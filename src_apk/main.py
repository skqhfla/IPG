from __future__ import annotations

from datetime import datetime
from pathlib import Path

import sys

from cli.parser import build_parser
from core.adb.a11y_event_listener import A11yServiceUnavailable
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
from core.runtime.setup_runner import SetupRunner
from core.utils.path_manager import PathManager
from core.utils.logger import build_logger


def make_default_settings() -> Settings:
    return Settings(
        traversal=TraversalConfig(
            loop_threshold=1000,
            back_threshold=1500,
            same_screen_threshold=1000,
            timeout_sec=3600,
            interval_sec=2,
            node_loop_repetition=5,
            excluded_streak_threshold=3,
            stability_poll_interval_ms=300,
            stability_max_wait_sec=3.0,
            stability_required_matches=2,
            swipe_directions=("down", "up"),
            swipe_settle_ms=500,
            scroll_overlap_ratio=0.3,
            scroll_swipe_duration_ms=800,
            max_consecutive_scrolls=12,
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
            kind=ScreenIdKind.LAYOUT_TREE,
            algorithm="greedy_iou_v1",
            threshold=0.84,
            match_threshold=0.6,
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

    if args.node_loop_repetition:
        settings.traversal.node_loop_repetition = args.node_loop_repetition

    if args.detection_mode:
        settings.detection.ui_detection_mode = UiDetectionMode(args.detection_mode)

    if args.runtime:
        settings.traversal.timeout_sec = int(args.runtime)

    return settings


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    settings = make_default_settings()
    settings = apply_cli_overrides(settings, args)

    rerun_source: Path | None = None
    if args.rerun:
        rerun_source = Path(args.rerun)
        if not (rerun_source / "json" / "app_memory.json").exists():
            print(
                f"[ABORT] --rerun: app_memory.json not found under "
                f"{rerun_source / 'json'}",
                file=sys.stderr,
            )
            sys.exit(2)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    paths = PathManager(
        root=Path("outputs_APK"),
        app=args.app,
        timestamp=timestamp,
    )

    paths.create_dirs()

    logger = build_logger(
        name=f"iotpacket.{args.app}",
        log_mode=settings.runtime.log_mode,
        log_path=paths.runtime_log,
        scroll_debug=args.scroll_debug,
    )

    if args.setup:
        setup = SetupRunner(
            settings=settings,
            paths=paths,
            app_name=args.app,
            launcher_activity=None,
            device_serial=args.serial,
            adb_path="adb",
            logger=logger,
        )
        try:
            setup.run()
        except A11yServiceUnavailable as e:
            logger.error(f"[A11Y] {e}")
            print(f"\n[ABORT] {e}\n", file=sys.stderr)
            sys.exit(2)
        return

    if rerun_source is not None:
        logger.info(
            f"[RERUN] memory를 {rerun_source} 에서 로드해 미트리거 이벤트만 수행"
        )

    runner = Runner(
        settings=settings,
        paths=paths,
        app_name=args.app,
        launcher_activity=None,
        rerun_source=rerun_source,
        device_serial=args.serial,
        adb_path="adb",
        logger=logger,
    )
    try:
        runner.run()
    except A11yServiceUnavailable as e:
        logger.error(f"[A11Y] {e}")
        print(f"\n[ABORT] {e}\n", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()