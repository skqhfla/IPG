"""
Build Monitor-compatible UTG + app_memory JSON from a captured session.

Output (alongside the captured session):
  <session>/screen/utg.json   ← Monitor opens this; PNGs found in same dir
  <session>/json/app_memory.json  ← Sidebar auto-loads this for element data

UTG schema follows Monitor/README.md. app_memory.json mirrors IPG's structure
so Monitor's TransitionGraph can render bbox overlays, trigger-mode filtering,
and node-pair diffs (added/removed/modified/unchanged).

Screen identity: SHA-1[:16] of normalized XML (volatile attrs stripped).
Element id: stable per-screen, depth-first traversal index.

Usage:
    python device_listener/host/build_utg.py <session_dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


VOLATILE_ATTRS = ("focused", "selected", "checked")
EDGE_LOOKBACK = 5
BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def normalize_xml(xml: str) -> str:
    out = xml
    for attr in VOLATILE_ATTRS:
        out = re.sub(rf' {attr}="[^"]*"', "", out)
    return out


def screen_id_of(xml: str) -> str:
    return hashlib.sha1(normalize_xml(xml).encode("utf-8")).hexdigest()[:16]


def parse_bounds(s: Optional[str]) -> Optional[list[int]]:
    if not s:
        return None
    m = BOUNDS_RE.match(s)
    if not m:
        return None
    return [int(m.group(i)) for i in range(1, 5)]


def short_class(cls: str) -> str:
    return cls.rsplit(".", 1)[-1] if "." in cls else cls


def extract_elements(xml_text: str) -> list[dict]:
    """Walk the XML tree depth-first, emit one element per node with bounds."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    elements: list[dict] = []
    counter = 0

    def walk(node: ET.Element) -> None:
        nonlocal counter
        bounds = parse_bounds(node.get("bounds"))
        if bounds is not None:
            cls = short_class(node.get("class") or "")
            rid = node.get("resource-id") or None
            text = node.get("text") or None
            desc = node.get("content-desc") or None
            is_actionable = (
                node.get("clickable") == "true"
                or node.get("long-clickable") == "true"
                or node.get("scrollable") == "true"
                or bool(rid)
            )
            elements.append({
                "element_id": f"el_{counter:04d}",
                "class": cls,
                "bbox": bounds,
                "source": "ipg_listener",
                "resource_id": rid,
                "text": text,
                "description": desc,
                "executed_events": [],
                "is_actionable": is_actionable,
                "note": None,
            })
            counter += 1
        for child in node:
            walk(child)

    walk(root)
    return elements


def find_element_id(elements: list[dict], action_meta: dict) -> Optional[str]:
    """Match the action's source node against this screen's elements."""
    src = action_meta.get("source") or {}
    rid = src.get("resourceId")
    if rid:
        for el in elements:
            if el["resource_id"] == rid:
                return el["element_id"]
    bbox = parse_bounds(src.get("bounds"))
    if bbox:
        for el in elements:
            if el["bbox"] == bbox:
                return el["element_id"]
    return None


def event_kind_of(action_type: str) -> str:
    return {
        "VIEW_CLICKED": "tap",
        "VIEW_LONG_CLICKED": "long_tap",
        "VIEW_SCROLLED": "swipe",
        "WINDOW_CONTENT_CHANGED": "change",
    }.get(action_type, "action")


def build(session_dir: Path) -> tuple[Path, Path]:
    xml_dir = session_dir / "xml"
    json_dir = session_dir / "json"
    if not xml_dir.is_dir():
        raise FileNotFoundError(f"no xml/ in {session_dir}")

    # Load (seq, meta, xml_text) triples ordered by seq
    events: list[tuple[str, dict, str]] = []
    for xml_path in sorted(xml_dir.glob("*.xml")):
        seq = xml_path.stem
        meta_path = json_dir / f"{seq}.json"
        meta: dict = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        try:
            xml = xml_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        events.append((seq, meta, xml))

    if not events:
        raise RuntimeError(f"no events parsed in {session_dir}")

    # Compute screen_id per event + group snapshots
    sequence: list[tuple[str, str, dict]] = []
    screens: dict[str, dict] = {}
    representative_xml: dict[str, str] = {}  # screen_id -> xml of first snapshot
    for seq, meta, xml in events:
        sid = screen_id_of(xml)
        sequence.append((seq, sid, meta))
        if sid not in screens:
            screens[sid] = {"snapshots": [], "first": seq, "last": seq}
            representative_xml[sid] = xml
        screens[sid]["snapshots"].append(seq)
        screens[sid]["last"] = seq

    # Order sids by first appearance
    ordered_sids: list[str] = []
    seen: set[str] = set()
    for _, sid, _ in sequence:
        if sid not in seen:
            ordered_sids.append(sid)
            seen.add(sid)

    # Extract elements for each unique screen
    screen_elements: dict[str, list[dict]] = {
        sid: extract_elements(representative_xml[sid]) for sid in ordered_sids
    }

    # Build edges; resolve trigger element_id against the SOURCE screen.
    # Trigger candidate priority (within EDGE_LOOKBACK events):
    #   1. VIEW_CLICKED / VIEW_LONG_CLICKED  (definite user tap)
    #   2. VIEW_SCROLLED                      (user swipe)
    #   3. WINDOW_CONTENT_CHANGED with source (something visibly changed —
    #      useful fallback when user input came via raw touch / `input tap`
    #      which doesn't fire VIEW_CLICKED)
    edges: list[dict] = []
    last_user_action: Optional[tuple[int, dict]] = None
    last_content_source: Optional[tuple[int, dict]] = None

    for i in range(1, len(sequence)):
        prev_seq, prev_sid, prev_meta = sequence[i - 1]
        curr_seq, curr_sid, curr_meta = sequence[i]

        ptype = prev_meta.get("type", "")
        if ptype in ("VIEW_CLICKED", "VIEW_SCROLLED", "VIEW_LONG_CLICKED"):
            last_user_action = (i - 1, prev_meta)
        elif ptype == "WINDOW_CONTENT_CHANGED" and (prev_meta.get("source") or {}).get("bounds"):
            last_content_source = (i - 1, prev_meta)

        if prev_sid == curr_sid:
            continue

        trigger_meta: Optional[dict] = None
        if last_user_action and (i - last_user_action[0]) <= EDGE_LOOKBACK:
            trigger_meta = last_user_action[1]
        elif last_content_source and (i - last_content_source[0]) <= EDGE_LOOKBACK:
            trigger_meta = last_content_source[1]

        if trigger_meta is not None:
            kind = event_kind_of(trigger_meta.get("type", ""))
            elem_id = find_element_id(screen_elements[prev_sid], trigger_meta)
            if elem_id:
                event_type = kind
                event_key = f"{kind}@{elem_id}"
            else:
                src_obj = trigger_meta.get("source") or {}
                fallback_id = src_obj.get("resourceId") or src_obj.get("bounds") or kind
                event_type = kind
                event_key = f"{kind}@{fallback_id}"
        else:
            event_type = "auto"
            event_key = f"auto@{curr_meta.get('type', '?')}"

        edges.append({
            "src": prev_sid,
            "dst": curr_sid,
            "event_type": event_type,
            "event_key": event_key,
            "description": None,
            "src_snapshot_id": prev_seq,
            "dst_snapshot_id": curr_seq,
        })

    # Populate executed_events on each element from edges
    for edge in edges:
        key = edge["event_key"]
        # Only edges keyed by element_id ("kind@el_NNNN") count for trigger mode
        m = re.match(r"^([a-z_]+)@(el_\d+)$", key)
        if not m:
            continue
        sid = edge["src"]
        elem_id = m.group(2)
        for el in screen_elements.get(sid, []):
            if el["element_id"] == elem_id and key not in el["executed_events"]:
                el["executed_events"].append(key)
                break

    # Build nodes
    nodes = [
        {
            "screen_id": sid,
            "index": idx,
            "snapshots": screens[sid]["snapshots"],
            "first_snapshot_id": screens[sid]["first"],
            "last_snapshot_id": screens[sid]["last"],
        }
        for idx, sid in enumerate(ordered_sids)
    ]

    # Write utg.json (next to PNGs so Monitor finds snapshots)
    utg = {"nodes": nodes, "edges": edges}
    utg_path = session_dir / "screen" / "utg.json"
    utg_path.parent.mkdir(parents=True, exist_ok=True)
    utg_path.write_text(json.dumps(utg, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write app_memory.json at <session>/json/ (Sidebar auto-load location)
    app_memory = {
        "screens": {
            sid: {
                "screen_id": sid,
                "snapshots": screens[sid]["snapshots"],
                "screenshot_path": f"screen/{screens[sid]['first']}.png",
                "xml_path": f"xml/{screens[sid]['first']}.xml",
                "elements": screen_elements[sid],
            }
            for sid in ordered_sids
        }
    }
    mem_path = session_dir / "json" / "app_memory.json"
    mem_path.parent.mkdir(parents=True, exist_ok=True)
    mem_path.write_text(json.dumps(app_memory, indent=2, ensure_ascii=False), encoding="utf-8")

    return utg_path, mem_path


def main() -> int:
    p = argparse.ArgumentParser(description="Build Monitor-compatible UTG + app_memory from a session.")
    p.add_argument("session_dir", type=Path)
    args = p.parse_args()
    try:
        utg_path, mem_path = build(args.session_dir)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1
    utg = json.loads(utg_path.read_text(encoding="utf-8"))
    mem = json.loads(mem_path.read_text(encoding="utf-8"))
    total_elems = sum(len(s["elements"]) for s in mem["screens"].values())
    triggered = sum(
        1 for s in mem["screens"].values() for e in s["elements"] if e["executed_events"]
    )
    print(
        f"[+] {utg_path} ({len(utg['nodes'])} nodes, {len(utg['edges'])} edges)\n"
        f"[+] {mem_path} ({len(mem['screens'])} screens, {total_elems} elements, "
        f"{triggered} with executed events)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
