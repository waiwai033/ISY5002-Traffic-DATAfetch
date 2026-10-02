#!/usr/bin/env python3
"""Create portable GitHub Release archives from a merged camera dataset.

Python's tarfile does not synthesize macOS AppleDouble ``._`` entries, which
made the first release appear to contain twice as many images on Windows.
"""
import argparse
import csv
import hashlib
import tarfile
from pathlib import Path

def files_under(path):
    return sorted(p for p in path.rglob("*") if p.is_file()
                  and p.name != ".DS_Store" and not p.name.startswith("._"))


def pack(target, dataset, paths):
    with tarfile.open(target, "w:gz") as archive:
        for path in paths:
            archive.add(path, arcname=path.relative_to(dataset), recursive=False)
    with tarfile.open(target, "r:gz") as archive:
        names = [member.name for member in archive.getmembers() if member.isfile()]
    if len(names) != len(paths) or any(Path(name).name.startswith("._") for name in names):
        raise RuntimeError(f"Archive verification failed: {target}")
    print(f"{target.name}: {len(names):,} files, {target.stat().st_size / 1048576:.1f} MiB")


def verify_images(dataset, images):
    expected = {}
    with (dataset / "manifest.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["status"] == "downloaded" and row["image_path"]:
                expected[row["image_path"]] = row["sha256"]
    actual = {str(path.relative_to(dataset)) for path in images}
    if actual != set(expected):
        raise RuntimeError(f"Image/manifest mismatch: {len(actual - expected)} extra, "
                           f"{len(set(expected) - actual)} missing")
    for path in images:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != expected[str(path.relative_to(dataset))]:
            raise RuntimeError(f"Image sha256 mismatch: {path}")
    print(f"Verified {len(images):,} JPEGs against manifest SHA-256")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    dataset, out = args.dataset.resolve(), args.out.resolve()
    required = ("README.md", "manifest.csv", "distribution.html", "distribution.csv")
    if any(not (dataset / name).is_file() for name in required):
        raise SystemExit("Dataset metadata is incomplete")
    images = files_under(dataset / "images")
    if not images or any(p.suffix.lower() != ".jpg" for p in images):
        raise SystemExit("No JPEG images found, or unexpected files in images/")
    verify_images(dataset, images)
    gallery = files_under(dataset / "gallery")
    if not (dataset / "gallery/index.html").is_file():
        raise SystemExit("Gallery is missing")
    out.mkdir(parents=True, exist_ok=True)
    pack(out / "metadata.tar.gz", dataset, [dataset / name for name in required])
    pack(out / "images.tar.gz", dataset, images)
    pack(out / "gallery.tar.gz", dataset, gallery)
    with (out / "SHA256SUMS.txt").open("w", encoding="utf-8") as stream:
        for name in ("metadata.tar.gz", "images.tar.gz", "gallery.tar.gz"):
            with (out / name).open("rb") as archive:
                digest = hashlib.file_digest(archive, "sha256").hexdigest()
            stream.write(f"{digest}  {name}\n")
    print(f"Checksums: {out / 'SHA256SUMS.txt'}")


if __name__ == "__main__":
    main()
