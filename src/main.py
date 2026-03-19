from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cli.parser import build_parser
from core.config import (
    ComputeDevice,
    DetectionConfig,
    InputConfig,
    LogMode,
    OcrMode,
    PacketConfig,
    RuntimeConfig,
    ScreenIdConfig,
    ScreenIdKind,
    ScreenTransitionMode,
    Settings,
    TraversalConfig,
    UiDetectionMode,
)
from core.runtime.runner import Runner
from core.utils.path_manager import PathManager
from core.utils.logger import build_logger


def make_default_settings() -> Settings:
    return Settings(
        traversal=TraversalConfig(
            loop_threshold=1000,
            back_threshold=15,
            same_screen_threshold=10,
            timeout_sec=3600,
            interval_sec=2,
        ),
        detection=DetectionConfig(
            ocr_mode=OcrMode.PADDLE,
            ui_detection_mode=UiDetectionMode.HYBRID,
            screen_transition_mode=ScreenTransitionMode.SCREEN_ID,
            iou_threshold=0.84,
        ),
        packet=PacketConfig(
            packet_threshold=10,
            capture_time_sec=3,
        ),
        input=InputConfig(
            swipe_start_ratio=0.8,
            swipe_end_ratio=0.2,
        ),
        runtime=RuntimeConfig(
            compute_device=ComputeDevice.CPU,
            log_mode=LogMode.DEBUG,
            enable_utg=False,
            draw_detection=False,
        ),
        screen_id=ScreenIdConfig(
            kind=ScreenIdKind.LAYOUT_BBOX,
            algorithm="greedy_iou_v1",
            threshold=0.84,
        ),
    )


def apply_cli_overrides(settings: Settings, args) -> Settings:
    settings.runtime.enable_utg = bool(args.utg)
    settings.runtime.draw_detection = bool(args.draw)
    
    if args.no_log:
        settings.runtime.log_mode = LogMode.NO_LOG
    elif args.debug:
        settings.runtime.log_mode = LogMode.DEBUG
    else:
        settings.runtime.log_mode = LogMode.NORMAL

    return settings


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    settings = make_default_settings()
    settings = apply_cli_overrides(settings, args)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    paths = PathManager(
        root=Path("outputs"),
        app=args.app,
        timestamp=timestamp,
    )

    paths.create_dirs()

    logger = build_logger(
        name=f"iotpacket.{args.app}",
        log_mode=settings.runtime.log_mode,
        log_path=paths.runtime_log,
    )

    runner = Runner(
        settings=settings,
        paths=paths,
        app_name=args.app,
        launcher_activity=None,
        replay=False,
        device_serial=args.serial,
        adb_path="adb",
        logger=logger,
    )
    runner.run()


if __name__ == "__main__":
    main()