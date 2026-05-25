"""
Tail logcat for IPG_EVT DUMP_* lines and pull each XML/JSON/PNG to host.

Two output modes mirroring the APK:
  - "ipg":   <out_root>/<appLabel>/<session>/{xml,screen,json}/<seq>.{xml,png,json}
            Default out_root = repo_root/outputs_APK
  - "flat":  <out_root>/<session>/<basename>.{xml,json,png}
            Default out_root = device_listener/captures

On Ctrl+C the collector runs build_utg.py against every IPG-mode session it
touched, producing <session>/screen/utg.json for the Monitor webapp.

Usage:
    python device_listener/host/dump_collector.py [options]

Options:
    --keep                Don't delete files from device after pulling.
    --no-screenshots      Skip screenshot capture / pull.
    --no-utg              Skip auto UTG build at shutdown.
    --include-backlog     Process events already in the logcat ring buffer.
    --ipg-out DIR         Override IPG-mode root (default: repo/outputs_APK).
    --flat-out DIR        Override flat-mode root (default: device_listener/captures).
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import subprocess
import sys


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_IPG_OUT = REPO_ROOT / "outputs_APK"
DEFAULT_FLAT_OUT = SCRIPT_DIR.parent / "captures"
HOST_SCREENCAP_REMOTE = "/sdcard/_ipg_screencap.png"
BUILD_UTG_SCRIPT = SCRIPT_DIR / "build_utg.py"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pull IPG dump files as they are written.")
    p.add_argument("--ipg-out", type=pathlib.Path, default=DEFAULT_IPG_OUT)
    p.add_argument("--flat-out", type=pathlib.Path, default=DEFAULT_FLAT_OUT)
    p.add_argument("--keep", action="store_true",
                   help="Keep files on the device after pulling (default: delete).")
    p.add_argument("--no-screenshots", action="store_true",
                   help="Skip screenshot capture and pull entirely.")
    p.add_argument("--no-utg", action="store_true",
                   help="Skip auto UTG build at shutdown.")
    p.add_argument("--include-backlog", action="store_true",
                   help="Process events already in the logcat ring buffer (default: only new).")
    return p.parse_args()


def adb_pull(remote: str, local: pathlib.Path, quiet_missing: bool = True) -> bool:
    local.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["adb", "pull", remote, str(local)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        msg = r.stderr.strip()
        if quiet_missing and "No such file" in msg:
            return False
        sys.stderr.write(f"[!] pull failed: {remote} :: {msg}\n")
        return False
    return True


def adb_rm(remote: str) -> None:
    subprocess.run(["adb", "shell", "rm", "-f", remote], capture_output=True)


def adb_screencap(remote: str) -> bool:
    r = subprocess.run(
        ["adb", "shell", "screencap", "-p", remote],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        sys.stderr.write(f"[!] screencap failed :: {r.stderr.strip()}\n")
        return False
    return True


def parse_event(line: str) -> dict | None:
    i = line.find("IPG_EVT")
    if i < 0:
        return None
    j = line.find("{", i)
    if j < 0:
        return None
    try:
        return json.loads(line[j:].strip())
    except json.JSONDecodeError:
        return None


def session_root(evt: dict, args: argparse.Namespace) -> pathlib.Path:
    """Compute the local root dir for this DUMP_* event."""
    session = str(evt.get("session", "unknown"))
    if evt.get("outputMode") == "ipg":
        app_label = str(evt.get("appLabel", "_filtered"))
        return args.ipg_out / app_label / session
    return args.flat_out / session


def local_path_for(remote: str, session_dir: pathlib.Path, output_mode: str) -> pathlib.Path:
    """Mirror the device-side relative location under the local session dir."""
    name = pathlib.PurePosixPath(remote).name
    if output_mode == "ipg":
        # Device path: .../captures/<app>/<session>/<subdir>/<name>
        # We want:    <session_dir>/<subdir>/<name>
        parent = pathlib.PurePosixPath(remote).parent.name  # xml | screen | json
        return session_dir / parent / name
    return session_dir / name


def handle_dump_written(evt: dict, args: argparse.Namespace,
                        screenshots: bool, sessions_touched: set[pathlib.Path]) -> None:
    xml_remote = evt.get("xml")
    meta_remote = evt.get("meta")
    if not xml_remote or not meta_remote:
        return

    output_mode = evt.get("outputMode", "flat")
    sess_dir = session_root(evt, args)

    xml_local = local_path_for(xml_remote, sess_dir, output_mode)
    meta_local = local_path_for(meta_remote, sess_dir, output_mode)

    ok_xml = adb_pull(xml_remote, xml_local)
    ok_meta = adb_pull(meta_remote, meta_local)

    if ok_xml and ok_meta and not args.keep:
        adb_rm(xml_remote)
        adb_rm(meta_remote)

    if not (ok_xml and ok_meta):
        return

    if output_mode == "ipg":
        sessions_touched.add(sess_dir)

    suffix = ""
    if screenshots and evt.get("screenshotMode") == "host":
        # Compute the local PNG destination from the screenshotTarget the APK
        # told us (so it matches the IPG screen/<seq>.png convention there too).
        target = evt.get("screenshotTarget")
        if target:
            png_local = local_path_for(target, sess_dir, output_mode)
        else:
            xml_name = pathlib.PurePosixPath(xml_remote).name
            png_name = xml_name[:-4] + ".png" if xml_name.endswith(".xml") else xml_name + ".png"
            if output_mode == "ipg":
                png_local = sess_dir / "screen" / png_name
            else:
                png_local = sess_dir / png_name
        if adb_screencap(HOST_SCREENCAP_REMOTE):
            if adb_pull(HOST_SCREENCAP_REMOTE, png_local):
                suffix = " [+png]"
            adb_rm(HOST_SCREENCAP_REMOTE)

    print(f"[+] {sess_dir.name}/{xml_local.name}{suffix}", flush=True)


def handle_dump_screenshot(evt: dict, args: argparse.Namespace,
                           screenshots: bool, sessions_touched: set[pathlib.Path]) -> None:
    path = evt.get("path")
    if not path:
        return

    if not screenshots:
        # APK still wrote it; clean it up so storage doesn't pile up.
        if not args.keep:
            adb_rm(path)
        return

    output_mode = evt.get("outputMode", "ipg" if "captures/" in path else "flat")
    sess_dir = session_root(evt, args)
    local_png = local_path_for(path, sess_dir, output_mode)

    if adb_pull(path, local_png):
        if not args.keep:
            adb_rm(path)
        if output_mode == "ipg":
            sessions_touched.add(sess_dir)
        print(f"[+] {sess_dir.name}/{local_png.name}", flush=True)


def build_utg_for(sessions: set[pathlib.Path]) -> None:
    if not BUILD_UTG_SCRIPT.exists():
        sys.stderr.write(f"[!] {BUILD_UTG_SCRIPT} missing — skipping UTG build\n")
        return
    for sess in sorted(sessions):
        if not (sess / "xml").is_dir():
            continue
        print(f"[utg] building for {sess}...", flush=True)
        r = subprocess.run(
            [sys.executable, str(BUILD_UTG_SCRIPT), str(sess)],
            capture_output=False,
        )
        if r.returncode != 0:
            sys.stderr.write(f"[!] UTG build failed for {sess}\n")


def main() -> int:
    args = parse_args()
    args.ipg_out.mkdir(parents=True, exist_ok=True)
    args.flat_out.mkdir(parents=True, exist_ok=True)
    print(f"[dump_collector] ipg_out={args.ipg_out}", flush=True)
    print(f"[dump_collector] flat_out={args.flat_out}", flush=True)
    print(f"[dump_collector] device files will be {'kept' if args.keep else 'deleted'} after pull", flush=True)
    print(f"[dump_collector] screenshots {'OFF' if args.no_screenshots else 'ON'}", flush=True)
    print(f"[dump_collector] auto-utg {'OFF' if args.no_utg else 'ON'} (runs on Ctrl+C)", flush=True)

    logcat_cmd = ["adb", "logcat", "-s", "IPG_EVT:I"]
    if not args.include_backlog:
        now_str = datetime.datetime.now().strftime("%m-%d %H:%M:%S.000")
        logcat_cmd[2:2] = ["-T", now_str]

    proc = subprocess.Popen(
        logcat_cmd,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    assert proc.stdout is not None

    screenshots = not args.no_screenshots
    sessions_touched: set[pathlib.Path] = set()

    try:
        for line in proc.stdout:
            evt = parse_event(line)
            if not evt:
                continue
            t = evt.get("type")
            if t == "DUMP_WRITTEN":
                handle_dump_written(evt, args, screenshots, sessions_touched)
            elif t == "DUMP_SCREENSHOT":
                handle_dump_screenshot(evt, args, screenshots, sessions_touched)
            elif t == "DUMP_SCREENSHOT_FAILED":
                seq = evt.get("seq")
                reason = evt.get("reason")
                print(f"[!] screenshot failed seq={seq} :: {reason}", flush=True)
    except KeyboardInterrupt:
        print("\n[dump_collector] interrupted", flush=True)
    finally:
        proc.terminate()
        if not args.no_utg:
            build_utg_for(sessions_touched)

    return 0


if __name__ == "__main__":
    sys.exit(main())
