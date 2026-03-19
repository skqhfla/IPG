#src/core/utils/path_manager.py
from __future__ import annotations

from pathlib import Path


class PathManager:
    def __init__(self, root: Path, app: str, timestamp: str) -> None:
        self.root = root
        self.app = app
        self.timestamp = timestamp

        self.base = root / app / timestamp

        self.xml = self.base / "xml"
        self.screen = self.base / "screen"
        self.memory = self.base / "json"
        self.utg = self.base / "utg"
        self.logs = self.base / "logs"

        self.run_meta = self.base / "run_meta.json"

        self.detect_base = self.base / "detect_images"

        self.detect = {
            "base": self.detect_base,
            "uiauto": self.detect_base / "uiauto",
            "yolo": self.detect_base / "yolo",
            "merged": self.detect_base / "merged",
        }

    def create_dirs(self) -> None:
        """
        실험 시작 시 필요한 디렉터리 생성
        """
        dirs = [
            self.base,
            self.xml,
            self.screen,
            self.memory,
            self.utg,
            self.logs,
            self.detect_base,
            self.detect["uiauto"],
            self.detect["yolo"],
            self.detect["merged"],
        ]

        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    # -----------------------------
    # memory paths
    # -----------------------------

    @property
    def app_memory(self) -> Path:
        return self.memory / "app_memory.json"

    @property
    def screen_memory(self) -> Path:
        return self.memory / "screen_memory.json"

    @property
    def packet_memory(self) -> Path:
        return self.memory / "packet_memory.json"

    # -----------------------------
    # UTG
    # -----------------------------

    @property
    def utg_json(self) -> Path:
        return self.utg / "utg.json"

    @property
    def utg_png(self) -> Path:
        return self.utg / "utg.png"
    # -----------------------------
    # log
    # -----------------------------

    @property
    def runtime_log(self) -> Path:
        return self.logs / "runtime.log"