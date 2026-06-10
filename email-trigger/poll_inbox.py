#!/usr/bin/env python3
"""
poll_inbox.py — 轮询 QQ 邮箱，挑出"综述触发"邮件，解析成任务。

判据（全部满足才算触发）：
  1) 主题以 trigger.subject_prefix 开头（默认 [综述]）
  2) 正文含 trigger.secret_token 暗号
  3) sender_whitelist 非空时，发件人须在白名单内
Message-ID 记入 state/seen_ids.txt 去重，不重复处理；不改邮件已读状态（非破坏）。

正文按 `键: 值` 解析（中英冒号都认）。必填=主题；缺主题→产出 clarification（回信要求补）。

用法：
  python poll_inbox.py --dry-run        # 只解析打印，不落队列
  python poll_inbox.py --emit-queue     # 把任务写进 state/queue/*.json
"""
import argparse
import email
import email.header
import hashlib
import imaplib
import json
import os
import re
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state")
QUEUE = os.path.join(STATE, "queue")
SEEN = os.path.join(STATE, "seen_ids.txt")

KEY_ALIASES = {
    "token": ["暗号", "token", "口令", "密令"],
    "topic": ["主题", "题目", "综述主题", "topic"],
    "question": ["要解决的问题", "拟解决的问题", "核心问题", "研究问题", "question"],
    "scope": ["范围", "边界", "scope"],
    "timewin": ["时间窗", "年份", "时间范围", "years"],
    "tier": ["重点期刊分区", "分区门槛", "期刊层级", "tier"],
    "count": ["篇数", "数量", "count"],
    "words": ["字数", "篇幅", "words"],
    "seeds": ["必读文献", "种子文献", "必读", "seeds"],
    "reply_to": ["回信地址", "回复地址", "reply"],
    "notes": ["备注", "其它", "其他", "notes"],
}
_ALIAS2KEY = {a.lower(): k for k, al in KEY_ALIASES.items() for a in al}


def load_yaml(path):
    import yaml
    return yaml.safe_load(open(path, encoding="utf-8"))


def load_config():
    for n in ("config.yaml", "config.example.yaml"):
        p = os.path.join(HERE, n)
        if os.path.exists(p):
            return load_yaml(p)
    sys.exit("缺少 config.yaml（可由 config.example.yaml 复制）")


def imap_creds(cfg):
    cf = load_yaml(cfg["mailbox"]["creds_from"])["smtp"]
    return cf["user"], cf["password"]


def _safe_decode(b, enc=None):
    """对未知/非法 charset（如 QQ 常见的 unknown-8bit）多候选回退，latin-1 永不失败。"""
    for cand in (enc, "utf-8", "gb18030", "latin-1"):
        if not cand:
            continue
        try:
            return b.decode(cand, "ignore")
        except (LookupError, UnicodeDecodeError):
            continue
    return b.decode("utf-8", "ignore")


def _decode(s):
    if not s:
        return ""
    parts = email.header.decode_header(s)
    out = []
    for txt, enc in parts:
        out.append(_safe_decode(txt, enc) if isinstance(txt, bytes) else txt)
    return "".join(out)


def _html_to_text(html):
    """块级标签转换行后再去标签，避免整封 HTML 塌成一行导致只解析到第一个字段。"""
    html = re.sub(r"(?i)<\s*br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</\s*(p|div|tr|li|h[1-6]|table|blockquote)\s*>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&")):
        text = text.replace(a, b)
    return text


def get_body_text(msg):
    """取 text/plain 正文（优先），否则把 html 转带换行的文本。"""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                pl = part.get_payload(decode=True)
                if pl:
                    return _safe_decode(pl, part.get_content_charset())
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                pl = part.get_payload(decode=True)
                if pl:
                    return _html_to_text(_safe_decode(pl, part.get_content_charset()))
        return ""
    pl = msg.get_payload(decode=True)
    return _safe_decode(pl, msg.get_content_charset()) if pl else ""


def parse_intake(body):
    intake = {}
    for line in body.splitlines():
        if line.lstrip().startswith(">"):  # 跳过引用/转发的历史正文，避免 first-wins 取到旧字段
            continue
        m = re.match(r"\s*([^:：]{1,20})[:：]\s*(.+?)\s*$", line)
        if not m:
            continue
        k = _ALIAS2KEY.get(m.group(1).strip().lower())
        if k and k not in intake:
            intake[k] = m.group(2).strip()
    return intake


def load_seen():
    if os.path.exists(SEEN):
        return set(l.strip() for l in open(SEEN, encoding="utf-8") if l.strip())
    return set()


def add_seen(mid):
    os.makedirs(STATE, exist_ok=True)
    with open(SEEN, "a", encoding="utf-8") as f:
        f.write(mid + "\n")


def addr_of(raw_from):
    m = re.search(r"[\w.+-]+@[\w.-]+", raw_from or "")
    return m.group(0).lower() if m else ""


def poll(cfg, since_days=3, max_scan=400):
    user, pw = imap_creds(cfg)
    prefix = cfg["trigger"]["subject_prefix"]
    token = str(cfg["trigger"]["secret_token"])
    whitelist = [a.lower() for a in (cfg["trigger"].get("sender_whitelist") or [])]
    seen = load_seen()

    M = imaplib.IMAP4_SSL(cfg["mailbox"]["imap_host"], cfg["mailbox"].get("imap_port", 993))
    M.login(user, pw)
    M.select("INBOX", readonly=True)
    since = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    typ, data = M.search(None, f'(SINCE {since})')
    ids = data[0].split() if data and data[0] else []
    ids = ids[-max_scan:]  # 只看最近 max_scan 封

    # 注意：这里不写 seen。seen 由 main() 在任务真正落盘后再记，避免崩在落盘前永久丢任务。
    tasks, clarifications, skipped_mids = [], [], []
    try:
        for num in reversed(ids):  # 新→旧
            try:
                # 先只取头部，廉价筛主题前缀 + Message-ID 去重（BODY.PEEK 不置 \Seen）
                typ, hd = M.fetch(num, "(BODY.PEEK[HEADER.FIELDS (SUBJECT MESSAGE-ID)])")
                if typ != "OK" or not hd or not hd[0]:
                    continue
                head = email.message_from_bytes(hd[0][1])
                mid = (head.get("Message-ID") or f"nomid-{num.decode()}").strip()
                if mid in seen:
                    continue
                subject = _decode(head.get("Subject"))
                if not subject.strip().startswith(prefix):
                    continue
                # 命中前缀才整封拉取（拿正文/发件人）
                typ, msgdata = M.fetch(num, "(RFC822)")
                if typ != "OK" or not msgdata or not msgdata[0]:
                    continue
                msg = email.message_from_bytes(msgdata[0][1])
                sender = addr_of(_decode(msg.get("From")))
                body = get_body_text(msg)
                intake = parse_intake(body)

                # 暗号校验（防滥用）
                if token not in body and intake.get("token") != token:
                    skipped_mids.append(mid); continue
                # 白名单
                if whitelist and sender not in whitelist:
                    skipped_mids.append(mid); continue

                reply_to = intake.get("reply_to") or sender
                topic = intake.get("topic") or subject.strip()[len(prefix):].strip()
                rec = {
                    # id 用 Message-ID 的 sha1 前 12 位：稳定且不被 qq.com 域名主导碰撞
                    "id": "t" + hashlib.sha1(mid.encode("utf-8")).hexdigest()[:12],
                    "message_id": mid, "from": sender, "reply_to": reply_to,
                    "subject": subject, "intake": {**intake, "topic": topic},
                    "created": datetime.now().isoformat(timespec="seconds"),
                }
                (clarifications if not topic else tasks).append(rec)
            except Exception as e:
                print(f"# 跳过一封异常邮件 {num}: {type(e).__name__}: {str(e)[:80]}",
                      file=sys.stderr)
                continue
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return tasks, clarifications, skipped_mids


def main():
    ap = argparse.ArgumentParser(description="轮询 QQ 邮箱挑综述触发邮件")
    ap.add_argument("--dry-run", action="store_true", help="只解析打印，不落队列、不记 seen")
    ap.add_argument("--emit-queue", action="store_true", help="任务写入 state/queue/*.json")
    ap.add_argument("--since-days", type=int, default=3)
    args = ap.parse_args()
    cfg = load_config()

    tasks, clar, skipped_mids = poll(cfg, since_days=args.since_days)
    print(f"# 命中任务 {len(tasks)} · 待澄清 {len(clar)} · 跳过(暗号/白名单) {len(skipped_mids)}",
          file=sys.stderr)
    for t in tasks:
        print(json.dumps(t, ensure_ascii=False))

    # 只有 --emit-queue（真正落盘）才记 seen；dry-run 不记，可反复看
    if args.emit_queue:
        os.makedirs(QUEUE, exist_ok=True)
        for t in tasks:
            json.dump(t, open(os.path.join(QUEUE, t["id"] + ".json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        for c in clar:
            c["_clarify"] = True
            json.dump(c, open(os.path.join(QUEUE, c["id"] + ".clarify.json"), "w",
                      encoding="utf-8"), ensure_ascii=False, indent=2)
        # 落盘成功后再记 seen（崩在落盘前不会永久丢任务）
        for mid in [t["message_id"] for t in tasks] + \
                   [c["message_id"] for c in clar] + skipped_mids:
            add_seen(mid)
        print(f"# 写入队列 {QUEUE}，记 seen {len(tasks)+len(clar)+len(skipped_mids)} 条",
              file=sys.stderr)


if __name__ == "__main__":
    main()
