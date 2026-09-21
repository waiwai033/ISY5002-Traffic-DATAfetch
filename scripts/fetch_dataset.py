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

REPO = "waiwai033/ISY5002-Sentosa-Traffic"


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
