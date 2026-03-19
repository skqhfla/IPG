#src/core/persistence/memory_loader.py
from __future__ import annotations

from pathlib import Path

from core.app_types import BBox, Element, Screen, ScreenID
from core.memory.app_memory import AppMemoryStore
from core.memory.packet_memory import PacketMemoryStore
from core.memory.screen_memory import ScreenMemoryStore

from .json_io import read_json


class MemoryLoader:
    def __init__(self, input_dir: Path) -> None:
        self.input_dir = input_dir

    @property
    def app_memory_path(self) -> Path:
        return self.input_dir / "app_memory.json"

    @property
    def screen_memory_path(self) -> Path:
        return self.input_dir / "screen_memory.json"

    @property
    def packet_memory_path(self) -> Path:
        return self.input_dir / "packet_memory.json"

    def load_app_memory(self) -> AppMemoryStore:
        store = AppMemoryStore()

        if not self.app_memory_path.exists():
            return store

        payload = read_json(self.app_memory_path)
        screens = payload.get("screens", {})

        for screen_key, screen_data in screens.items():
            screen_id = ScreenID(value=screen_data["screen_id"])

            screenshot_path_raw = screen_data.get("screenshot_path")
            xml_path_raw = screen_data.get("xml_path")

            elements: list[Element] = []
            for item in screen_data.get("elements", []):
                bbox = BBox(*item["bbox"])

                element = Element(
                    element_id=item["element_id"],
                    cls=item["class"],
                    bbox=bbox,
                    source=item["source"],
                    resource_id=item.get("resource_id"),
                    text=item.get("text"),
                    description=item.get("description"),
                    is_actionable=item.get("is_actionable", True),
                    note=item.get("note"),
                )

                for event_key in item.get("executed_events", []):
                    element.mark_executed(event_key)

                elements.append(element)

            screen = Screen(
                screen_id=screen_id,
                elements=elements,
                screenshot_path=Path(screenshot_path_raw) if screenshot_path_raw else None,
                xml_path=Path(xml_path_raw) if xml_path_raw else None,
            )

            store.upsert_screen(screen)

            for snapshot_id in screen_data.get("snapshots", []):
                store.add_snapshot(screen_key, snapshot_id)

        return store

    def load_screen_memory(self) -> ScreenMemoryStore:
        store = ScreenMemoryStore()

        if not self.screen_memory_path.exists():
            return store

        payload = read_json(self.screen_memory_path)
        screens = payload.get("screens", {})

        for dst_screen_key, transitions in screens.items():
            for item in transitions:
                store.record_transition(
                    dst_screen_key=dst_screen_key,
                    src_screen_key=item["src_screen_key"],
                    event_key=item["event_key"],
                )

        return store

    def load_packet_memory(self) -> PacketMemoryStore:
        store = PacketMemoryStore()

        if not self.packet_memory_path.exists():
            return store

        payload = read_json(self.packet_memory_path)
        screens = payload.get("screens", {})

        for screen_key, screen_data in screens.items():
            for event_key in screen_data.get("events", []):
                store.add_event(screen_key, event_key)

        return store

    def load_all(
        self,
    ) -> tuple[AppMemoryStore, ScreenMemoryStore, PacketMemoryStore]:
        app_memory = self.load_app_memory()
        screen_memory = self.load_screen_memory()
        packet_memory = self.load_packet_memory()
        return app_memory, screen_memory, packet_memory