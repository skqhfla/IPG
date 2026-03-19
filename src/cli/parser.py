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

    return parser