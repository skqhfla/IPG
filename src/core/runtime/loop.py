from __future__ import annotations

from collections.abc import Callable
import time
from pathlib import Path

from core.app_types import EventType, Screen
from core.detection.result import DetectionResult
from core.detection.draw import draw_elements_on_image
from core.runtime.context import RuntimeContext
from core.config.settings import UiDetectionMode
from core.config.settings import LogMode

class RuntimeLoop:
    def __init__(
        self,
        ctx: RuntimeContext,
        on_before_first_detection: Callable[[], None] | None = None,
    ) -> None:
        self.ctx = ctx
        self.on_before_first_detection = on_before_first_detection
        self._first_detection_started = False
        self.interval_sec = ctx.settings.traversal.interval_sec

    def run_step(self) -> None:
        assert self.ctx.detector is not None
        assert self.ctx.executor is not None
        assert self.ctx.traverser is not None

        self._recover_if_needed()

        if not self._first_detection_started:
            if self.on_before_first_detection is not None:
                self.on_before_first_detection()
            self._first_detection_started = True

        if self.ctx.current_screen is None:
            before_det = self._detect_next_screen()
            before_screen = self._register_detection(
                det=before_det,
                snapshot_id=before_det.snapshot_id,
            )
            before_screen_key = before_screen.screen_id.to_key()

            self.ctx.current_screen = before_screen
            self.ctx.current_screen_key = before_screen_key
        else:
            before_det = None
            before_screen = self.ctx.current_screen
            before_screen_key = self.ctx.current_screen_key

        assert before_screen is not None
        assert before_screen_key is not None

        action = self.ctx.traverser.choose_action(
            ctx=self.ctx,
            screen=before_screen,
        )
        if action is None:
            self.ctx.terminal_reason = "no_more_actionable_events"
            return

        event_key = self.ctx.executor.execute(action)

        if self.interval_sec > 0:
            time.sleep(self.interval_sec)

        after_det = self._detect_next_screen()
        after_screen = self._register_detection(
            det=after_det,
            snapshot_id=after_det.snapshot_id,
        )
        after_screen_key = after_screen.screen_id.to_key()

        element_id = action.get("element_id")
        if element_id:
            self.ctx.app_memory.mark_event_executed(
                screen_key=before_screen_key,
                element_id=element_id,
                event_key=event_key,
            )

        transitioned = before_screen_key != after_screen_key

        if transitioned:
            self._record_transition(
                src_screen_key=before_screen_key,
                dst_screen_key=after_screen_key,
                event_key=event_key,
            )

            if self.ctx.settings.runtime.enable_utg:
                self._record_utg_transition(
                    before_screen=before_screen,
                    after_screen=after_screen,
                    before_snapshot_id=before_det.snapshot_id if before_det else None,
                    after_snapshot_id=after_det.snapshot_id,
                    event_key=event_key,
                )

            self.ctx.same_screen_streak = 0
        else:
            self.ctx.same_screen_streak += 1

        self.ctx.previous_screen = before_screen
        self.ctx.previous_screen_key = before_screen_key

        self.ctx.current_screen = after_screen
        self.ctx.current_screen_key = after_screen_key

    # -------------------------------------------------
    # helpers
    # -------------------------------------------------

    def _recover_if_needed(self) -> None:
        state = self.ctx.foreground_state
        target = self.ctx.target_package
        device = self.ctx.adb_device

        fg = state.get()
        if fg is None:
            return

        current_pkg, current_act = fg

        if current_pkg == target:
            return

        # 잠깐 튄 경우는 무시
        if state.mismatch_duration() < 1.0:
            return

        if self.ctx.logger:
            self.ctx.logger.warning(
                f"[RECOVER] foreground lost: current={current_pkg}/{current_act}, "
                f"target={target}"
            )

        # 1) soft recover
        device.bring_to_front(
            target,
            self.ctx.launcher_activity,
        )
        self.ctx.foreground_recover_count += 1
        self.invalidate_current_screen()

        time.sleep(1.0)

        # 2) verify
        after_soft = device.get_foreground_package()
        if after_soft == target:
            if self.ctx.logger:
                self.ctx.logger.info("[RECOVER] bring_to_front success")
            return

        if self.ctx.logger:
            self.ctx.logger.warning(
                f"[RECOVER] bring_to_front failed: current={after_soft}, "
                f"target={target}. restarting app."
            )

        # 3) hard recover
        device.launch_app(
            target,
            self.ctx.launcher_activity,
        )
        self.ctx.app_restart_count += 1
        self.invalidate_current_screen()

        time.sleep(1.0)
        
    def _detect_next_screen(self) -> DetectionResult:
        self.ctx.step_count += 1
        snapshot_id = f"{self.ctx.step_count:06d}"
        return self.ctx.detector.detect(snapshot_id)

    def _register_detection(
        self,
        *,
        det: DetectionResult,
        snapshot_id: str,
    ) -> Screen:
        detected_screen = det.screen

        # AppMemory의 canonical screen 사용
        screen = self.ctx.app_memory.get_or_add_screen(detected_screen)
        screen_key = screen.screen_id.to_key()

        self.ctx.app_memory.add_snapshot(screen_key, snapshot_id)

        self.ctx.screen_visit_count[screen_key] = (
            self.ctx.screen_visit_count.get(screen_key, 0) + 1
        )

        if (
            self.ctx.settings.runtime.draw_detection
            and self.ctx.settings.runtime.log_mode != LogMode.NO_LOG
        ):
            try:
                screenshot_path = detected_screen.screenshot_path
                if screenshot_path is not None:
                    self._save_detection_draws(
                        det=det,
                        snapshot_id=snapshot_id,
                        screen_key=screen_key,
                        screenshot_path=Path(screenshot_path),
                    )
            except Exception as e:
                if self.ctx.logger:
                    self.ctx.logger.warning(
                        f"[DRAW] failed to save detection overlay "
                        f"(snapshot={snapshot_id}): {e}"
                    )

        return screen
    
    def _record_transition(
        self,
        *,
        src_screen_key: str,
        dst_screen_key: str,
        event_key: str,
    ) -> None:
        self.ctx.screen_memory.record_transition(
            dst_screen_key=dst_screen_key,
            src_screen_key=src_screen_key,
            event_key=event_key,
        )

    def _record_utg_transition(
        self,
        *,
        before_screen: Screen | None,
        after_screen: Screen,
        before_snapshot_id: str | None,
        after_snapshot_id: str | None,
        event_key: str,
    ) -> None:

        if before_screen is None:
            return

        self.ctx.utg.add_transition(
            src_screen=before_screen.screen_id.value,
            dst_screen=after_screen.screen_id.value,
            event_type=self._infer_event_type(event_key),
            event_key=event_key,
            src_snapshot_id=before_snapshot_id,
            dst_snapshot_id=after_snapshot_id,
            src_screenshot_path=str(before_screen.screenshot_path) if before_screen.screenshot_path else None,
            dst_screenshot_path=str(after_screen.screenshot_path) if after_screen.screenshot_path else None,
        )

    def _infer_event_type(self, event_key: str) -> EventType:
        if event_key.startswith("tap@"):
            return EventType.TAP
        if event_key.startswith("swipe@"):
            return EventType.SWIPE
        if event_key.startswith("input@"):
            return EventType.INPUT
        return EventType.SCHEDULER

    def invalidate_current_screen(self) -> None:
        """
        외부 상태 변화로 current screen 재사용이 위험할 때 호출.
        다음 loop에서 다시 detection 하게 만든다.
        """
        self.ctx.current_screen = None
        self.ctx.current_screen_key = None

    def _save_detection_draws(
        self,
        *,
        det: DetectionResult,
        snapshot_id: str,
        screen_key: str,
        screenshot_path: Path,
    ) -> None:
        mode = self.ctx.settings.detection.ui_detection_mode
        log_mode = self.ctx.settings.runtime.log_mode

        def _save(kind: str, elements) -> None:
            if not elements:
                return

            out_dir = self.ctx.paths.detect[kind]
            out_path = out_dir / f"{snapshot_id}.png"

            draw_elements_on_image(
                image_path=screenshot_path,
                elements=elements,
                out_path=out_path,
                title=f"{screen_key} [{kind}]",
            )

        if log_mode == LogMode.NO_LOG:
            return

        if mode == UiDetectionMode.HYBRID:
            _save("merged", det.merged_elements or det.screen.elements)

            if log_mode == LogMode.DEBUG:
                _save("yolo", det.yolo_elements)
                _save("uiauto", det.uiauto_elements)
            return

        if mode == UiDetectionMode.YOLO:
            _save("yolo", det.screen.elements)
            return

        if mode == UiDetectionMode.UIAUTOMATOR:
            _save("uiauto", det.screen.elements)
            return