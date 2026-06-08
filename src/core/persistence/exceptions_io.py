from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.persistence.json_io import read_json, write_json
from core.utils.path_manager import PathManager


class ExceptionsIO:
    def __init__(self, paths: PathManager) -> None:
        self.paths = paths

    def load(self) -> dict[str, Any]:
        if not self.paths.exceptions_file.exists():
            return {"app_name": self.paths.app, "exclusions": []}

        data = read_json(self.paths.exceptions_file)
        if not isinstance(data, dict) or "exclusions" not in data:
            return {"app_name": self.paths.app, "exclusions": []}
        return data

    def load_screen_ids(self) -> set[str]:
        data = self.load()
        return {
            entry["screen_id"]
            for entry in data.get("exclusions", [])
            if isinstance(entry, dict) and "screen_id" in entry
        }

    def save(self, data: dict[str, Any]) -> None:
        write_json(self.paths.exceptions_file, data)

    def add_screen(
        self,
        screen_id: str,
        snapshot_path: Path | None = None,
    ) -> bool:
        data = self.load()
        for entry in data["exclusions"]:
            if entry.get("screen_id") == screen_id:
                return False

        data["exclusions"].append({
            "screen_id": screen_id,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_path": str(snapshot_path) if snapshot_path else None,
        })
        self.save(data)
        return True

    def remove_screen(self, screen_id: str) -> bool:
        data = self.load()
        before = len(data["exclusions"])
        data["exclusions"] = [
            e for e in data["exclusions"]
            if e.get("screen_id") != screen_id
        ]
        if len(data["exclusions"]) == before:
            return False
        self.save(data)
        return True
