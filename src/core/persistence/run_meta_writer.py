from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from core.app_types.run_meta import (
    AppMeta,
    DeviceMeta,
    ExperimentMeta,
    RunMeta,
    SummaryMeta,
)
from core.config import Settings
from core.memory.app_memory import AppMemoryStore
from core.memory.packet_memory import PacketMemoryStore

from .json_io import write_json


class RunMetaWriter:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path

    def build_experiment_meta(self, settings: Settings) -> ExperimentMeta:
        return ExperimentMeta(
            traversal=asdict(settings.traversal),
            detection={
                "ocr_mode": settings.detection.ocr_mode.value,
                "ui_detection_mode": settings.detection.ui_detection_mode.value,
                "screen_transition_mode": settings.detection.screen_transition_mode.value,
                "iou_threshold": settings.detection.iou_threshold,
            },
            packet=asdict(settings.packet),
            input=asdict(settings.input),
            runtime={
                "compute_device": settings.runtime.compute_device.value,
                "log_mode": settings.runtime.log_mode.value,
                "enable_utg": settings.runtime.enable_utg,
                "draw_detection": settings.runtime.draw_detection,
                "foreground_poll_interval_sec": settings.runtime.foreground_poll_interval_sec,
            },
            screen_id={
                "kind": settings.screen_id.kind.value,
                "algorithm": settings.screen_id.algorithm,
                "threshold": settings.screen_id.threshold,
            },
        )

    def build_summary_meta(
        self,
        app_memory: AppMemoryStore,
        packet_memory: PacketMemoryStore,
        screen_visit_count: dict[str, int] | None = None,
        app_restart_count: int = 0,
        foreground_recover_count: int = 0,
        terminal_reason: str | None = None,
    ) -> SummaryMeta:
        if screen_visit_count is None:
            screen_visit_count = {}

        total_screen_count = sum(screen_visit_count.values()) if screen_visit_count else 0

        return SummaryMeta(
            unique_screen_count=app_memory.screen_count(),
            total_screen_count=total_screen_count,
            screen_visit_count=screen_visit_count,
            packet_event_count=packet_memory.total_event_count(),
            app_restart_count=app_restart_count,
            foreground_recover_count=foreground_recover_count,
            terminal_reason=terminal_reason,
        )

    def build_run_meta(
        self,
        start_ts: str,
        end_ts: str | None,
        duration_sec: float | None,
        settings: Settings,
        device_meta: DeviceMeta | None,
        app_meta: AppMeta | None,
        app_memory: AppMemoryStore,
        packet_memory: PacketMemoryStore,
        screen_visit_count: dict[str, int] | None = None,
        app_restart_count: int = 0,
        foreground_recover_count: int = 0,
        terminal_reason: str | None = None,
    ) -> RunMeta:
        experiment = self.build_experiment_meta(settings)
        summary = self.build_summary_meta(
            app_memory=app_memory,
            packet_memory=packet_memory,
            screen_visit_count=screen_visit_count,
            app_restart_count=app_restart_count,
            foreground_recover_count=foreground_recover_count,   
            terminal_reason=terminal_reason,
        )

        return RunMeta(
            start_ts=start_ts,
            end_ts=end_ts,
            duration_sec=duration_sec,
            device=device_meta,
            app=app_meta,
            experiment=experiment,
            summary=summary,
        )

    def write(self, run_meta: RunMeta) -> None:
        payload = asdict(run_meta)
        write_json(self.output_path, payload)