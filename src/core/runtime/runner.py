from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
import queue
import threading

from core.adb import ADBClient, ADBDevice
from core.adb.metadata import collect_app_meta, collect_device_meta
from core.config import LogMode, Settings
from core.config.app_packages import get_app_package
from core.detection.factory import create_detector
from core.graph.utg import UTGGraphData
from core.memory.app_memory import AppMemoryStore
from core.memory.packet_memory import PacketMemoryStore
from core.memory.screen_memory import ScreenMemoryStore
from core.persistence.memory_loader import MemoryLoader
from core.persistence.memory_saver import MemorySaver
from core.persistence.run_meta_writer import RunMetaWriter
from core.persistence.utg_io import load_utg, save_utg
from core.persistence.utg_render import render_utg_png
from core.runtime.context import RuntimeContext
from core.runtime.loop import RuntimeLoop
from core.utils.path_manager import PathManager
from core.executor.factory import create_executor
from core.traversal.factory import create_traverser
from core.runtime.monitor.foreground_monitor import start_foreground_watcher


class Runner:
    def __init__(
        self,
        *,
        settings: Settings,
        paths: PathManager,
        app_name: str,
        launcher_activity: str | None = None,
        replay: bool = False,
        device_serial: str | None = None,
        adb_path: str = "adb",
        logger=None,
    ) -> None:
        self.settings = settings
        self.paths = paths
        self.app_name = app_name
        self.launcher_activity = launcher_activity
        self.replay = replay
        self.device_serial = device_serial
        self.adb_path = adb_path
        self.logger = logger

        self._started_monotonic: float | None = None
        self._has_started_experiment = False

        self.memory_loader = MemoryLoader(self.paths.memory)
        self.memory_saver = MemorySaver(self.paths.memory)
        self.run_meta_writer = RunMetaWriter(self.paths.run_meta)

        self.ctx: RuntimeContext | None = None

        self._fg_stop_event = threading.Event()
        self._fg_thread: threading.Thread | None = None

    # -------------------------------------------------
    # init helpers
    # -------------------------------------------------

    def init_adb_device(self) -> ADBDevice:
        client = ADBClient(
            device_serial=self.device_serial,
            adb_path=self.adb_path,
            logger=self.logger,
        )
        device = ADBDevice.create(client=client)
        device.require_device()
        return device

    def load_memories(self) -> tuple[AppMemoryStore, ScreenMemoryStore, PacketMemoryStore]:
        if self.replay:
            return self.memory_loader.load_all()
        return AppMemoryStore(), ScreenMemoryStore(), PacketMemoryStore()

    def load_utg(self) -> UTGGraphData:
        if self.replay:
            return load_utg(self.paths.utg_json)
        return UTGGraphData()

    # -------------------------------------------------
    # lifecycle
    # -------------------------------------------------

    def initialize(self) -> None:
        # 1. memory / utg load
        app_memory, screen_memory, packet_memory = self.load_memories()
        utg = self.load_utg()

        # 2. adb init
        adb_device = self.init_adb_device()

        # 3. target app resolve
        target_package = get_app_package(self.app_name)

        # 4. app launch
        adb_device.wakeup()
        adb_device.launch_app(target_package, self.launcher_activity)

        # 5. device/app meta
        device_meta = collect_device_meta(adb_device)
        app_meta = collect_app_meta(
            adb_device,
            app_name=self.app_name,
            package=target_package,
        )

        # 6. context build
        self.ctx = RuntimeContext(
            settings=self.settings,
            paths=self.paths,
            adb_device=adb_device,
            target_app_name=self.app_name,
            target_package=target_package,
            launcher_activity=self.launcher_activity,
            app_memory=app_memory,
            screen_memory=screen_memory,
            packet_memory=packet_memory,
            utg=utg,
            device_meta=device_meta,
            app_meta=app_meta,
            logger=self.logger,
        )

        # 7. foreground watcher starts
        self._fg_stop_event = threading.Event()
        self._fg_thread = start_foreground_watcher(
            device=adb_device,
            stop_event=self._fg_stop_event,
            poll_interval=self.settings.runtime.foreground_poll_interval_sec,
            logger=self.logger,
            state=self.ctx.foreground_state,
            target_package=self.ctx.target_package,
        )

        # 8. detector create
        self.ctx.detector = create_detector(self.ctx)
        self.ctx.executor = create_executor(self.ctx)
        self.ctx.traverser = create_traverser(self.ctx)

    def start_experiment_timer(self) -> None:
        """
        모든 메타 수집 / 앱 실행 / OCR / YOLO init 이후,
        첫 UI Detection 직전에만 호출된다.
        """
        if self._has_started_experiment:
            return

        assert self.ctx is not None

        self.ctx.start_ts = datetime.now(timezone.utc).isoformat()
        self._started_monotonic = time.monotonic()
        self._has_started_experiment = True

    def should_stop(self) -> bool:
        assert self.ctx is not None

        # timeout
        if self._started_monotonic is not None:
            elapsed = time.monotonic() - self._started_monotonic
            if elapsed >= self.settings.traversal.timeout_sec:
                self.ctx.terminal_reason = "timeout"
                return True

        # same screen threshold
        if self.ctx.same_screen_streak >= self.settings.traversal.back_threshold + 2:
            self.ctx.terminal_reason = "same_screen_limit"
            return True

        # loop threshold
        if self.ctx.step_count >= self.settings.traversal.loop_threshold:
            self.ctx.terminal_reason = "loop_limit"
            return True

        return False

    def run(self) -> None:
        self.initialize()
        assert self.ctx is not None

        loop = RuntimeLoop(
            self.ctx,
            on_before_first_detection=self.start_experiment_timer,
        )

        try:
            while not self.should_stop():
                loop.run_step()

        except KeyboardInterrupt:
            self.ctx.terminal_reason = "keyboard_interrupt"

        except Exception as e:
            self.ctx.terminal_reason = f"error:{type(e).__name__}"
            raise

        finally:
            self.finalize()

    def finalize(self) -> None:
        assert self.ctx is not None

        self._fg_stop_event.set()
        if self._fg_thread is not None:
            self._fg_thread.join(timeout=1.0)
            self._fg_thread = None

        if self._has_started_experiment:
            self.ctx.end_ts = datetime.now(timezone.utc).isoformat()
            if self._started_monotonic is not None:
                self.ctx.duration_sec = time.monotonic() - self._started_monotonic
        else:
            self.ctx.end_ts = None
            self.ctx.duration_sec = None

        # memory save
        self.memory_saver.save_all(
            self.ctx.app_memory,
            self.ctx.screen_memory,
            self.ctx.packet_memory,
        )

        # utg save/render
        if self.settings.runtime.enable_utg:
            save_utg(self.paths.utg_json, self.ctx.utg)
            render_utg_png(self.paths.utg_png, self.ctx.utg)

        # run_meta save
        run_meta = self.run_meta_writer.build_run_meta(
            start_ts=self.ctx.start_ts or "",
            end_ts=self.ctx.end_ts,
            duration_sec=self.ctx.duration_sec,
            settings=self.ctx.settings,
            device_meta=self.ctx.device_meta,
            app_meta=self.ctx.app_meta,
            app_memory=self.ctx.app_memory,
            packet_memory=self.ctx.packet_memory,
            screen_visit_count=self.ctx.screen_visit_count,
            app_restart_count=self.ctx.app_restart_count,
            foreground_recover_count=self.ctx.foreground_recover_count,
            terminal_reason=self.ctx.terminal_reason,
        )
        self.run_meta_writer.write(run_meta)

        if self.settings.runtime.log_mode != LogMode.NO_LOG:
            logging.shutdown()