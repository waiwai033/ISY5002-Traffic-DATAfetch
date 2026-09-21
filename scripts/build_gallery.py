#!/usr/bin/env python3
"""Build a browsable HTML album over the collected camera images.

The album is a local file because the images are hundreds of megabytes and stay
on disk; it references them by relative path rather than embedding them.
"""
import argparse
import csv
import html
import json
import re
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fetch_lta_camera_images import ROOT, SG, load_cameras

# 20260915T163558Z_4712_1635_baf133ec9d2d.jpg
NAME = re.compile(r"(\d{8}T\d{6})Z_(\d+)_\d{4}_([0-9a-f]+)\.jpg$")


def scan(source):
    """One entry per distinct frame; the same frame recurs across artifacts."""
    frames = {}
    for path in source.rglob("*.jpg"):
        match = NAME.match(path.name)
        if not match:
            continue
        stamp, camera, digest = match.groups()
        captured = datetime.strptime(stamp, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        frames.setdefault(path.name, {
            "file": path, "camera": camera, "captured": captured, "sha": digest})
    return frames


def statuses(source):
    """Manifest rows carry the collection status a filename cannot express."""
    rows = defaultdict(list)
    for manifest in source.rglob("manifest.csv"):
        with manifest.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                if row.get("image_path"):
                    rows[Path(row["image_path"]).name].append(row)
    return rows


def thumbnail(job):
    source, target = job
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["sips", "-Z", "360", str(source), "--out", str(target)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def build(source, out, workers):
    cameras = {c["CameraID"]: c for c in load_cameras(ROOT / "reference/camera_info.csv")}
    frames = scan(source)
    if not frames:
        raise SystemExit(f"No collected images found under {source}")
    rows = statuses(source)
    out.mkdir(parents=True, exist_ok=True)
    thumbs = out / "thumbs"

    jobs, records = [], []
    for name, frame in sorted(frames.items(), key=lambda kv: (kv[1]["camera"], kv[1]["captured"])):
        camera = cameras.get(frame["camera"], {})
        thumb = thumbs / frame["camera"] / name
        jobs.append((frame["file"], thumb))
        row = rows.get(name, [{}])[0]
        collected = row.get("collected_at_utc") or ""
        age = ""
        if collected:
            delta = datetime.fromisoformat(collected) - frame["captured"]
            age = round(delta.total_seconds() / 60, 1)
        records.append({
            "n": name,
            "f": str(Path(frame["file"]).resolve().relative_to(ROOT.resolve())),
            "t": str(thumb.resolve().relative_to(out.resolve())),
            "c": frame["camera"],
            "u": frame["captured"].isoformat(),
            "s": frame["captured"].astimezone(SG).strftime("%Y-%m-%d %H:%M"),
            "d": frame["captured"].astimezone(SG).strftime("%Y-%m-%d"),
            "h": frame["captured"].astimezone(SG).hour,
            "a": age,
        })

    print(f"{len(records)} frames; generating thumbnails with {workers} workers...")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(thumbnail, jobs))

    roster = {cid: {"name": c.get("LocationName", cid), "road": c.get("RoadSegment", ""),
                    "dir": c.get("Direction", "")} for cid, c in cameras.items()}
    # The album is opened from out/, so originals need a prefix back to the repo root.
    prefix = Path(*[".."] * len(out.resolve().relative_to(ROOT.resolve()).parts))
    page = TEMPLATE.replace("__DATA__", json.dumps(records, separators=(",", ":")))
    page = page.replace("__CAMERAS__", json.dumps(roster, ensure_ascii=False))
    page = page.replace("__PREFIX__", json.dumps(str(prefix)))
    page = page.replace("__BUILT__", html.escape(datetime.now(SG).strftime("%Y-%m-%d %H:%M SGT")))
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"Album written to {out / 'index.html'}")
    return records


TEMPLATE = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sentosa Traffic Album</title>
<style>
:root{
  --bg:#f6f6f4; --panel:#fff; --ink:#1a1a18; --muted:#6b6b66; --line:#e2e2dd;
  --accent:#2f6f4f; --accent-ink:#fff; --shadow:0 1px 3px rgba(0,0,0,.08);
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#14150f; --panel:#1d1e18; --ink:#eceade; --muted:#9a998c; --line:#2e2f27;
  --accent:#7fb89a; --accent-ink:#11150f; --shadow:0 1px 3px rgba(0,0,0,.4);
}}
:root[data-theme=dark]{
  --bg:#14150f; --panel:#1d1e18; --ink:#eceade; --muted:#9a998c; --line:#2e2f27;
  --accent:#7fb89a; --accent-ink:#11150f; --shadow:0 1px 3px rgba(0,0,0,.4);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Helvetica Neue",sans-serif}
header{position:sticky;top:0;z-index:20;background:var(--panel);
  border-bottom:1px solid var(--line);padding:12px 16px;box-shadow:var(--shadow)}
h1{margin:0 0 2px;font-size:16px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:12px}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}
select,button{font:inherit;color:var(--ink);background:var(--bg);
  border:1px solid var(--line);border-radius:7px;padding:5px 9px;cursor:pointer}
button.on{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.count{color:var(--muted);font-size:12px;margin-left:auto}
main{padding:16px}
.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}
figure{margin:0;background:var(--panel);border:1px solid var(--line);
  border-radius:9px;overflow:hidden;cursor:zoom-in}
figure img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;background:var(--line)}
figcaption{padding:6px 8px;font-size:11px;color:var(--muted);
  display:flex;justify-content:space-between;gap:6px}
figcaption b{color:var(--ink);font-weight:600}
.stale{color:#c2723a}
.day{margin:22px 0 8px;font-size:13px;font-weight:600;
  padding-bottom:5px;border-bottom:1px solid var(--line)}
/* player */
#player{display:none}
#player.show{display:block}
.stage{background:#000;border-radius:10px;overflow:hidden;position:relative}
.stage img{display:block;width:100%;aspect-ratio:16/9;object-fit:contain}
.stamp{position:absolute;left:10px;bottom:10px;background:rgba(0,0,0,.72);
  color:#fff;padding:4px 9px;border-radius:6px;font-size:12px;font-variant-numeric:tabular-nums}
.bar{display:flex;gap:10px;align-items:center;margin-top:10px}
input[type=range]{flex:1;accent-color:var(--accent)}
.hint{color:var(--muted);font-size:11px;margin-top:6px}
/* lightbox */
#box{position:fixed;inset:0;background:rgba(0,0,0,.9);display:none;
  align-items:center;justify-content:center;z-index:50;cursor:zoom-out}
#box.show{display:flex}
#box img{max-width:96vw;max-height:88vh}
#box .meta{position:absolute;bottom:14px;left:0;right:0;text-align:center;
  color:#eee;font-size:12px}
.empty{color:var(--muted);padding:40px 0;text-align:center}
</style>
</head>
<body>
<header>
  <h1>Sentosa Traffic Album</h1>
  <div class="sub">八台摄像头 · 生成于 __BUILT__</div>
  <div class="controls">
    <select id="cam"></select>
    <select id="date"></select>
    <select id="band">
      <option value="">全天</option>
      <option value="night">夜间 00–06</option>
      <option value="am">早高峰 07–09</option>
      <option value="day">白天 10–16</option>
      <option value="pm">晚高峰 17–19</option>
      <option value="eve">夜晚 20–23</option>
    </select>
    <button id="mGrid" class="on">网格</button>
    <button id="mPlay">时间轴</button>
    <span class="count" id="count"></span>
  </div>
</header>
<main>
  <div id="grid" class="grid"></div>
  <div id="player">
    <div class="stage"><img id="frame" alt=""><div class="stamp" id="stamp"></div></div>
    <div class="bar">
      <button id="play">▶ 播放</button>
      <input type="range" id="seek" min="0" value="0">
      <select id="speed">
        <option value="500">2×/秒</option>
        <option value="250" selected>4×/秒</option>
        <option value="120">8×/秒</option>
      </select>
    </div>
    <div class="hint">← → 单帧步进 · 空格播放/暂停</div>
  </div>
  <div class="empty" id="empty" hidden>这个筛选条件下没有图像</div>
</main>
<div id="box"><img id="boxImg" alt=""><div class="meta" id="boxMeta"></div></div>
<script>
const DATA=__DATA__, CAMS=__CAMERAS__, PREFIX=__PREFIX__;
const $=id=>document.getElementById(id);
const full=r=>PREFIX+"/"+r.f;
const BANDS={night:[0,6],am:[7,9],day:[10,16],pm:[17,19],eve:[20,23]};

const camIds=[...new Set(DATA.map(r=>r.c))].sort();
$("cam").innerHTML=camIds.map(c=>{
  const m=CAMS[c]||{};
  return `<option value="${c}">${c} · ${m.name||""}</option>`}).join("");
const dates=[...new Set(DATA.map(r=>r.d))].sort();
$("date").innerHTML=`<option value="">全部日期</option>`+
  dates.map(d=>`<option value="${d}">${d}</option>`).join("");

let view="grid", rows=[], idx=0, timer=null;

function filter(){
  const c=$("cam").value, d=$("date").value, b=$("band").value;
  rows=DATA.filter(r=>r.c===c && (!d||r.d===d) &&
    (!b||(r.h>=BANDS[b][0]&&r.h<=BANDS[b][1])));
  $("count").textContent=`${rows.length} 帧`;
  $("empty").hidden=rows.length>0;
  idx=Math.min(idx,Math.max(0,rows.length-1));
  view==="grid"?drawGrid():drawPlayer();
}

function drawGrid(){
  const byDay={};
  rows.forEach(r=>(byDay[r.d]=byDay[r.d]||[]).push(r));
  $("grid").innerHTML=Object.entries(byDay).map(([day,list])=>
    `<div class="day" style="grid-column:1/-1">${day} · ${list.length} 帧</div>`+
    list.map(r=>{
      const old=r.a!==""&&r.a>20;
      return `<figure data-n="${r.n}">
        <img loading="lazy" src="${r.t}" alt="${r.s}">
        <figcaption><b>${r.s.slice(11)}</b>
        <span class="${old?"stale":""}">${r.a===""?"":r.a+"m"}</span></figcaption>
      </figure>`}).join("")).join("");
}

function drawPlayer(){
  if(!rows.length){$("frame").removeAttribute("src");$("stamp").textContent="";return}
  $("seek").max=rows.length-1; $("seek").value=idx;
  const r=rows[idx];
  $("frame").src=full(r);
  $("stamp").textContent=`${r.s} SGT · ${idx+1}/${rows.length}`+(r.a===""?"":` · 帧龄 ${r.a}m`);
  for(const j of [idx+1,idx+2]) if(rows[j]) new Image().src=full(rows[j]);
}

function setView(v){
  view=v;
  $("mGrid").classList.toggle("on",v==="grid");
  $("mPlay").classList.toggle("on",v==="play");
  $("grid").style.display=v==="grid"?"grid":"none";
  $("player").classList.toggle("show",v==="play");
  stop(); v==="grid"?drawGrid():drawPlayer();
}
function stop(){clearInterval(timer);timer=null;$("play").textContent="▶ 播放"}
function toggle(){
  if(timer)return stop();
  $("play").textContent="⏸ 暂停";
  timer=setInterval(()=>{
    if(idx>=rows.length-1)return stop();
    idx++;drawPlayer();
  },+$("speed").value);
}

["cam","date","band"].forEach(id=>$(id).onchange=()=>{idx=0;filter()});
$("mGrid").onclick=()=>setView("grid");
$("mPlay").onclick=()=>setView("play");
$("play").onclick=toggle;
$("seek").oninput=e=>{idx=+e.target.value;stop();drawPlayer()};
$("speed").onchange=()=>{if(timer){stop();toggle()}};

$("grid").onclick=e=>{
  const fig=e.target.closest("figure"); if(!fig)return;
  const r=rows.find(x=>x.n===fig.dataset.n); if(!r)return;
  $("boxImg").src=full(r);
  $("boxMeta").textContent=`${r.c} · ${CAMS[r.c]?.name||""} · ${r.s} SGT`+
    (r.a===""?"":` · 帧龄 ${r.a} 分钟`);
  $("box").classList.add("show");
};
$("box").onclick=()=>$("box").classList.remove("show");
addEventListener("keydown",e=>{
  if(e.key==="Escape")$("box").classList.remove("show");
  if(view!=="play")return;
  if(e.key==="ArrowRight"&&idx<rows.length-1){stop();idx++;drawPlayer()}
  if(e.key==="ArrowLeft"&&idx>0){stop();idx--;drawPlayer()}
  if(e.key===" "){e.preventDefault();toggle()}
});
filter();
</script>
</body>
</html>
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/dataset",
                        help="Merged dataset from fetch_dataset.py (or a raw artifact dir)")
    parser.add_argument("--out", type=Path, default=ROOT / "data/gallery")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    build(args.source, args.out, args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
