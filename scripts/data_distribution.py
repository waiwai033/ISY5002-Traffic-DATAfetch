#!/usr/bin/env python3
"""Summarise how the collected frames are distributed across time and cameras.

Writes a text summary, a CSV of every breakdown, and an HTML report whose charts
are inline SVG so the report opens anywhere with no dependencies.
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from fetch_lta_camera_images import ROOT, SG, load_cameras

KEPT = ("downloaded", "duplicate")          # the request yielded usable data
LOST = ("stale", "missing", "error")        # the request yielded nothing


def load(dataset):
    path = dataset / "manifest.csv"
    if not path.exists():
        raise SystemExit(f"No manifest at {path}; run scripts/fetch_dataset.py first")
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    for row in rows:
        stamp = row.get("captured_at_utc") or row.get("collected_at_utc")
        row["_when"] = datetime.fromisoformat(stamp).astimezone(SG) if stamp else None
        collected = row.get("collected_at_utc")
        captured = row.get("captured_at_utc")
        row["_age"] = ((datetime.fromisoformat(collected) - datetime.fromisoformat(captured)
                        ).total_seconds() / 60) if collected and captured else None
    return rows


def breakdowns(rows, cameras):
    # Count distinct image files, not "kept" observations: a duplicate row means the
    # frame had not changed, so it adds an observation but no new sample. Counting
    # rows here would put these charts at odds with the dataset's own file count.
    seen, kept = set(), []
    for r in rows:
        if r["status"] != "downloaded" or not r.get("image_path"):
            continue
        name = Path(r["image_path"]).name
        if name in seen:
            continue
        seen.add(name)
        kept.append(r)
    out = {
        "hour": Counter(r["_when"].hour for r in kept if r["_when"]),
        "day": Counter(r["_when"].strftime("%m-%d") for r in kept if r["_when"]),
        "camera": Counter(r["camera_id"] for r in kept),
        "status": Counter(r["status"] for r in rows),
        "segment": Counter(r["road_segment"] for r in kept),
    }
    ages = sorted(r["_age"] for r in kept if r["_age"] is not None)
    buckets = Counter()
    for age in ages:
        for edge, label in ((5, "0–5"), (10, "5–10"), (15, "10–15"), (30, "15–30"),
                            (60, "30–60"), (120, "60–120"), (10**9, "120+")):
            if age < edge:
                buckets[label] += 1
                break
    out["age"] = buckets
    out["_ages"] = ages
    return out


# ---------- SVG ----------
W, PAD = 760, {"l": 46, "r": 14, "t": 12, "b": 34}
MAXBAR = 46          # thin marks: a handful of categories must not become slabs


def nice_top(value, steps=4):
    """Round the axis up to a readable step so ticks are 250/500/... not 1432/2863."""
    if value <= 0:
        return steps, 1
    import math
    raw = value / steps
    mag = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 2.5, 5, 10):
        if raw <= mag * mult:
            step = mag * mult
            break
    step = int(step) if step >= 1 else step
    return step * steps, step


def bars_v(data, height=190, fmt=str):
    """Vertical bars: ordered dimension, one series, 4px rounded top, 2px gap."""
    keys = list(data)
    top, step = nice_top(max(data.values()) or 1)
    plot_w = W - PAD["l"] - PAD["r"]
    plot_h = height - PAD["t"] - PAD["b"]
    slot = plot_w / len(keys)
    bw = min(MAXBAR, max(3.0, slot - 2))          # 2px surface gap between bars
    parts = []
    for i in range(5):                            # recessive gridlines + ticks
        v = step * i
        y = PAD["t"] + plot_h - plot_h * i / 4
        parts.append(f'<line class="grid" x1="{PAD["l"]}" y1="{y:.1f}" x2="{W-PAD["r"]}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{PAD["l"]-7}" y="{y+3.5:.1f}" text-anchor="end">{v:,}</text>')
    for i, k in enumerate(keys):
        v = data[k]
        h = plot_h * v / top
        x = PAD["l"] + i * slot + (slot - bw) / 2
        y = PAD["t"] + plot_h - h
        r = min(4, bw / 2, h)                     # rounded data-end, square at baseline
        d = (f'M{x:.1f} {PAD["t"]+plot_h:.1f} V{y+r:.1f} Q{x:.1f} {y:.1f} {x+r:.1f} {y:.1f} '
             f'H{x+bw-r:.1f} Q{x+bw:.1f} {y:.1f} {x+bw:.1f} {y+r:.1f} V{PAD["t"]+plot_h:.1f} Z') if h > 0.5 else ""
        parts.append(f'<path class="bar" d="{d}" data-k="{k}" data-v="{v}"/>')
        if len(keys) <= 12 or i % 2 == 0:
            parts.append(f'<text class="tick" x="{x+bw/2:.1f}" y="{height-PAD["b"]+16}" text-anchor="middle">{k}</text>')
    parts.append(f'<line class="axis" x1="{PAD["l"]}" y1="{PAD["t"]+plot_h}" x2="{W-PAD["r"]}" y2="{PAD["t"]+plot_h}"/>')
    return f'<svg viewBox="0 0 {W} {height}" role="img">{"".join(parts)}</svg>'


def bars_h(pairs, colors=None, height=None):
    """Horizontal bars: long labels, direct value labels, no legend needed."""
    rowh, gap, lw = 26, 2, 176
    height = height or len(pairs) * rowh + 10
    top, _ = nice_top(max(v for _, v in pairs) or 1)
    plot_w = W - lw - 62
    parts = []
    for i, (label, v) in enumerate(pairs):
        y = 5 + i * rowh
        bh = rowh - gap * 2
        bwid = plot_w * v / top
        r = min(4, bh / 2, bwid)
        cls = colors[i] if colors else "bar"
        d = (f'M{lw} {y:.1f} H{lw+bwid-r:.1f} Q{lw+bwid:.1f} {y:.1f} {lw+bwid:.1f} {y+r:.1f} '
             f'V{y+bh-r:.1f} Q{lw+bwid:.1f} {y+bh:.1f} {lw+bwid-r:.1f} {y+bh:.1f} H{lw} Z') if bwid > 0.5 else ""
        parts.append(f'<path class="{cls}" d="{d}"/>')
        parts.append(f'<text class="rowlab" x="{lw-9}" y="{y+bh/2+4:.1f}" text-anchor="end">{label}</text>')
        parts.append(f'<text class="val" x="{lw+bwid+7:.1f}" y="{y+bh/2+4:.1f}">{v:,}</text>')
    return f'<svg viewBox="0 0 {W} {height}" role="img">{"".join(parts)}</svg>'


def card(title, note, svg, table):
    return (f'<section class="card"><h2>{title}</h2><p class="note">{note}</p>'
            f'<div class="plot">{svg}</div><details><summary>数据表</summary>{table}</details></section>')


def table(head, rows):
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return ("<table><thead><tr>" + "".join(f"<th>{h}</th>" for h in head) +
            f"</tr></thead><tbody>{body}</tbody></table>")


def render(dataset, rows, b, cameras, out):
    kept = sum(b["camera"].values())                     # distinct image files
    usable = sum(b["status"][s] for s in KEPT)           # requests that returned data
    lost = sum(b["status"][s] for s in LOST)
    ages = b["_ages"]
    pct = lambda n, d: f"{n/d*100:.1f}%" if d else "–"
    pick = lambda p: ages[min(len(ages) - 1, int(len(ages) * p))] if ages else 0

    hour_tbl = table(["小时 (SGT)", "帧数"], [(f"{h:02d}:00", f"{b['hour'].get(h,0):,}") for h in range(24)])
    day_tbl = table(["日期", "帧数"], sorted(b["day"].items()))
    cam_pairs = [(f'{c} · {cameras.get(c,{}).get("LocationName",c)}', n)
                 for c, n in sorted(b["camera"].items())]
    cam_tbl = table(["摄像头", "路段", "帧数"],
                    [(c, cameras.get(c, {}).get("RoadSegment", ""), f"{n:,}")
                     for c, n in sorted(b["camera"].items())])
    order = [s for s in KEPT + LOST if b["status"].get(s)]
    st_pairs = [(s, b["status"][s]) for s in order]
    st_colors = ["bar" if s == "downloaded" else "bar2" for s in order]
    st_tbl = table(["状态", "条数", "占比", "是否产生文件"],
                   [(s, f"{b['status'][s]:,}", pct(b["status"][s], len(rows)),
                     "是" if s == "downloaded" else "否") for s in order])
    age_keys = ["0–5", "5–10", "10–15", "15–30", "30–60", "60–120", "120+"]
    age_data = {k: b["age"].get(k, 0) for k in age_keys}
    age_tbl = table(["帧龄 (分钟)", "帧数"], [(k, f"{v:,}") for k, v in age_data.items()])

    legend = ('<div class="legend">'
              '<span><i style="background:var(--series)"></i>写入文件</span>'
              '<span><i style="background:var(--series2)"></i>未写入文件</span></div>')
    page = HTML.format(
        built=datetime.now(SG).strftime("%Y-%m-%d %H:%M SGT"),
        images=f"{kept:,}", obs=f"{len(rows):,}",
        cams=len(b["camera"]), days=len(b["day"]),
        rate=pct(usable, len(rows)),
        med_age=f"{pick(0.5):.1f}",
        hour_card=card("按小时分布（新加坡时间）",
                       "深夜摄像头长时间不刷新，采集前期的 15 分钟新鲜度上限把这段判为过期，"
                       "因此 02–06 时明显偏低。",
                       bars_v({f"{h:02d}": b["hour"].get(h, 0) for h in range(24)}), hour_tbl),
        day_card=card("按日期分布",
                      "9/16 起新鲜度上限放宽到 240 分钟，此后各天接近理论满值 1,152 帧／天"
                      "（6 次/小时 × 24 × 8 台）。",
                      bars_v(dict(sorted(b["day"].items()))), day_tbl),
        cam_card=card("按摄像头分布",
                      "八台摄像头共用同一轮请求，因此分布应当接近均匀；偏差来自各自的缺帧。",
                      bars_h(cam_pairs), cam_tbl),
        st_card=card("按状态分布",
                     f"只有 downloaded 会写入新文件。duplicate 表示画面与上次完全相同（sha256 一致），"
                     f"算作有效响应但不重复存盘；stale / missing / error 共 {lost:,} 条则没有拿到可用画面。",
                     bars_h(st_pairs, st_colors) + legend, st_tbl),
        age_card=card("帧龄分布",
                      "帧龄 = 采集时刻 − 实际拍摄时刻。做时间序列分析请以 captured_at_utc 为准。",
                      bars_v(age_data), age_tbl),
    )
    (out / "distribution.html").write_text(page, encoding="utf-8")

    with (out / "distribution.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["breakdown", "key", "frames"])
        for h in range(24):
            w.writerow(["hour_sgt", f"{h:02d}", b["hour"].get(h, 0)])
        for k, v in sorted(b["day"].items()):
            w.writerow(["day", k, v])
        for k, v in sorted(b["camera"].items()):
            w.writerow(["camera", k, v])
        for k, v in sorted(b["segment"].items()):
            w.writerow(["road_segment", k, v])
        for k, v in b["status"].most_common():
            w.writerow(["status", k, v])
        for k in age_keys:
            w.writerow(["frame_age_min", k, age_data[k]])
    return kept, lost


def text_summary(b, rows, cameras):
    kept = sum(b["camera"].values())
    usable = sum(b["status"][s] for s in KEPT)
    top = max(b["hour"].values()) or 1
    print(f"\n  image files    {kept:,}")
    print(f"  observations   {len(rows):,}  ({usable:,} returned data, "
          f"{usable/len(rows)*100:.1f}%)")
    print(f"\n  by hour (SGT)")
    for h in range(24):
        n = b["hour"].get(h, 0)
        print(f"    {h:02d}  {'█' * int(n / top * 40)} {n}")
    print(f"\n  by day")
    for k, v in sorted(b["day"].items()):
        print(f"    {k}  {'█' * int(v / max(b['day'].values()) * 40)} {v}")
    print(f"\n  by camera")
    for k, v in sorted(b["camera"].items()):
        print(f"    {k} {cameras.get(k,{}).get('LocationName',''):<24} {v}")
    print(f"\n  status " + "  ".join(f"{k}:{v}" for k, v in b["status"].most_common()))


HTML = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>数据分布 · Sentosa Traffic</title>
<style>
:root{{
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,.10);
  --series:#2a78d6; --series2:#eb6834;
}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
  --series:#3987e5; --series2:#d95926;
}}}}
:root[data-theme=dark]{{
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
  --series:#3987e5; --series2:#d95926;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--plane);color:var(--ink);
 font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
.wrap{{max-width:860px;margin:0 auto;padding:28px 18px 60px}}
h1{{font-size:20px;margin:0 0 3px;letter-spacing:-.01em}}
.sub{{color:var(--ink2);font-size:12.5px;margin:0 0 20px}}
.tiles{{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(122px,1fr));margin-bottom:22px}}
.tile{{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:11px 13px}}
.tile b{{display:block;font-size:21px;letter-spacing:-.02em;margin-bottom:1px}}
.tile span{{color:var(--muted);font-size:11.5px}}
.card{{background:var(--surface);border:1px solid var(--ring);border-radius:12px;
 padding:15px 16px 12px;margin-bottom:15px}}
h2{{font-size:14px;margin:0 0 2px}}
.note{{color:var(--ink2);font-size:12px;margin:0 0 11px}}
.plot{{overflow-x:auto}}
svg{{display:block;width:100%;min-width:430px;overflow:visible}}
.grid{{stroke:var(--grid);stroke-width:1}}
.axis{{stroke:var(--axis);stroke-width:1}}
.tick{{fill:var(--muted);font-size:10.5px;font-variant-numeric:tabular-nums}}
.rowlab{{fill:var(--ink2);font-size:11.5px}}
.val{{fill:var(--ink);font-size:11.5px;font-variant-numeric:tabular-nums}}
.bar{{fill:var(--series)}} .bar2{{fill:var(--series2)}}
.bar:hover,.bar2:hover{{opacity:.78}}
.legend{{display:flex;gap:14px;font-size:11.5px;color:var(--ink2);margin:9px 0 0}}
.legend i{{width:10px;height:10px;border-radius:2px;display:inline-block;margin-right:5px}}
details{{margin-top:9px}}
summary{{cursor:pointer;color:var(--muted);font-size:11.5px}}
table{{border-collapse:collapse;width:100%;margin-top:8px;font-size:12px}}
th,td{{text-align:left;padding:4px 8px;border-bottom:1px solid var(--grid);
 font-variant-numeric:tabular-nums}}
th{{color:var(--muted);font-weight:600}}
#tip{{position:fixed;background:var(--ink);color:var(--plane);padding:4px 8px;
 border-radius:6px;font-size:11.5px;pointer-events:none;opacity:0;transition:opacity .1s}}
</style></head><body><div class="wrap">
<h1>数据分布</h1>
<p class="sub">Sentosa / 新柔通道交通摄像头数据集 · 生成于 {built}</p>
<div class="tiles">
  <div class="tile"><b>{images}</b><span>图片文件</span></div>
  <div class="tile"><b>{obs}</b><span>观测记录</span></div>
  <div class="tile"><b>{rate}</b><span>请求有效率</span></div>
  <div class="tile"><b>{cams}</b><span>摄像头</span></div>
  <div class="tile"><b>{days}</b><span>天</span></div>
  <div class="tile"><b>{med_age}<small> 分</small></b><span>帧龄中位数</span></div>
</div>
{hour_card}{day_card}{cam_card}{st_card}{age_card}
</div><div id="tip"></div>
<script>
const tip=document.getElementById('tip');
document.querySelectorAll('path[data-k]').forEach(p=>{{
  p.addEventListener('mousemove',e=>{{
    tip.textContent=p.dataset.k+' · '+(+p.dataset.v).toLocaleString()+' 帧';
    tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY-28)+'px';tip.style.opacity=1;
  }});
  p.addEventListener('mouseleave',()=>tip.style.opacity=0);
}});
</script></body></html>"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/dataset")
    parser.add_argument("--quiet", action="store_true", help="Skip the text summary")
    args = parser.parse_args(argv)
    cameras = {c["CameraID"]: c for c in load_cameras(ROOT / "reference/camera_info.csv")}
    rows = load(args.dataset)
    b = breakdowns(rows, cameras)
    if not args.quiet:
        text_summary(b, rows, cameras)
    kept, lost = render(args.dataset, rows, b, cameras, args.dataset)
    print(f"\n  distribution.html and distribution.csv written to {args.dataset}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
