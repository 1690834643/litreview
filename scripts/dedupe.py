#!/usr/bin/env python3
"""
dedupe.py — 多来源文献记录去重（Scholar / PubMed / 出版社 合并时用）。

强键：DOI（归一化）。弱键 fallback：归一化标题。
合并同一条目的多来源 source 标记，保留信息最全的字段。

输入：JSON 数组，每条至少含 title，可选 doi / year / authors / journal / source / url ...
输出：去重后的 JSON 数组（stdout 或 --out）。

用法：
  python dedupe.py records.json --out clean.json
  cat records.json | python dedupe.py
"""
import argparse
import json
import re
import sys


def norm_doi(doi):
    if not doi:
        return ""
    d = str(doi).strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = d.replace("doi:", "").strip()
    return d


def norm_title(t):
    if not t:
        return ""
    t = str(t).lower()
    t = re.sub(r"[^a-z0-9一-鿿]+", "", t)  # 去标点空格，保中英数字
    return t


def richer(a, b):
    """合并 b 进 a：缺字段补全，source 合并。返回 a。"""
    for k, v in b.items():
        if k == "source":
            continue
        if not a.get(k) and v:
            a[k] = v
    src = set()
    for r in (a, b):
        s = r.get("source")
        if isinstance(s, list):
            src.update(s)
        elif s:
            src.add(s)
    if src:
        a["source"] = sorted(src)
    return a


def dedupe(records):
    """双索引：DOI 与归一化标题都指向同一条，解决"一份有 DOI 一份没有"的跨源同篇。"""
    by_doi, by_title = {}, {}
    out = []  # 合并后的记录，按首见顺序
    for rec in records:
        d = norm_doi(rec.get("doi"))
        t = norm_title(rec.get("title"))
        if not d and not t:  # 空记录跳过
            continue
        target = None
        if d and d in by_doi:
            target = by_doi[d]
        elif t and t in by_title:
            cand = by_title[t]
            cand_doi = norm_doi(cand.get("doi"))
            # 标题命中：仅当任一方无 DOI 或 DOI 相同才算同篇（防同名不同 DOI 误合并）
            if not d or not cand_doi or d == cand_doi:
                target = cand
        if target is None:
            target = dict(rec)
            out.append(target)
        else:
            richer(target, rec)
        if t:
            by_title[t] = target
        if d:
            by_doi[d] = target
    return out


def main():
    ap = argparse.ArgumentParser(description="文献记录去重（DOI 优先，标题 fallback）")
    ap.add_argument("infile", nargs="?", help="输入 JSON 数组；省略则读 stdin")
    ap.add_argument("--out", help="输出文件；省略则 stdout")
    args = ap.parse_args()

    raw = open(args.infile, encoding="utf-8").read() if args.infile else sys.stdin.read()
    records = json.loads(raw)
    if not isinstance(records, list):
        sys.exit("输入必须是 JSON 数组")

    clean = dedupe(records)
    out = json.dumps(clean, ensure_ascii=False, indent=2)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(out)
        print(f"# 去重：{len(records)} → {len(clean)} 条，写入 {args.out}", file=sys.stderr)
    else:
        print(out)
        print(f"# 去重：{len(records)} → {len(clean)} 条", file=sys.stderr)


if __name__ == "__main__":
    main()
