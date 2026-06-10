#!/usr/bin/env python3
"""
easyscholar_rank.py — 期刊名 → 中科院分区/JCR/影响因子，带持久缓存。

设计要点（来自 grill 决策）：
- 先查本地缓存"已知名单"（~/.cache/easyscholar/cache.json）；命中直接用，不查接口。
- 只有缓存里没有的期刊才走 easyScholar API。
- API 有限流（约 2 次/秒；超了返回 code 40006 请求频繁）：LIVE 调用默认间隔
  0.6s（≈1.6 次/秒留余量）+ 命中 40006 指数退避重试。
- secretKey 从 repo 外路径读取（家目录是公开 git repo，key 绝不入库）。

用法：
  python easyscholar_rank.py "Nature" "Molecular Ecology"   # 查若干期刊
  python easyscholar_rank.py --file journals.txt            # 文件每行一个
  cat journals.txt | python easyscholar_rank.py --stdin
  python easyscholar_rank.py --list                         # 列已知名单（缓存）
  python easyscholar_rank.py --no-live "X"                  # 只用缓存，不查接口
  python easyscholar_rank.py "Nature" --out ranks.json      # 结果写 JSON
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

KEY_PATHS = [
    os.path.expanduser("~/.config/easyscholar/key.txt"),
]
CACHE_PATH = os.path.expanduser("~/.cache/easyscholar/cache.json")
API = "https://www.easyscholar.cc/open/getPublicationRank"

# 我们保留的字段（其余高校自定义分区忽略）
KEEP = {
    "sciUp": "中科院大类",
    "sciUpSmall": "中科院小类",
    "sciUpTop": "中科院TOP",
    "sciBase": "中科院基础版",
    "sciif": "IF",
    "sciif5": "IF5",
    "sci": "JCR",
    "jci": "JCI",
    "esi": "ESI",
}


def load_key():
    env = os.environ.get("EASYSCHOLAR_KEY")
    if env:
        return env.strip()
    for p in KEY_PATHS:
        if os.path.exists(p):
            k = open(p, encoding="utf-8").read().strip()
            if k:
                return k
    sys.exit(
        "未找到 easyScholar secretKey。请写入 ~/.config/easyscholar/key.txt "
        "或设置环境变量 EASYSCHOLAR_KEY。"
    )


def normalize(name):
    n = (name or "").strip().lower()
    n = re.sub(r"\s+", " ", n)
    n = n.rstrip(". ")
    return n


def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            return json.load(open(CACHE_PATH, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    json.dump(cache, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, CACHE_PATH)


def tidy(raw_all, queried_name):
    """从 officialRank.all 抽出我们要的字段。"""
    out = {"matched_name": queried_name}
    for k in KEEP:
        v = (raw_all or {}).get(k)
        if v not in (None, ""):
            out[k] = v
    return out


def query_api(name, key, throttle=0.6, max_retry=4):
    """单期刊 LIVE 查询，带 40006 退避重试。返回 tidy dict 或 {'error':...}。"""
    url = API + "?" + urllib.parse.urlencode({"secretKey": key, "publicationName": name})
    backoff = 2
    for attempt in range(max_retry):
        try:
            r = json.load(urllib.request.urlopen(url, timeout=30))
        except Exception as e:
            return {"error": f"{type(e).__name__}: {str(e)[:120]}"}
        if not isinstance(r, dict):  # 网关/代理异常可能返回数组或 HTML
            return {"error": f"非预期返回类型 {type(r).__name__}"}
        code = r.get("code")
        if code == 200:
            data = r.get("data") if isinstance(r.get("data"), dict) else {}
            off = data.get("officialRank") if isinstance(data.get("officialRank"), dict) else {}
            all_ = off.get("all") if isinstance(off.get("all"), dict) else {}
            time.sleep(throttle)  # 限速 2 次/秒：成功后也歇 0.6s
            if not all_:
                return {"error": "无分区数据（期刊名可能不匹配）"}
            return tidy(all_, name)
        if code == 40006:  # 请求频繁
            time.sleep(backoff)
            backoff *= 2
            continue
        return {"error": f"code={code} msg={r.get('msg')}"}
    return {"error": "40006 限流重试耗尽"}


def get_rank(name, key=None, cache=None, live=True, throttle=0.6):
    """主入口：先缓存后接口。可被其它脚本 import。"""
    cache = cache if cache is not None else load_cache()
    nk = normalize(name)
    if nk in cache:
        rec = dict(cache[nk])
        rec["_source"] = "cache"
        return rec
    if not live:
        return {"matched_name": name, "_source": "miss", "error": "缓存未命中且 --no-live"}
    key = key or load_key()
    res = query_api(name, key, throttle=throttle)
    res["query"] = name
    if "error" not in res:
        cache[nk] = res
        save_cache(cache)
        res = dict(res)
        res["_source"] = "live"
    else:
        res["_source"] = "live-error"
    return res


def fmt_line(name, r):
    if "error" in r:
        return f"  {name:50.50s} | ✗ {r['error']}  [{r.get('_source','')}]"
    bits = []
    if r.get("sciUp"):
        bits.append(r["sciUp"] + ("·TOP" if r.get("sciUpTop") else ""))
    if r.get("sciUpSmall"):
        bits.append(r["sciUpSmall"])
    if r.get("sci"):
        bits.append("JCR " + r["sci"])
    if r.get("sciif"):
        bits.append("IF " + str(r["sciif"]))
    return f"  {name:50.50s} | " + " | ".join(bits) + f"  [{r.get('_source','')}]"


def main():
    ap = argparse.ArgumentParser(description="期刊 → 中科院分区/IF（带缓存）")
    ap.add_argument("journals", nargs="*", help="期刊名")
    ap.add_argument("--file", help="文件，每行一个期刊名")
    ap.add_argument("--stdin", action="store_true", help="从 stdin 读，每行一个")
    ap.add_argument("--list", action="store_true", help="列出缓存里的已知名单")
    ap.add_argument("--no-live", action="store_true", help="只用缓存，不查接口")
    ap.add_argument("--throttle", type=float, default=0.6, help="LIVE 调用间隔秒（接口限速 2 次/秒）")
    ap.add_argument("--out", help="结果写入 JSON 文件")
    args = ap.parse_args()

    cache = load_cache()

    if args.list:
        print(f"# 已知名单（缓存 {CACHE_PATH}，共 {len(cache)} 条）")
        for nk in sorted(cache):
            print(fmt_line(cache[nk].get("query", nk), {**cache[nk], "_source": "cache"}))
        return

    names = list(args.journals)
    if args.file:
        names += [l.strip() for l in open(args.file, encoding="utf-8") if l.strip()]
    if args.stdin:
        names += [l.strip() for l in sys.stdin if l.strip()]
    if not names:
        ap.error("没有期刊名。给出参数，或用 --file/--stdin，或 --list 看缓存。")

    key = None if args.no_live else load_key()
    results = {}
    n_live = n_cache = 0
    for nm in names:
        r = get_rank(nm, key=key, cache=cache, live=not args.no_live, throttle=args.throttle)
        results[nm] = r
        if r.get("_source") == "cache":
            n_cache += 1
        elif r.get("_source", "").startswith("live"):
            n_live += 1
        print(fmt_line(nm, r))
    print(f"\n# 命中缓存 {n_cache} · 走接口 {n_live} · 缓存现有 {len(cache)} 条", file=sys.stderr)

    if args.out:
        json.dump(results, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"# 结果写入 {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
