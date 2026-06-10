#!/usr/bin/env python3
"""
zip_pdfs.py — 把下载的源 PDF 压缩成附件，超过邮箱上限自动拆卷。

QQ 邮箱 SMTP 单封附件上限约 50MB，默认阈值设 45MB 留余量。
若所有 PDF 压缩后 ≤ 阈值 → 单个 sources.zip。
若超过 → 贪心拆成 sources.part1.zip / part2.zip ...（每卷 ≤ 阈值）。
单个 PDF 本身就超阈值时，单独成卷并在 manifest 标注 oversize（发信端据此决定降级）。

输出 JSON manifest（stdout 或 --out）：
  {"zips": [...绝对路径...], "total_mb": .., "split": bool, "oversize": [...], "count": N}

用法：
  python zip_pdfs.py /path/to/pdf_dir --out manifest.json
  python zip_pdfs.py /path/to/pdf_dir --max-mb 45 --prefix sources
"""
import argparse
import json
import os
import sys
import zipfile

MB = 1024 * 1024


def compressed_size(path):
    """估算单文件压缩后大小：实压到临时 zip 量一次（PDF 多已压缩，省得猜）。"""
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(path, arcname=os.path.basename(path))
    return buf.tell()


def main():
    ap = argparse.ArgumentParser(description="压缩源 PDF 为邮件附件，超限拆卷")
    ap.add_argument("pdf_dir", help="存放 PDF 的目录")
    ap.add_argument("--out", help="manifest JSON 输出路径")
    ap.add_argument("--max-mb", type=float, default=45.0, help="单卷上限 MB（默认 45）")
    ap.add_argument("--prefix", default="sources", help="zip 文件名前缀")
    ap.add_argument("--outdir", help="zip 输出目录（默认 pdf_dir 的父目录）")
    args = ap.parse_args()

    pdf_dir = os.path.abspath(args.pdf_dir)
    if not os.path.isdir(pdf_dir):
        sys.exit(f"目录不存在：{pdf_dir}")
    outdir = os.path.abspath(args.outdir) if args.outdir else os.path.dirname(pdf_dir)
    os.makedirs(outdir, exist_ok=True)
    cap = args.max_mb * MB

    pdfs = sorted(
        os.path.join(pdf_dir, f) for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")
    )
    if not pdfs:
        manifest = {"zips": [], "total_mb": 0, "split": False, "oversize": [], "count": 0,
                    "note": "目录内无 PDF"}
        _emit(manifest, args.out)
        return

    sizes = [(p, compressed_size(p)) for p in pdfs]
    oversize = [os.path.basename(p) for p, s in sizes if s > cap]

    # 贪心装卷
    volumes = []          # list of list[path]
    cur, cur_sz = [], 0
    for p, s in sizes:
        if s > cap:       # 单文件超限：自己一卷
            if cur:
                volumes.append(cur); cur, cur_sz = [], 0
            volumes.append([p])
            continue
        if cur_sz + s > cap and cur:
            volumes.append(cur); cur, cur_sz = [], 0
        cur.append(p); cur_sz += s
    if cur:
        volumes.append(cur)

    split = len(volumes) > 1
    zips = []
    for i, vol in enumerate(volumes, 1):
        name = f"{args.prefix}.zip" if not split else f"{args.prefix}.part{i}.zip"
        zpath = os.path.join(outdir, name)
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in vol:
                z.write(p, arcname=os.path.basename(p))
        zips.append(zpath)

    total_mb = round(sum(os.path.getsize(z) for z in zips) / MB, 2)
    manifest = {
        "zips": zips,
        "total_mb": total_mb,
        "split": split,
        "volumes": len(zips),
        "oversize": oversize,
        "count": len(pdfs),
    }
    _emit(manifest, args.out)


def _emit(manifest, out):
    s = json.dumps(manifest, ensure_ascii=False, indent=2)
    if out:
        open(out, "w", encoding="utf-8").write(s)
        print(f"# {manifest['count']} 个 PDF → {manifest.get('volumes',0)} 卷, "
              f"{manifest['total_mb']}MB, 写入 {out}", file=sys.stderr)
    else:
        print(s)


if __name__ == "__main__":
    main()
