#!/usr/bin/env python3
"""Pull every collected artifact into one merged, de-duplicated dataset.

Collection ran as ~30 separate GitHub windows, so the images arrive as dozens of
artifacts that each hold a slice of the week plus their own manifest. This walks
them into a single tree and one manifest, and is safe to re-run: artifacts
already fetched are skipped.
"""
import argparse
import csv
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from fetch_lta_camera_images import FIELDS, ROOT

REPO = "waiwai033/ISY5002-Traffic-DATAfetch"


def gh(args):
    done = subprocess.run(args, capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(done.stderr.strip() or " ".join(args))
    return done.stdout


def artifacts(repo):
    raw = gh(["gh", "api", f"repos/{repo}/actions/artifacts", "--paginate",
              "--jq", '.artifacts[] | select(.expired==false) | '
                      '{id:.id, run:.workflow_run.id, name:.name, size:.size_in_bytes}'])
    seen, out = set(), []
    for line in raw.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item["run"] not in seen:
            seen.add(item["run"])
            out.append(item)
    return out


def download(repo, items, cache):
    cache.mkdir(parents=True, exist_ok=True)
    for n, item in enumerate(items, 1):
        target = cache / str(item["run"])
        if target.exists() and any(target.rglob("*.jpg")):
            print(f"  [{n}/{len(items)}] run {item['run']} cached")
            continue
        print(f"  [{n}/{len(items)}] run {item['run']} ({item['size']/1048576:.0f} MB)...")
        try:
            gh(["gh", "run", "download", str(item["run"]), "--repo", repo, "--dir", str(target)])
        except RuntimeError as error:
            print(f"      skipped: {error}")
            shutil.rmtree(target, ignore_errors=True)


def merge(cache, out):
    """Identical frames carry identical names, so the tree collapses on copy."""
    images = out / "images"
    images.mkdir(parents=True, exist_ok=True)
    copied = kept = 0
    for source in cache.rglob("*.jpg"):
        if source.parent.parent.name != "images":
            continue
        target = images / source.parent.name / source.name
        if target.exists():
            kept += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1

    rows, seen = [], set()
    for manifest in sorted(cache.rglob("manifest.csv")):
        with manifest.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                key = (row.get("collected_at_utc"), row.get("camera_id"))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
    rows.sort(key=lambda r: (r.get("collected_at_utc", ""), r.get("camera_id", "")))
    with (out / "manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return copied, kept, rows


README = """# Sentosa / 新柔通道 交通摄像头数据集

由 `scripts/fetch_dataset.py` 生成于 {built}。
采集自 [data.gov.sg 实时交通图像接口](https://api.data.gov.sg/v1/transport/traffic-images)，
经由 GitHub Actions 连续运行约 30 个采集窗口完成。

采集区间：{first} → {last} UTC

## 目录结构

```
dataset/
├── README.md          本文件
├── manifest.csv       {obs:,} 条观测记录
├── images/            {files:,} 张图片（{size:.2f} GB）
│   └── <camera_id>/<拍摄时间>Z_<id>_<时分>_<内容哈希>.jpg
└── gallery/           可浏览相册（见文末）
```

## 为什么是 {files:,} 张图片，却有 {obs:,} 条观测记录

**两者计的不是同一件事。**

- `manifest.csv` 的一行 = **一次请求**：某个时刻向某台摄像头要过一次画面，不论结果如何
- `images/` 的一个文件 = **一帧不重复的画面**

每 10 分钟一轮、每轮 8 台摄像头，只要发起请求就会留下一条记录 —— 即使没拿到新画面。
差额 {gap:,} 条正是"请求了但没产生新文件"的部分：

| 状态 | 条数 | 是否产生文件 | 含义 |
|---|---:|---|---|
| `downloaded` | {downloaded:,} | 是 | 成功取得画面 |
| `stale` | {stale:,} | 否 | 画面距拍摄已超过新鲜度上限，判定为过期 |
| `duplicate` | {duplicate:,} | 否 | 画面内容与上次完全相同（sha256 一致），不重复存盘 |
| `missing` | {missing:,} | 否 | 接口本轮未返回这台摄像头 |
| `error` | {error:,} | 否 | 请求或下载失败 |
| **合计** | **{obs:,}** | | |

逐步对账：

```
{obs:,} 条观测
  − {noimage:,} 条无画面（stale {stale} + missing {missing} + error {error}）
  − {duplicate:,} 条画面未变化（duplicate，不写新文件）
  = {downloaded:,} 条 downloaded
  − {overlap:,} 条同一帧被两个重叠窗口各取了一次
  = {files:,} 张不重复画面  ← 与 images/ 实际文件数一致
```

最后那 {overlap:,} 条值得说明：采集窗口之间有少量时间重叠，重叠期内两个窗口会各自
请求同一时刻的画面。它们拿到的是**同一帧**，文件名（含拍摄时间与内容哈希）完全相同，
合并时自然覆盖为一个文件，但两次请求都各自留下了记录。

> 校验结果：`downloaded` 记录指向的文件 **{files:,} 个全部存在**，
> `images/` 中也**没有**任何缺少对应记录的孤儿文件。

## manifest.csv 字段

| 字段 | 说明 |
|---|---|
| `collected_at_utc` / `collected_at_sgt` | **发起请求**的时刻 |
| `captured_at_utc` / `captured_at_sgt` | 画面的**实际拍摄**时刻（来自接口） |
| `timestamp_basis` | 拍摄时刻的来源；`source` 表示由接口提供 |
| `camera_id` `road_segment` `direction` | 摄像头标识与位置 |
| `status` | 见上表 |
| `image_path` | 相对 `dataset/` 的图片路径；仅 `downloaded` 有值 |
| `sha256` `bytes` | 图片内容哈希与大小 |
| `source_url` `error` | 原始链接；失败时的错误说明 |

做时间序列分析时请用 **`captured_at_utc`** 而非 `collected_at_utc` ——
两者的差值即"帧龄"，静止时段可达数小时。

## 已知特征

**凌晨时段样本较稀疏。** 摄像头在深夜会长时间不刷新画面（实测最长 215 分钟）。
采集前期的新鲜度上限是 15 分钟，导致 9/14–9/15 两天凌晨的画面被大量判为 `stale` 丢弃；
9/16 起上限调整为 240 分钟后，凌晨轮次恢复完整。因此 **9/14–9/15 的 00:00–07:00
时段数据量明显低于其后几天**，建模时请注意这段的采样偏差。

## 浏览

相册需通过 HTTP 打开（浏览器不允许 `file://` 页面读取同目录以外的图片）：

```bash
cd <dataset 的上级目录> && python3 -m http.server 8791
```

然后访问 http://localhost:8791/dataset/gallery/index.html

支持按摄像头、日期、时段筛选；网格视图缩略图浏览、点击放大；
时间轴视图把单台摄像头的序列当延时片播放。
"""


def write_readme(out, rows, files, size, first, last):
    """Generated from the data itself, so the counts cannot drift from reality."""
    import datetime
    st = Counter(r.get("status", "") for r in rows)
    downloaded = st["downloaded"]
    noimage = st["stale"] + st["missing"] + st["error"]
    (out / "README.md").write_text(README.format(
        built=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        first=first[:16], last=last[:16],
        obs=len(rows), files=files, size=size / 1073741824,
        downloaded=downloaded, stale=st["stale"], duplicate=st["duplicate"],
        missing=st["missing"], error=st["error"],
        noimage=noimage, gap=len(rows) - files,
        overlap=downloaded - files), encoding="utf-8")


def report(out, rows):
    files = list((out / "images").rglob("*.jpg"))
    size = sum(f.stat().st_size for f in files)
    per_camera = Counter(f.parent.name for f in files)
    status = Counter(r.get("status", "") for r in rows)
    stamps = sorted(r["collected_at_utc"] for r in rows if r.get("collected_at_utc"))
    print(f"\n  images      {len(files):,}  ({size/1073741824:.2f} GB)")
    print(f"  manifest    {len(rows):,} observations")
    if stamps:
        print(f"  covering    {stamps[0][:16]} -> {stamps[-1][:16]} UTC")
    print(f"  per camera  " + "  ".join(f"{c}:{n}" for c, n in sorted(per_camera.items())))
    print(f"  status      " + "  ".join(f"{s}:{n}" for s, n in status.most_common()))
    write_readme(out, rows, len(files), size,
                 stamps[0] if stamps else "", stamps[-1] if stamps else "")
    print(f"  README.md   written with the observation/file reconciliation")
    print(f"\n  dataset at  {out}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--cache", type=Path, default=ROOT / "data/github/all",
                        help="Where raw artifacts land; re-runs reuse it")
    parser.add_argument("--out", type=Path, default=ROOT / "data/dataset")
    parser.add_argument("--skip-download", action="store_true",
                        help="Merge what is already cached")
    args = parser.parse_args(argv)
    if not args.skip_download:
        items = artifacts(args.repo)
        print(f"{len(items)} artifact run(s) available:")
        download(args.repo, items, args.cache)
    print("\nmerging...")
    copied, kept, rows = merge(args.cache, args.out)
    print(f"  {copied:,} new frames, {kept:,} already present (duplicates across windows)")
    report(args.out, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
