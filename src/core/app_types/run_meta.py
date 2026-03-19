#src/core/app_types/run_meta.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DeviceMeta:
    model: str
    manufacturer: str
    version: str
    sdk: str
    serial: str
    screen_width: int
    screen_height: int


@dataclass(slots=True)
class AppMeta:
    app_name: str
    package: str
    version: str
    version_code: str
    uid: str | None = None
    last_update: str | None = None


@dataclass(slots=True)
class ExperimentMeta:
    traversal: dict[str, object]
    detection: dict[str, object]
    packet: dict[str, object]
    input: dict[str, object]
    runtime: dict[str, object]
    screen_id: dict[str, object]


@dataclass(slots=True)
class SummaryMeta:
    unique_screen_count: int = 0
    total_screen_count: int = 0
    screen_visit_count: dict[str, int] = field(default_factory=dict)
    packet_event_count: int = 0
    app_restart_count: int = 0
    foreground_recover_count: int = 0
    terminal_reason: str | None = None


@dataclass(slots=True)
class RunMeta:
    start_ts: str
    end_ts: str | None = None
    duration_sec: float | None = None

    device: DeviceMeta | None = None
    app: AppMeta | None = None
    experiment: ExperimentMeta | None = None
    summary: SummaryMeta = field(default_factory=SummaryMeta)