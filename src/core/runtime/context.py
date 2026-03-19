from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.adb.device import ADBDevice
from core.app_types.run_meta import AppMeta, DeviceMeta
from core.app_types.screen import Screen
from core.config import Settings
from core.graph.utg import UTGGraphData
from core.memory.app_memory import AppMemoryStore
from core.memory.packet_memory import PacketMemoryStore
from core.memory.screen_memory import ScreenMemoryStore
from core.utils.path_manager import PathManager
from core.runtime.monitor.foreground_monitor import ForegroundState


@dataclass(slots=True)
class RuntimeContext:
    settings: Settings
    paths: PathManager

    adb_device: ADBDevice
    target_app_name: str
    target_package: str
    launcher_activity: str | None = None

    app_memory: AppMemoryStore = field(default_factory=AppMemoryStore)
    screen_memory: ScreenMemoryStore = field(default_factory=ScreenMemoryStore)
    packet_memory: PacketMemoryStore = field(default_factory=PacketMemoryStore)
    utg: UTGGraphData = field(default_factory=UTGGraphData)

    foreground_state: ForegroundState = field(default_factory=ForegroundState)

    device_meta: DeviceMeta | None = None
    app_meta: AppMeta | None = None

    detector: Any = None
    executor: object | None = None
    traverser: object | None = None

    start_ts: str | None = None
    end_ts: str | None = None
    duration_sec: float | None = None

    current_screen_key: str | None = None
    previous_screen_key: str | None = None

    current_screen: Screen | None = None
    previous_screen: Screen | None = None

    screen_visit_count: dict[str, int] = field(default_factory=dict)

    app_restart_count: int = 0
    foreground_recover_count: int = 0
    terminal_reason: str | None = None

    step_count: int = 0
    same_screen_streak: int = 0

    logger: Any = None

    @property
    def screen_wh(self) -> tuple[int, int] | None:
        if self.device_meta is None:
            return None
        return (
            int(self.device_meta.screen_width),
            int(self.device_meta.screen_height),
        )