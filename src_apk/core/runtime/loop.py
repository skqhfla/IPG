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

            if self._is_excluded(before_screen_key):
                self._handle_excluded_screen(before_screen_key, stage="before")
                return

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

        is_scroll_swipe = bool(
            action.get("type") == "swipe" and action.get("is_scroll")
        )

        # 스크롤 swipe인 경우, VIEW_SCROLLED 이벤트를 깨끗하게 받기 위해
        # swipe 직전 queue를 비운다 (다른 stale 이벤트가 끼지 않도록).
        if is_scroll_swipe and self.ctx.a11y_listener is not None:
            self.ctx.a11y_listener.clear()

        # swipe 직전 foreground (pkg, activity). swipe 후 값과 비교해
        # '화면 전환이 있었는지'를 판정한다 (refresh/scroll vs navigation 구분).
        before_fg = self.ctx.foreground_state.get()

        event_key = self.ctx.executor.execute(action)

        scrolled_progress = False
        if is_scroll_swipe:
            scrolled_progress = self._handle_scroll_feedback(
                action=action,
                before_screen_key=before_screen_key,
            )

        if self.interval_sec > 0:
            time.sleep(self.interval_sec)

        # pull-to-refresh로 의심되는 상황(맨 위에서 풀 방향으로 swipe했지만
        # 스크롤 이벤트가 없음)에서는 새로고침 스피너가 가라앉도록 추가 settle.
        if (
            is_scroll_swipe
            and not scrolled_progress
            and action.get("direction") == "up"
        ):
            time.sleep(1.0)

        after_det = self._detect_next_screen()

        # 스크롤 swipe 동안 activity 전환(WINDOW_STATE_CHANGED)이 없었다면
        # 스크롤·새로고침(pull-to-refresh)·로딩 스피너 모두 같은 화면의
        # sub-state이므로, 콘텐츠 해시가 달라져도 screen_id를 유지한다.
        # 이렇게 해야 refresh가 화면을 분절시켜 무한 새로고침 루프에 빠지지
        # 않는다 (exhausted 메모리가 같은 screen_id에 누적되어 재시도 차단).
        # 진짜 navigation은 WINDOW_STATE_CHANGED로 activity가 바뀌어 제외된다.
        # scrolled_progress(VIEW_SCROLLED 수신)는 foreground 정보가 없을 때의
        # 보조 신호.
        keep_same_screen = False
        if is_scroll_swipe and before_screen is not None:
            after_fg = self.ctx.foreground_state.get()
            activity_unchanged = (
                before_fg is not None
                and after_fg is not None
                and before_fg == after_fg
            )
            keep_same_screen = activity_unchanged or scrolled_progress

        if (
            keep_same_screen
            and before_screen is not None
            and after_det.screen.screen_id != before_screen.screen_id
        ):
            if self.ctx.logger:
                self.ctx.logger.info(
                    f"[SCROLL] same-screen 유지: "
                    f"{after_det.screen.screen_id} -> {before_screen.screen_id}"
                )
            after_det.screen.screen_id = before_screen.screen_id

        after_screen = self._register_detection(
            det=after_det,
            snapshot_id=after_det.snapshot_id,
        )
        after_screen_key = after_screen.screen_id.to_key()

        # 스크롤 swipe는 _handle_scroll_feedback에서 이미 swipe 메모리를
        # 기록하므로, executed_events 중복 기록을 피하기 위해 제외한다.
        identity_key = action.get("identity_key")
        if identity_key and not is_scroll_swipe:
            self.ctx.app_memory.mark_event_executed(
                screen_key=before_screen_key,
                identity_key=identity_key,
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

        transitioned = before_screen_key != after_screen_key

        if transitioned:
            self._record_transition(
                src_screen_key=before_screen_key,
                dst_screen_key=after_screen_key,
                event_key=event_key,
            )

            self._flush_memory()

            self.ctx.same_screen_streak = 0
        elif is_scroll_swipe and keep_same_screen:
            # 같은 화면 내 스크롤·새로고침은 stuck이 아니다 — 방향별 exhausted
            # 메모리가 종료를 보장하므로 same_screen_limit 조기 종료를 막기
            # 위해 streak을 리셋한다. 종료가 아닌 시점에도 누적 메모리를
            # 디스크에 반영한다.
            self.ctx.same_screen_streak = 0
            self._flush_memory()
        else:
            self.ctx.same_screen_streak += 1

        # 연속 스크롤 카운터: 스크롤 swipe면 +1, tap/back 등 다른 행동이면 0.
        # policy가 이 값이 상한에 닿으면 스크롤을 멈춰 무한 루프를 끊는다.
        if is_scroll_swipe:
            self.ctx.consecutive_scroll_count += 1
        else:
            self.ctx.consecutive_scroll_count = 0

        self.ctx.previous_screen = before_screen
        self.ctx.previous_screen_key = before_screen_key

        self.ctx.current_screen = after_screen
        self.ctx.current_screen_key = after_screen_key

        if self._is_excluded(after_screen_key):
            self._handle_excluded_screen(after_screen_key, stage="after")
        else:
            self.ctx.excluded_streak = 0

    # -------------------------------------------------
    # helpers
    # -------------------------------------------------

    def _handle_scroll_feedback(
        self,
        *,
        action: dict,
        before_screen_key: str,
    ) -> bool:
        """
        Scrollable element 대상 swipe 직후, VIEW_SCROLLED 이벤트를 통해
        해당 방향이 더 진행 가능한지(미고갈) / 끝까지 도달했는지(고갈) 판정해
        element 및 screen-level memory에 기록.

        Returns:
            콘텐츠가 실제로 이동했는지 여부(VIEW_SCROLLED 수신 & 미고갈).
            True이면 호출자가 '같은 화면 스크롤'로 간주해 screen_id를 유지한다.
        """
        listener = self.ctx.a11y_listener
        direction = action.get("direction")
        identity_key = action.get("identity_key")

        if not direction or not identity_key:
            return False

        # 무조건 tried 마킹 — 시도는 했으므로
        self.ctx.app_memory.mark_swipe_tried(
            screen_key=before_screen_key,
            identity_key=identity_key,
            direction=direction,
        )

        summary = None
        if listener is not None:
            timeout = self.ctx.settings.traversal.swipe_settle_ms / 1000.0
            try:
                summary = listener.wait_for_scroll_evt(timeout_sec=timeout)
            except Exception as e:
                if self.ctx.logger:
                    self.ctx.logger.warning(
                        f"[SCROLL] wait_for_scroll_evt 실패: {e}"
                    )

        evt = summary.last_evt if summary is not None else None

        exhausted = self._is_scroll_exhausted(evt=evt, direction=direction)

        if exhausted:
            self.ctx.app_memory.mark_swipe_exhausted(
                screen_key=before_screen_key,
                identity_key=identity_key,
                direction=direction,
            )
        else:
            # fling으로 한 viewport 이상 건너뛰었으면 되돌려 overlap 복원
            self._ensure_scroll_overlap(
                action=action,
                summary=summary,
                direction=direction,
            )

        if self.ctx.logger:
            d = evt.raw if evt is not None else {}
            moved = (
                f"{summary.total_dx},{summary.total_dy}"
                if summary is not None else "-"
            )
            self.ctx.logger.info(
                f"[SCROLL] screen={before_screen_key} element={identity_key} "
                f"dir={direction} exhausted={exhausted} "
                f"scroll=({d.get('scrollX')},{d.get('scrollY')}) "
                f"max=({d.get('maxScrollX')},{d.get('maxScrollY')}) "
                f"delta=({d.get('scrollDeltaX')},{d.get('scrollDeltaY')}) "
                f"moved_total=({moved}) "
                f"item=({d.get('fromIndex')}/{d.get('toIndex')}/{d.get('itemCount')})"
            )

        # VIEW_SCROLLED 수신 = 콘텐츠가 실제로 스크롤됐다는 신호.
        # 이번 swipe로 끝(exhausted)에 도달했더라도 '스크롤은 일어난 것'이므로,
        # exhausted와 무관하게 같은 화면(스크롤 sub-state)으로 간주한다.
        # (exhausted를 묶으면 짧은 리스트에서 1회 스크롤=끝 도달 시 화면이
        #  분절되어 A↔B 핑퐁 → node_loop 조기 종료가 발생함.)
        return evt is not None

    def _ensure_scroll_overlap(
        self,
        *,
        action: dict,
        summary,
        direction: str,
    ) -> None:
        """
        직전 scroll swipe가 fling으로 한 viewport(목표 전진량) 이상 이동했는지
        VIEW_SCROLLED scrollDelta 누적합으로 검사하고, overlap이 부족하면
        반대 방향으로 살짝 되돌려(back-swipe) 직전 viewport와 겹치게 한다.

        - 되돌리는 방향은 overlap을 늘리는 쪽이라, 보정이 빗나가도(추가 fling)
          gap을 만들지 않는다(항상 안전한 방향).
        - a11y가 scrollDelta를 주지 않는 뷰(측정 불가)에서는 보정하지 않고
          느린 swipe(fling 억제)의 구조적 보장에만 의존한다.
        """
        if summary is None or summary.samples == 0:
            return

        bounds = action.get("element_bounds")
        if not bounds or len(bounds) != 4:
            return

        x1, y1, x2, y2 = (int(v) for v in bounds)

        if direction in ("down", "up"):
            viewport = max(1, y2 - y1)
            moved = abs(summary.total_dy)
        else:
            viewport = max(1, x2 - x1)
            moved = abs(summary.total_dx)

        if moved == 0:
            # scrollDelta 측정 불가 → 느린 swipe의 구조적 보장에 의존
            return

        overlap_ratio = getattr(
            self.ctx.settings.traversal, "scroll_overlap_ratio", 0.3
        )
        target_advance = viewport * (1.0 - overlap_ratio)

        if moved <= target_advance:
            return  # overlap 충분

        overshoot = moved - target_advance
        # 한 번의 back-swipe로 컨테이너 안에서 표현 가능한 범위로 제한
        back_dist = int(min(overshoot, viewport * 0.8))
        if back_dist < max(8, int(viewport * 0.03)):
            return  # 무시할 만큼 작음

        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        half = back_dist // 2

        # 원래 스크롤의 반대 방향으로 되돌린다.
        if direction == "down":
            sx, sy, ex, ey = cx, cy - half, cx, cy + half
        elif direction == "up":
            sx, sy, ex, ey = cx, cy + half, cx, cy - half
        elif direction == "right":
            sx, sy, ex, ey = cx - half, cy, cx + half, cy
        else:  # left
            sx, sy, ex, ey = cx + half, cy, cx - half, cy

        duration = int(
            getattr(self.ctx.settings.traversal, "scroll_swipe_duration_ms", 800)
        )

        if self.ctx.a11y_listener is not None:
            self.ctx.a11y_listener.clear()
        self.ctx.adb_device.swipe(sx, sy, ex, ey, duration)

        if self.ctx.logger:
            self.ctx.logger.info(
                f"[SCROLL] over-scroll 보정: dir={direction} "
                f"moved={moved}px viewport={viewport}px "
                f"target_advance={int(target_advance)}px back={back_dist}px "
                f"(overlap {overlap_ratio:.0%} 복원)"
            )

    @staticmethod
    def _is_scroll_exhausted(*, evt, direction: str) -> bool:
        if evt is None:
            # VIEW_SCROLLED 이벤트 자체가 안 옴 → 스크롤 안 일어남 → 끝
            return True

        d = evt.raw
        sx = d.get("scrollX")
        sy = d.get("scrollY")
        mx = d.get("maxScrollX")
        my = d.get("maxScrollY")
        dx = d.get("scrollDeltaX")
        dy = d.get("scrollDeltaY")
        from_idx = d.get("fromIndex")
        to_idx = d.get("toIndex")
        item_count = d.get("itemCount")

        if direction == "down":
            if dy is not None and dy <= 0:
                return True
            if sy is not None and my is not None and sy >= my:
                return True
            if (
                to_idx is not None
                and item_count is not None
                and item_count > 0
                and to_idx >= item_count - 1
            ):
                return True
        elif direction == "up":
            if dy is not None and dy >= 0:
                return True
            if sy is not None and sy <= 0:
                return True
            if from_idx is not None and from_idx <= 0:
                return True
        elif direction == "right":
            if dx is not None and dx <= 0:
                return True
            if sx is not None and mx is not None and sx >= mx:
                return True
        elif direction == "left":
            if dx is not None and dx >= 0:
                return True
            if sx is not None and sx <= 0:
                return True

        return False

    def _is_excluded(self, screen_key: str) -> bool:
        return screen_key in self.ctx.excluded_screen_ids

    def _handle_excluded_screen(self, screen_key: str, *, stage: str) -> None:
        self.ctx.excluded_streak += 1
        threshold = self.ctx.settings.traversal.excluded_streak_threshold

        if self.ctx.excluded_streak >= threshold:
            if self.ctx.logger:
                self.ctx.logger.info(
                    f"[EXCLUDED] step={self.ctx.step_count} stage={stage} "
                    f"screen={screen_key} — streak={self.ctx.excluded_streak} "
                    f"임계값({threshold}) 도달, 하드 이스케이프(home + relaunch)"
                )
            self._hard_escape()
            return

        if self.ctx.logger:
            self.ctx.logger.info(
                f"[EXCLUDED] step={self.ctx.step_count} stage={stage} "
                f"screen={screen_key} — 제외 화면 도달, back 실행 "
                f"(streak={self.ctx.excluded_streak}/{threshold})"
            )
        self.ctx.adb_device.back()
        if self.interval_sec > 0:
            time.sleep(self.interval_sec)
        self.invalidate_current_screen()

    def _hard_escape(self) -> None:
        device = self.ctx.adb_device
        device.home()
        if self.interval_sec > 0:
            time.sleep(self.interval_sec)
        device.launch_app(self.ctx.target_package, self.ctx.launcher_activity)
        if self.interval_sec > 0:
            time.sleep(self.interval_sec)
        self.ctx.excluded_escape_count += 1
        self.ctx.excluded_streak = 0
        self.ctx.same_screen_streak = 0
        self.invalidate_current_screen()

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

        # AppMemory의 canonical screen 사용.
        # screen_id.threshold가 설정돼 있으면 구조 기반 매칭으로
        # 같은 화면(스크롤·로딩·탭 변종)을 하나의 screen_id로 묶는다.
        screen = self.ctx.app_memory.get_or_add_screen(
            detected_screen,
            match_threshold=getattr(
                self.ctx.settings.screen_id, "match_threshold", 0.0
            ),
        )
        screen_key = screen.screen_id.to_key()

        self.ctx.app_memory.add_snapshot(screen_key, snapshot_id)

        self.ctx.screen_visit_count[screen_key] = (
            self.ctx.screen_visit_count.get(screen_key, 0) + 1
        )
        # 연속 중복(같은 화면을 스크롤하며 머무는 경우 등)은 history에 쌓지
        # 않는다. node-loop 탐지는 '화면 전환' 패턴을 보는 것이므로 연속된
        # distinct screen만 의미가 있다 (같은 화면 정체는 same_screen_streak가 담당).
        if (
            not self.ctx.screen_history
            or self.ctx.screen_history[-1] != screen_key
        ):
            self.ctx.screen_history.append(screen_key)

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

    def _flush_memory(self) -> None:
        """
        transition 발생 시점에 app_memory / screen_memory를 디스크에 즉시 반영.
        runner.finalize()의 종료 flush와 별개로, 도중 비정상 종료 시에도
        최신 transition 기준 상태가 남도록 한다.
        """
        saver = getattr(self.ctx, "memory_saver", None)
        if saver is None:
            return
        try:
            saver.save_app_memory(self.ctx.app_memory)
            saver.save_screen_memory(self.ctx.screen_memory)
        except Exception as e:
            if self.ctx.logger:
                self.ctx.logger.warning(f"[MEMORY] incremental flush 실패: {e}")

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
