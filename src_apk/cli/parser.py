from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="IoT App Traversal Framework",
    )

    parser.add_argument(
        "--app",
        type=str,
        default="Hejhome",
        help="Target app name",
    )

    parser.add_argument(
        "--serial",
        type=str,
        default=None,
        help="ADB device serial",
    )

    parser.add_argument(
        "--runtime",
        type=int,
        default=3600,
        help="Traversal timeout in seconds",
    )

    parser.add_argument(
        "--detection-mode",
        type=str,
        choices=["hybrid", "yolo", "uiautomator"],
        default=None,
        help="UI detection mode override (default: hybrid)",
    )

    parser.add_argument(
        "--utg",
        action="store_true",
        help="Enable UTG recording (utg.json / utg.png)",
    )

    parser.add_argument(
        "--draw",
        action="store_true",
        help="Save UI detection visualization images",
    )

    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Disable log file output",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode",
    )

    parser.add_argument(
        "--scroll-debug",
        action="store_true",
        help="Log only scroll-related lines "
        "(VIEW_SCROLLED events, [SCROLL], [POLICY], scroll swipes)",
    )

    parser.add_argument(
        "--node-loop-repetition",
        type=int,
        default=3,
        help="Repetition count for node loop detection (default: 3)",
    )

    parser.add_argument(
        "--setup",
        action="store_true",
        help="Setup mode: interactively register screens to exclude from traversal",
    )

    parser.add_argument(
        "--rerun",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Re-execution mode: load memory from a previous run dir "
            "(e.g. outputs_APK/Hejhome/20260526_120000) and only attempt "
            "events that were never triggered. Output goes to a new timestamp dir."
        ),
    )

    return parser