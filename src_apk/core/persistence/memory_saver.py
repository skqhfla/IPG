#src/core/persistence/memory_saver.py
from __future__ import annotations

from pathlib import Path

from core.memory.app_memory import AppMemoryStore
from core.memory.screen_memory import ScreenMemoryStore
from core.memory.packet_memory import PacketMemoryStore

from .json_io import write_json


class MemorySaver:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    @property
    def app_memory_path(self) -> Path:
        return self.output_dir / "app_memory.json"

    @property
    def screen_memory_path(self) -> Path:
        return self.output_dir / "screen_memory.json"

    @property
    def packet_memory_path(self) -> Path:
        return self.output_dir / "packet_memory.json"

    def save_app_memory(self, app_memory: AppMemoryStore) -> None:
        payload = {
            "screens": app_memory.to_dict(),
        }
        write_json(self.app_memory_path, payload)

    def save_screen_memory(self, screen_memory: ScreenMemoryStore) -> None:
        payload = {
            "screens": screen_memory.to_dict(),
        }
        write_json(self.screen_memory_path, payload)

    def save_packet_memory(self, packet_memory: PacketMemoryStore) -> None:
        payload = {
            "screens": packet_memory.to_dict(),
        }
        write_json(self.packet_memory_path, payload)

    def save_all(
        self,
        app_memory: AppMemoryStore,
        screen_memory: ScreenMemoryStore,
        packet_memory: PacketMemoryStore,
    ) -> None:
        self.save_app_memory(app_memory)
        self.save_screen_memory(screen_memory)
        self.save_packet_memory(packet_memory)