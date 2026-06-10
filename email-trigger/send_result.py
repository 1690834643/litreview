#!/usr/bin/env python3
"""
send_result.py — 回信综述结果：Word 综述作邮件附件，源 PDF 上传腾讯服务器给随机下载链接。

可重复执行：对同一 outdir 多次调用都安全（token 存 06_download.txt 复用，不产生孤儿目录）。
产物目录里自动找：
  - 综述 docx（*.docx，优先含 report/综述 的）→ 邮件附件
  - 源 PDF 压缩包（sources*.zip）→ scp 到 server:<remote_dir>/<token>/ → 正文给 https 链接
  - 正文：email_body.md > summary.md（无则默认）；pending：05_pending_科研通.md

用法：
  python send_result.py --outdir <产物目录>            # 用 outdir/00_task.json，可重复重发
  python send_result.py --task t.json --outdir <目录>
  python send_result.py --outdir <目录> --dry-run
  python send_result.py --clarify t.clarify.json       # 发"请补主题"澄清信
"""
import argparse
import glob
import json
import os
import secrets
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.expanduser("~/.claude/skills/email-sender"))
import email_sender  # noqa: E402

import yaml  # noqa: E402


def load_config():
    for n in ("config.yaml", "config.example.yaml"):
        p = os.path.join(HERE, n)
        if os.path.exists(p):
            return yaml.safe_load(open(p, encoding="utf-8"))
    sys.exit("缺少 config.yaml")


def smtp_config(cfg):
    """复用 email-sender 的 QQ SMTP 凭据。"""
    return yaml.safe_load(open(cfg["mailbox"]["creds_from"], encoding="utf-8"))


def collect(outdir, attach_docx=True):
    docs = sorted(glob.glob(os.path.join(outdir, "*.docx")),
                  key=lambda p: ("report" not in p.lower() and "综述" not in p)) if attach_docx else []
    zips = sorted(glob.glob(os.path.join(outdir, "sources*.zip")))
    return docs, zips


def upload_zips(zips, outdir, deliv):
    """scp 上传到 server:<remote_dir>/<token>/。token 存 06_download.txt 复用。
    返回 (base_url, [urls], err)。失败 err 非空。"""
    urlfile = os.path.join(outdir, "06_download.txt")
    if os.path.exists(urlfile):
        base = open(urlfile, encoding="utf-8").read().strip()
        token = base.rstrip("/").split("/")[-1]
    else:
        token = "lr" + "".join(c for c in secrets.token_urlsafe(12) if c.isalnum())[:14]
        base = deliv["base_url"].rstrip("/") + "/" + token
    key = os.path.expanduser(deliv["ssh_key"])
    host, port, user = deliv["host"], str(deliv["ssh_port"]), deliv["ssh_user"]
    rdir = deliv["remote_dir"].rstrip("/") + "/" + token
    ssh = ["ssh", "-p", port, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
           "-i", key, f"{user}@{host}"]
    try:
        subprocess.run(ssh + [f"mkdir -p {shlex.quote(rdir)}"],
                       check=True, capture_output=True, timeout=30)
        subprocess.run(["scp", "-P", port, "-o", "StrictHostKeyChecking=no", "-i", key]
                       + zips + [f"{user}@{host}:{rdir}/"],
                       check=True, capture_output=True, timeout=900)
    except Exception as e:
        detail = getattr(e, "stderr", b"")
        detail = detail.decode("utf-8", "ignore")[:100] if isinstance(detail, bytes) else ""
        return None, [], f"{type(e).__name__} {detail}".strip()
    open(urlfile, "w", encoding="utf-8").write(base + "\n")
    return base, [base + "/" + os.path.basename(z) for z in zips], None


def build_body(outdir, task, download_urls, note, expire_days):
    for n in ("email_body.md", "summary.md"):
        p = os.path.join(outdir, n)
        if os.path.exists(p):
            body = open(p, encoding="utf-8").read()
            break
    else:
        body = f"# 文献综述完成\n\n**主题**：{task.get('intake', {}).get('topic', '')}\n\n详见附件 Word 综述。"
    if download_urls:
        body += f"\n\n---\n## 源 PDF 下载（链接约 {expire_days} 天后失效）\n\n"
        body += "\n".join(f"- {u}" for u in download_urls) + "\n"
    elif note:
        body += f"\n\n---\n## 源 PDF\n\n{note}\n"
    pend = os.path.join(outdir, "05_pending_科研通.md")
    if os.path.exists(pend):
        body += "\n\n---\n## 待补全文（科研通求助中/未到）\n\n" + open(pend, encoding="utf-8").read()
    return body


def send_result(task, outdir, dry_run=False):
    cfg = load_config()
    rep = cfg.get("reply", {})
    deliv = cfg.get("delivery", {})
    docs, zips = collect(outdir, rep.get("attach_docx", True))
    to = task.get("reply_to") or task.get("from")
    cc = rep.get("cc") or None
    subj = "Re: " + task.get("subject", "[综述] 结果")
    pdf_via = deliv.get("pdf_via", "server")
    expire = deliv.get("expire_days", 14)

    download_urls, note = [], ""
    if zips and pdf_via == "server":
        if dry_run:
            note = f"(dry-run 不上传) 将上传 {len(zips)} 个 zip 到 {deliv.get('base_url')}/<token>/"
        else:
            base, urls, err = upload_zips(zips, outdir, deliv)
            if err:
                note = f"源 PDF 上传失败（{err}）；本地在 {outdir}"
                print(f"# 上传失败: {err}", file=sys.stderr)
            else:
                download_urls = urls
    elif zips:
        note = f"源 PDF 未投递（pdf_via={pdf_via}）；本地在 {outdir}"

    body = build_body(outdir, task, download_urls, note, expire)

    if dry_run:
        print("=== DRY-RUN 回信预览 ===")
        print("收件人:", to, "\n抄送:", cc, "\n主题:", subj)
        print("Word 附件:", [os.path.basename(d) for d in docs])
        print("PDF:", [os.path.basename(z) for z in zips], "→", note or download_urls)
        print("正文前 300:\n", body[:300])
        return {"to": to, "cc": cc, "docx": docs, "download_urls": download_urls, "note": note, "dry_run": True}

    email_sender.send_markdown_email(to=to, subject=subj, markdown_body=body,
                                     cc=cc, attachments=docs, config=smtp_config(cfg))
    print(f"# 已回信 {to} · 抄送 {cc} · Word 附件 {len(docs)} · PDF 下载链接 {len(download_urls)}", file=sys.stderr)
    return {"to": to, "cc": cc, "subject": subj, "docx": docs, "download_urls": download_urls, "note": note}


def send_clarify(task, dry_run=False, body=None):
    cfg = load_config()
    to = task.get("reply_to") or task.get("from")
    cc = cfg.get("reply", {}).get("cc") or None
    subj = "Re: " + task.get("subject", "[综述] 请补充信息")
    if not body:
        body = (
            "# 综述任务缺少必填项\n\n收到你的综述请求，但**没解析到「主题」**。\n\n"
            "请回复并在正文按模板补全（至少要有 `暗号` 和 `主题`），例如：\n\n"
            "```\n暗号: <你的暗号>\n主题: 鳞翅目性别决定的趋同演化\n范围: Masc/piRNA/dsx；近10年\n篇数: 分诊60 精读20\n```\n"
        )
    if dry_run:
        print("=== DRY-RUN 澄清信 ===\n收件人:", to, "\n抄送:", cc, "\n主题:", subj, "\n", body[:300])
        return
    email_sender.send_markdown_email(to=to, subject=subj, markdown_body=body,
                                     cc=cc, config=smtp_config(cfg))
    print(f"# 已发澄清信 {to} · 抄送 {cc}", file=sys.stderr)


def _load_task(args):
    if args.task:
        return json.load(open(args.task, encoding="utf-8"))
    tp = os.path.join(args.outdir, "00_task.json")
    if not os.path.exists(tp):
        sys.exit("未给 --task 且 outdir 无 00_task.json")
    return json.load(open(tp, encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description="回信综述结果（Word 附件 + PDF 服务器下载链接）")
    ap.add_argument("--task", help="任务 JSON；省略则用 outdir/00_task.json（便于重发）")
    ap.add_argument("--outdir", help="产物目录")
    ap.add_argument("--clarify", help="澄清任务 JSON（缺主题时）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.clarify:
        send_clarify(json.load(open(args.clarify, encoding="utf-8")), dry_run=args.dry_run)
        return
    if not args.outdir:
        ap.error("需要 --outdir（或 --clarify）")
    send_result(_load_task(args), args.outdir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
