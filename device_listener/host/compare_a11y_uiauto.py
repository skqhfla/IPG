"""
Side-by-side comparison of what our APK's a11y walker captured vs what
`uiautomator dump` produces for the SAME screen.

Output: a self-contained HTML file with the screenshot as background and
two SVG overlay layers (a11y in blue, uiautomator in red, overlap in
purple). Toggle layers + hover for element details.

How the a11y XML is sourced:
  - The latest XML in the most-recently-modified outputs_APK/<app>/<session>/xml/
  - i.e. whichever screen our APK most recently dumped via the AccessibilityService

How uiautomator XML is sourced:
  - Fresh `adb shell uiautomator dump` at script time

Workflow:
  1. Start the collector (or have the APK service running)
  2. Navigate the phone to the screen you want to compare
  3. Lightly interact (or wait for a CONTENT_CHANGED) so a fresh a11y dump
     is written by our APK; OR pass --wait to make this script trigger a
     KEYCODE_DPAD_CENTER as a low-impact stimulus
  4. Run this script — it picks the most recent XML in outputs_APK and
     pairs it with a fresh uiautomator dump + screencap

Usage:
    python device_listener/host/compare_a11y_uiauto.py [--out DIR] [--open]
"""
from __future__ import annotations

import argparse
import base64
import datetime
import re
import subprocess
import sys
import time
import webbrowser
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


DUMP_BROADCAST_ACTION = "dev.ipg.listener.DUMP_NOW"


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_OUT = SCRIPT_DIR.parent / "compare"
DEFAULT_IPG_OUT = REPO_ROOT / "outputs_APK"

BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Visual a11y vs uiautomator XML comparison.")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help="Output dir for HTML + raw XMLs (default: device_listener/compare).")
    p.add_argument("--ipg-out", type=Path, default=DEFAULT_IPG_OUT,
                   help="Where to look for the latest a11y XML (default: outputs_APK).")
    p.add_argument("--open", action="store_true",
                   help="Open the resulting HTML in the default browser.")
    p.add_argument("--no-broadcast", action="store_true",
                   help="Skip the DUMP_NOW broadcast — just use whatever a11y XML is already there.")
    return p.parse_args()


def die(msg: str, code: int = 1) -> None:
    print(f"[!] {msg}", file=sys.stderr)
    sys.exit(code)


def find_latest_a11y_xml(ipg_out: Path) -> tuple[Path, Path]:
    """Find (xml_path, session_dir) for the latest a11y dump under ipg_out."""
    if not ipg_out.is_dir():
        die(f"{ipg_out} does not exist — run a capture session first.")
    candidates: list[tuple[float, Path, Path]] = []
    for app_dir in ipg_out.iterdir():
        if not app_dir.is_dir():
            continue
        for sess_dir in app_dir.iterdir():
            xml_dir = sess_dir / "xml"
            if not xml_dir.is_dir():
                continue
            for xml in xml_dir.glob("*.xml"):
                candidates.append((xml.stat().st_mtime, xml, sess_dir))
    if not candidates:
        die(f"no a11y XMLs found under {ipg_out}")
    candidates.sort(reverse=True)
    _, xml_path, sess_dir = candidates[0]
    return xml_path, sess_dir


def trigger_fresh_a11y_dump(ipg_out: Path) -> None:
    """Broadcast DUMP_NOW to the APK, then poll for a newer XML appearing under
    ipg_out. The collector pulls it and deletes the device-side copy, so we
    just watch the local mirror."""
    pre = find_latest_a11y_xml(ipg_out)[0]
    pre_mtime = pre.stat().st_mtime
    print(f"[*] broadcasting {DUMP_BROADCAST_ACTION} ...", flush=True)
    r = adb_run(["adb", "shell", "am", "broadcast", "-a", DUMP_BROADCAST_ACTION])
    if r.returncode != 0:
        print(f"[!] broadcast failed (continuing with stale a11y): {r.stderr.strip()}", file=sys.stderr)
        return
    deadline = time.time() + 5.0
    while time.time() < deadline:
        latest = find_latest_a11y_xml(ipg_out)[0]
        if latest.stat().st_mtime > pre_mtime:
            print(f"[*] fresh a11y dump arrived: {latest.name}", flush=True)
            return
        time.sleep(0.2)
    print("[!] no new a11y dump within 5s — using latest available "
          "(is the collector running and APK active?)", file=sys.stderr)


def adb_run(args: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=capture, text=True, encoding="utf-8", errors="ignore")


def grab_uiautomator_xml(out_dir: Path, stem: str) -> Path:
    """Run uiautomator dump with retries — `could not get idle state` is common
    on devices with constantly-animating system UI (status bar, AOD service,
    etc). The default output path /sdcard/window_dump.xml is more reliable
    across vendor variations than explicit paths."""
    remote = "/sdcard/window_dump.xml"
    adb_run(["adb", "shell", "rm", "-f", remote])

    last_err = ""
    for attempt in range(1, 4):
        # Attempt 1+2: full tree (fair comparison vs our walker which keeps
        # everything). Attempt 3: --compressed as last-ditch when idle keeps
        # timing out — produces fewer elements but at least succeeds.
        compressed = attempt == 3
        print(f"[*] uiautomator dump (attempt {attempt}/3{', --compressed' if compressed else ''}) ...", flush=True)
        cmd = ["adb", "shell", "uiautomator", "dump"]
        if compressed:
            cmd.append("--compressed")
        r = adb_run(cmd)
        combined = (r.stderr or "") + (r.stdout or "")
        # uiautomator returns 0 even on idle errors — check stderr content
        if "ERROR" in combined or "Exception" in combined:
            last_err = combined.strip()
            continue
        # Confirm the file actually exists on device
        ls = adb_run(["adb", "shell", "ls", remote])
        if ls.returncode == 0 and remote in ls.stdout:
            break
        last_err = "dump file not created"
    else:
        die(f"uiautomator dump failed after retries — {last_err}\n"
            f"  Tip: lock + unlock the phone, or close any animating overlay.")

    local = out_dir / f"{stem}_uiauto.xml"
    r = adb_run(["adb", "pull", remote, str(local)])
    if r.returncode != 0:
        die(f"adb pull uiauto failed: {r.stderr.strip()}")
    adb_run(["adb", "shell", "rm", "-f", remote])
    return local


def grab_screencap(out_dir: Path, stem: str) -> Path:
    remote = "/sdcard/_cmp_screen.png"
    print("[*] adb shell screencap ...", flush=True)
    r = adb_run(["adb", "shell", "screencap", "-p", remote])
    if r.returncode != 0:
        die(f"screencap failed: {r.stderr.strip()}")
    local = out_dir / f"{stem}_screen.png"
    r = adb_run(["adb", "pull", remote, str(local)])
    if r.returncode != 0:
        die(f"adb pull screen failed: {r.stderr.strip()}")
    adb_run(["adb", "shell", "rm", "-f", remote])
    return local


def png_dims(path: Path) -> tuple[int, int]:
    with open(path, "rb") as f:
        data = f.read(24)
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))


def parse_bounds(s: Optional[str]) -> Optional[tuple[int, int, int, int]]:
    if not s:
        return None
    m = BOUNDS_RE.match(s)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))


def parse_elements(xml_text: str, source: str) -> list[dict]:
    """Walk an XML hierarchy (a11y or uiauto format) and emit elements with bounds."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        die(f"{source} XML parse error: {e}")
    out: list[dict] = []

    def walk(node: ET.Element, depth: int) -> None:
        bounds = parse_bounds(node.get("bounds"))
        if bounds is not None:
            out.append({
                "source": source,
                "bounds": bounds,
                "class": node.get("class") or "",
                "resource_id": node.get("resource-id") or "",
                "text": node.get("text") or "",
                "content_desc": node.get("content-desc") or "",
                "clickable": node.get("clickable") == "true",
                "scrollable": node.get("scrollable") == "true",
                "depth": depth,
            })
        for child in node:
            walk(child, depth + 1)

    walk(root, 0)
    return out


def match_elements(
    a11y: list[dict], uiauto: list[dict]
) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """Match by exact bounds tuple. (Both come from getBoundsInScreen())"""
    uiauto_by_bounds: dict[tuple[int, int, int, int], list[dict]] = {}
    for el in uiauto:
        uiauto_by_bounds.setdefault(el["bounds"], []).append(el)
    matched: list[tuple[dict, dict]] = []
    only_a11y: list[dict] = []
    consumed_uiauto_ids: set[int] = set()
    for el in a11y:
        cands = uiauto_by_bounds.get(el["bounds"], [])
        pick = next((c for c in cands if id(c) not in consumed_uiauto_ids), None)
        if pick is not None:
            matched.append((el, pick))
            consumed_uiauto_ids.add(id(pick))
        else:
            only_a11y.append(el)
    only_uiauto = [c for c in uiauto if id(c) not in consumed_uiauto_ids]
    return matched, only_a11y, only_uiauto


def el_to_js_dict(el: dict, source_label: str) -> dict:
    return {
        "source": source_label,
        "bounds": list(el["bounds"]),
        "class": el["class"],
        "resource_id": el["resource_id"],
        "text": el["text"],
        "content_desc": el["content_desc"],
        "clickable": el["clickable"],
        "scrollable": el["scrollable"],
        "depth": el["depth"],
    }


def render_html(
    png_b64: str,
    img_w: int,
    img_h: int,
    matched: list[tuple[dict, dict]],
    only_a11y: list[dict],
    only_uiauto: list[dict],
    a11y_xml_src: Path,
    sess_label: str,
    timestamp: str,
) -> str:
    import json as _json

    rects: list[dict] = []
    for a, _u in matched:
        rects.append({**el_to_js_dict(a, "both"), "matched_uiauto_class": _u["class"]})
    for el in only_a11y:
        rects.append(el_to_js_dict(el, "a11y"))
    for el in only_uiauto:
        rects.append(el_to_js_dict(el, "uiauto"))

    rects_json = _json.dumps(rects, ensure_ascii=False)
    a11y_total = len(matched) + len(only_a11y)
    uiauto_total = len(matched) + len(only_uiauto)

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>a11y vs uiautomator — {timestamp}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, "Segoe UI", system-ui, sans-serif; background: #1a1a1a; color: #e0e0e0; }}
header {{ position: sticky; top: 0; background: #252525; padding: 12px 16px; border-bottom: 1px solid #444; z-index: 10; display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }}
header h1 {{ font-size: 14px; font-weight: 600; }}
header .meta {{ font-size: 11px; color: #999; font-family: monospace; }}
.stats {{ display: flex; gap: 12px; font-size: 12px; }}
.stats span {{ padding: 2px 8px; border-radius: 4px; }}
.stat-a {{ background: rgba(60, 130, 255, 0.2); color: #6aa9ff; }}
.stat-u {{ background: rgba(255, 80, 80, 0.2); color: #ff7070; }}
.stat-b {{ background: rgba(180, 100, 255, 0.2); color: #b070ff; }}
.modes {{ display: flex; gap: 4px; margin-left: auto; }}
.modes button {{ padding: 4px 10px; background: #333; color: #ccc; border: 1px solid #555; cursor: pointer; font-size: 11px; border-radius: 4px; }}
.modes button.active {{ background: #4a6da3; color: #fff; border-color: #4a6da3; }}
.layout {{ display: flex; height: calc(100vh - 50px); }}
.viewer {{ flex: 1; overflow: auto; display: flex; align-items: flex-start; justify-content: center; padding: 16px; background: #0a0a0a; }}
.canvas-wrap {{ position: relative; }}
.canvas-wrap img {{ display: block; max-width: none; }}
svg {{ position: absolute; top: 0; left: 0; pointer-events: none; }}
svg rect {{ pointer-events: all; cursor: pointer; fill-opacity: 0; stroke-width: 1.5; transition: fill-opacity 0.1s; }}
svg rect:hover {{ fill-opacity: 0.25; stroke-width: 2.5; }}
rect.both    {{ stroke: #b070ff; }}
rect.a11y    {{ stroke: #6aa9ff; }}
rect.uiauto  {{ stroke: #ff7070; }}
rect.selected {{ fill-opacity: 0.35; stroke-width: 3; }}
.hidden {{ display: none; }}
.panel {{ width: 360px; background: #1f1f1f; border-left: 1px solid #444; padding: 16px; overflow-y: auto; font-size: 12px; }}
.panel h2 {{ font-size: 13px; margin-bottom: 8px; color: #eee; }}
.panel .placeholder {{ color: #666; font-style: italic; }}
.field {{ margin-bottom: 8px; }}
.field .k {{ color: #999; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; }}
.field .v {{ font-family: monospace; word-break: break-all; color: #ddd; }}
.badge {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; }}
.badge.both    {{ background: rgba(180, 100, 255, 0.2); color: #b070ff; }}
.badge.a11y    {{ background: rgba(60, 130, 255, 0.2); color: #6aa9ff; }}
.badge.uiauto  {{ background: rgba(255, 80, 80, 0.2); color: #ff7070; }}
</style>
</head>
<body>
<header>
  <h1>a11y vs uiautomator</h1>
  <div class="meta">{sess_label} · {timestamp}<br>{a11y_xml_src.name}</div>
  <div class="stats">
    <span class="stat-b">both: {len(matched)}</span>
    <span class="stat-a">a11y only: {len(only_a11y)} (total {a11y_total})</span>
    <span class="stat-u">uiauto only: {len(only_uiauto)} (total {uiauto_total})</span>
  </div>
  <div class="modes">
    <button data-mode="all" class="active">All</button>
    <button data-mode="a11y">A11y</button>
    <button data-mode="uiauto">UiAuto</button>
    <button data-mode="diff">Diff only</button>
  </div>
</header>
<div class="layout">
  <div class="viewer">
    <div class="canvas-wrap" id="wrap">
      <img id="screen" src="data:image/png;base64,{png_b64}" alt="screen">
      <svg id="overlay" viewBox="0 0 {img_w} {img_h}" preserveAspectRatio="none"></svg>
    </div>
  </div>
  <aside class="panel" id="panel">
    <h2>Hover or click an element</h2>
    <p class="placeholder">파란 = a11y · 빨강 = uiautomator · 보라 = 둘 다 (좌표 일치)</p>
  </aside>
</div>
<script>
const RECTS = {rects_json};
const IMG_W = {img_w};
const IMG_H = {img_h};
const overlay = document.getElementById('overlay');
const panel = document.getElementById('panel');
const img = document.getElementById('screen');
const wrap = document.getElementById('wrap');

// Render rects
const SVG_NS = 'http://www.w3.org/2000/svg';
let rectEls = [];
RECTS.forEach((r, idx) => {{
  const [x1, y1, x2, y2] = r.bounds;
  const w = x2 - x1, h = y2 - y1;
  if (w <= 0 || h <= 0) return;
  const el = document.createElementNS(SVG_NS, 'rect');
  el.setAttribute('x', x1);
  el.setAttribute('y', y1);
  el.setAttribute('width', w);
  el.setAttribute('height', h);
  el.classList.add(r.source);
  el.dataset.idx = idx;
  el.addEventListener('mouseenter', () => showInfo(r));
  el.addEventListener('click', () => {{
    rectEls.forEach(e => e.classList.remove('selected'));
    el.classList.add('selected');
    showInfo(r, true);
  }});
  overlay.appendChild(el);
  rectEls.push(el);
}});

function showInfo(r, pinned) {{
  const badge = `<span class="badge ${{r.source}}">${{r.source.toUpperCase()}}</span>`;
  panel.innerHTML = `
    <h2>${{badge}} ${{(r.class || '').split('.').pop() || '(no class)'}}</h2>
    <div class="field"><div class="k">bounds</div><div class="v">[${{r.bounds.join(', ')}}]</div></div>
    <div class="field"><div class="k">class</div><div class="v">${{r.class || '—'}}</div></div>
    <div class="field"><div class="k">resource-id</div><div class="v">${{r.resource_id || '—'}}</div></div>
    <div class="field"><div class="k">text</div><div class="v">${{escape_html(r.text) || '—'}}</div></div>
    <div class="field"><div class="k">content-desc</div><div class="v">${{escape_html(r.content_desc) || '—'}}</div></div>
    <div class="field"><div class="k">depth</div><div class="v">${{r.depth}}</div></div>
    <div class="field"><div class="k">flags</div><div class="v">${{[r.clickable && 'clickable', r.scrollable && 'scrollable'].filter(Boolean).join(', ') || '—'}}</div></div>
    ${{r.matched_uiauto_class ? `<div class="field"><div class="k">matched uiauto class</div><div class="v">${{r.matched_uiauto_class}}</div></div>` : ''}}
  `;
}}

function escape_html(s) {{
  if (!s) return '';
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}}

// Mode switcher
document.querySelectorAll('.modes button').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.modes button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const mode = btn.dataset.mode;
    rectEls.forEach((el, i) => {{
      const src = RECTS[parseInt(el.dataset.idx)].source;
      let show;
      if (mode === 'all') show = true;
      else if (mode === 'a11y') show = (src === 'a11y' || src === 'both');
      else if (mode === 'uiauto') show = (src === 'uiauto' || src === 'both');
      else if (mode === 'diff') show = (src !== 'both');
      el.classList.toggle('hidden', !show);
    }});
  }});
}});

// Resize SVG to image
function syncSvg() {{
  overlay.style.width = img.clientWidth + 'px';
  overlay.style.height = img.clientHeight + 'px';
}}
img.onload = syncSvg;
window.addEventListener('resize', syncSvg);
syncSvg();
</script>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    if not args.no_broadcast:
        trigger_fresh_a11y_dump(args.ipg_out)

    a11y_xml_path, sess_dir = find_latest_a11y_xml(args.ipg_out)
    print(f"[*] latest a11y xml: {a11y_xml_path}", flush=True)
    print(f"[*] session: {sess_dir.name}", flush=True)

    a11y_xml_text = a11y_xml_path.read_text(encoding="utf-8")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{timestamp}_{sess_dir.name}_{a11y_xml_path.stem}"

    uiauto_xml_path = grab_uiautomator_xml(args.out, stem)
    uiauto_xml_text = uiauto_xml_path.read_text(encoding="utf-8")

    png_path = grab_screencap(args.out, stem)
    img_w, img_h = png_dims(png_path)
    if img_w == 0:
        die("failed to read PNG dimensions")

    a11y_elements = parse_elements(a11y_xml_text, "a11y")
    uiauto_elements = parse_elements(uiauto_xml_text, "uiauto")
    matched, only_a11y, only_uiauto = match_elements(a11y_elements, uiauto_elements)

    png_b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
    html = render_html(
        png_b64=png_b64,
        img_w=img_w,
        img_h=img_h,
        matched=matched,
        only_a11y=only_a11y,
        only_uiauto=only_uiauto,
        a11y_xml_src=a11y_xml_path,
        sess_label=sess_dir.name,
        timestamp=timestamp,
    )
    html_path = args.out / f"{stem}_compare.html"
    html_path.write_text(html, encoding="utf-8")

    print(
        f"\n[+] {html_path}\n"
        f"  a11y elements:    {len(a11y_elements)}\n"
        f"  uiauto elements:  {len(uiauto_elements)}\n"
        f"  matched (bounds): {len(matched)}\n"
        f"  only a11y:        {len(only_a11y)}\n"
        f"  only uiauto:      {len(only_uiauto)}",
        flush=True,
    )

    if args.open:
        webbrowser.open(html_path.as_uri())

    return 0


if __name__ == "__main__":
    sys.exit(main())
