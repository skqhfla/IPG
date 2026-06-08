from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
import time
from pathlib import Path

from core.adb.netstats import PacketStat
from core.app_types import EventType, Screen, ScreenID
from core.detection.result import DetectionResult
from core.detection.draw import draw_elements_on_image
from core.graph.recover_graph import RecoverEvent
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
        self.packet_capture_time = ctx.settings.packet.capture_time_sec
        self.packet_threshold = ctx.settings.packet.packet_threshold

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

            if not self._is_target_screen(before_det.screen):
                # 비-타겟 화면(런처/시스템 다이얼로그/외부 앱)은 app_memory에
                # 절대 등록하지 않는다. 등록 시 screen_id/transition/element가
                # target 앱 데이터에 섞여 영구 contamination이 된다.
                self._handle_non_target_screen(
                    snapshot_id=before_det.snapshot_id,
                    screen=before_det.screen,
                    stage="before",
                )
                return

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
            self.ctx.current_snapshot_id = before_det.snapshot_id
        else:
            before_det = None
            before_screen = self.ctx.current_screen
            before_screen_key = self.ctx.current_screen_key

        assert before_screen is not None
        assert before_screen_key is not None
        # 이벤트는 이 시점 화면(snapshot) 위에서 실행되므로, packet 측정의
        # 귀속 단위로 before_snapshot_id를 잡아 둔다.
        before_snapshot_id = self.ctx.current_snapshot_id

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

        # 이벤트 직전 UID 패킷 누적치 snapshot. capture_time_sec 후 다시 찍어
        # 차분을 packet_memory에 기록한다 (None이면 측정 비활성).
        before_stat = (
            self.ctx.netstats_sampler.sample()
            if self.ctx.netstats_sampler is not None
            else None
        )

        event_key = self.ctx.executor.execute(action)

        scrolled_progress = False
        if is_scroll_swipe:
            scrolled_progress = self._handle_scroll_feedback(
                action=action,
                before_screen_key=before_screen_key,
            )

        # 패킷 측정 윈도우. interval_sec 대신 capture_time_sec 사용.
        if self.packet_capture_time > 0:
            time.sleep(self.packet_capture_time)

        self._record_packet_delta(
            screen_key=before_screen_key,
            snapshot_id=before_snapshot_id,
            event_key=event_key,
            before=before_stat,
        )

        # pull-to-refresh로 의심되는 상황(맨 위에서 풀 방향으로 swipe했지만
        # 스크롤 이벤트가 없음)에서는 새로고침 스피너가 가라앉도록 추가 settle.
        if (
            is_scroll_swipe
            and not scrolled_progress
            and action.get("direction") == "up"
        ):
            time.sleep(1.0)

        # tap 이 IME(소프트 키보드)를 띄운 경우: 다음 element 시도를 위해 BACK 으로
        # 닫는다. element 본인은 이미 "실행됨" 으로 마킹되므로 (라인 ~196 의
        # mark_event_executed) 다음 iteration 의 정책이 같은 element 를 다시 고르지
        # 않는다 — 자연스럽게 다른 trigger 로 넘어감. BACK 한 번은 안드로이드 표준
        # 동작상 IME 만 닫고 activity stack 은 보존됨.
        # 1차 신호: listener 가 emit 한 IME_VISIBLE/HIDDEN 으로 캐시된 상태(0 cost).
        # 2차 폴백: 구 listener 또는 listener 없는 환경 → dumpsys input_method (~400ms).
        if action.get("type") == "tap":
            ime_visible = False
            if self.ctx.a11y_listener is not None:
                ime_visible = self.ctx.a11y_listener.is_ime_visible()
            if not ime_visible and self.ctx.a11y_listener is None:
                # listener 자체가 없는 경우만 dumpsys 폴백 — 있으면 신뢰
                ime_visible = self.ctx.adb_device.is_ime_visible()
            if ime_visible:
                if self.ctx.logger:
                    self.ctx.logger.info(
                        f"[KEYBOARD] screen={before_screen_key} "
                        f"element_id={action.get('element_id')} "
                        f"identity={action.get('identity_key')!r} "
                        f"text={action.get('element_text')!r} "
                        f"→ IME opened, mark executed + dismiss (BACK)"
                    )
                self.ctx.adb_device.back()
                # IME dismiss 애니메이션 + 콘텐츠 reflow 시간 — 너무 짧으면 다음 dump 에
                # IME 가 아직 일부 잡혀 element bbox 가 viewport 안에 fit 안 됨.
                time.sleep(0.5)

        after_det = self._detect_next_screen()

        if not self._is_target_screen(after_det.screen):
            # 이벤트는 이미 실행됐고 packet도 측정됐다 — 그건 그대로 두고,
            # 비-타겟 화면을 app_memory/screen_memory/utg에 등록하지 않는다.
            # before_screen의 element는 'executed'로 마킹해 다음 라운드에서
            # 같은 액션을 다시 골라 같은 외부 화면으로 빠지는 걸 막는다
            # (scroll swipe는 _handle_scroll_feedback이 이미 tried 마킹).
            identity_key = action.get("identity_key")
            if identity_key and not is_scroll_swipe:
                self.ctx.app_memory.mark_event_executed(
                    screen_key=before_screen_key,
                    identity_key=identity_key,
                    event_key=event_key,
                )
            self._flush_memory()
            self._handle_non_target_screen(
                snapshot_id=after_det.snapshot_id,
                screen=after_det.screen,
                stage="after",
                src_screen_key=before_screen_key,
                src_snapshot_id=before_snapshot_id,
                src_event_key=event_key,
            )
            return

        # 스크롤 swipe 후엔 viewport가 바뀌었다고 보고 별도 screen_id로
        # 분리한다 — 같은 activity 안이라도 visible content가 달라지므로
        # 다른 화면. visible-only tree_signature 매처가 같은 viewport
        # 재방문은 자동으로 같은 screen_id로 묶어 무한 새로고침 루프도
        # 차단된다(refresh 후 visible 구성은 동일).
        #
        # gate_reuse(transition_seq + identity 검사)는 VIEW_SCROLLED를
        # transition 신호로 보지 않으므로 스크롤 후에도 reuse=True가
        # 잡혀 직전 screen_id를 그대로 재사용해버린다 → 강제로 무력화.
        after_screen = self._register_detection(
            det=after_det,
            snapshot_id=after_det.snapshot_id,
            force_match=is_scroll_swipe,
        )
        after_screen_key = after_screen.screen_id.to_key()
        # 다음 step의 before_snapshot_id가 될 값을 미리 저장한다.
        self.ctx.current_snapshot_id = after_det.snapshot_id

        # 스크롤로 도달한 새 viewport는 직전 viewport의 executed_events 를
        # identity_key 매칭으로 상속받아, overlap 영역의 중복 탭을 막는다.
        # swipe 방향 마크는 상속하지 않는다 — 각 viewport 는 자신의 스크롤
        # 가능성을 독립적으로 판단해야 한다.
        if (
            is_scroll_swipe
            and before_screen is not None
            and before_screen_key != after_screen_key
        ):
            self.ctx.app_memory.inherit_executed_from(
                dst_screen_key=after_screen_key,
                src_screen_key=before_screen_key,
            )

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
        else:
            # transition 없음 = 같은 viewport 재방문(스크롤이 헛돌아 같은 화면
            # 으로 매처가 묶거나, tap이 화면 안 바꿨음). stuck 카운터 증가 —
            # same_screen_limit 도달 시 정책이 back/escape 트리거.
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

    def _record_packet_delta(
        self,
        *,
        screen_key: str,
        snapshot_id: str | None,
        event_key: str,
        before: PacketStat | None,
    ) -> None:
        sampler = self.ctx.netstats_sampler
        if sampler is None or before is None:
            return

        after = sampler.sample()
        if after is None:
            return

        delta = after.delta(before)
        if delta.total_packets() < self.packet_threshold:
            return

        self.ctx.packet_memory.add_event(
            screen_key=screen_key,
            snapshot_id=snapshot_id,
            event_key=event_key,
            stat=delta,
        )

        if self.ctx.logger:
            self.ctx.logger.info(
                f"[PACKET] screen={screen_key} snapshot={snapshot_id or '-'} "
                f"event={event_key} "
                f"tx_pkts={delta.tx_packets} rx_pkts={delta.rx_packets} "
                f"tx_bytes={delta.tx_bytes} rx_bytes={delta.rx_bytes}"
            )

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

        스크롤 후 screen_id 는 _register_detection(force_match=True) 가
        viewport 단위로 분리해 부여하므로, 여기서는 swipe 방향 마크와
        overlap 보정만 담당한다.

        Returns: scrolled_progress — VIEW_SCROLLED 수신 여부. 호출자가
        pull-to-refresh 스피너 settle 같은 후처리 분기에 쓴다.
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
    def _multiset_jaccard(
        a: tuple[str, ...],
        b: tuple[str, ...],
    ) -> float:
        ca = Counter(a)
        cb = Counter(b)
        keys = set(ca) | set(cb)
        inter = sum(min(ca[k], cb[k]) for k in keys)
        union = sum(max(ca[k], cb[k]) for k in keys)
        return inter / union if union else 0.0

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

    def _is_target_screen(self, screen: Screen) -> bool:
        """
        Detection 결과의 <hierarchy package=...>가 타겟 앱과 일치하는가.

        - package 속성이 비어 있는 구버전 dump / YOLO-only 화면은 검증할 근거가
          없으므로 permissive하게 True를 반환한다 (회귀 방지).
        - target_package가 비어 있으면 게이팅이 꺼진 상태로 간주.
        """
        target = self.ctx.target_package
        pkg = screen.package
        if not target or not pkg:
            return True
        return pkg == target

    def _handle_non_target_screen(
        self,
        *,
        snapshot_id: str,
        screen: Screen,
        stage: str,
        src_screen_key: str | None = None,
        src_snapshot_id: str | None = None,
        src_event_key: str | None = None,
    ) -> None:
        """
        타겟 외 화면이 dump됐을 때의 핸들러.
        - app_memory/screen_memory/utg에 등록하지 않는다.
        - foreground_state의 1초 임계를 우회해 즉시 recover를 강제한다 —
          A11y가 WINDOW_STATE_CHANGED를 놓쳐 state가 stale일 수 있기 때문.
        - 이벤트는 ctx.recover_graph에 기록되며, dst 화면은 다음 target detection
          성공 시점에 _register_detection이 채운다.
        """
        if self.ctx.logger:
            self.ctx.logger.warning(
                f"[GATE] non-target screen detected: stage={stage} "
                f"snapshot={snapshot_id} pkg={screen.package!r} "
                f"activity={screen.activity!r} target={self.ctx.target_package} — "
                f"skip registration + force recover"
            )

        event = RecoverEvent(
            step=self.ctx.step_count,
            timestamp=datetime.now(timezone.utc).isoformat(),
            stage=stage,
            snapshot_id=snapshot_id,
            non_target_package=screen.package,
            non_target_activity=screen.activity,
            src_screen_key=src_screen_key,
            src_snapshot_id=src_snapshot_id,
            src_event_key=src_event_key,
        )
        self.ctx.recover_graph.add(event)

        method, recovered = self._force_recover_to_target()
        event.recover_method = method
        event.recovered_to_target = recovered

        self.invalidate_current_screen()

    # 비-타겟 화면에서 BACK으로 dismiss를 시도할 때의 최대 횟수.
    # 1~2회면 대부분의 permission/popup/외부 앱 deep-link가 닫히고 직전
    # 타겟 화면으로 돌아간다 — 너무 많이 누르면 타겟 앱 stack도 pop되어
    # main 또는 종료로 빠지므로 작게 잡는다.
    BACK_RECOVER_MAX_PRESSES = 2
    BACK_RECOVER_SETTLE_SEC = 0.6

    def _force_recover_to_target(self) -> tuple[str, bool]:
        """
        비-타겟 화면에서 타겟으로 복귀. 단계적 escalation:
          1) BACK 1~2회 (popup/dialog/외부 deep-link dismiss)
             → 직전 타겟 deep 화면을 그대로 살릴 수 있다
          2) bring_to_front (home + LAUNCHER intent)
             → stack을 main으로 리셋하지만 프로세스는 유지
          3) launch_app (force-stop + relaunch)
             → 마지막 수단, 앱 상태 전부 리셋

        Returns:
            (method, recovered_to_target)
            method: 'back' | 'bring_to_front' | 'launch_app'
        """
        device = self.ctx.adb_device
        target = self.ctx.target_package
        current_pkg = ""

        # 1) BACK escalation — popup/dialog/외부 앱은 보통 1~2회로 닫힌다.
        for i in range(self.BACK_RECOVER_MAX_PRESSES):
            device.back()
            time.sleep(self.BACK_RECOVER_SETTLE_SEC)
            current_pkg = device.get_foreground_package()
            if current_pkg == target:
                if self.ctx.logger:
                    self.ctx.logger.info(
                        f"[RECOVER:FORCE] back ×{i + 1} → target restored"
                    )
                # back으로 복귀하면 stack 손실이 없으므로 recover_count는
                # 올리지 않는다 (이 카운터는 'main으로 리셋된 횟수'에 한정).
                return "back", True

        if self.ctx.logger and self.BACK_RECOVER_MAX_PRESSES > 0:
            self.ctx.logger.warning(
                f"[RECOVER:FORCE] back ×{self.BACK_RECOVER_MAX_PRESSES} 실패 "
                f"(current={current_pkg!r}), bring_to_front 진행"
            )

        # 2) bring_to_front — stack을 main으로 리셋.
        device.bring_to_front(target, self.ctx.launcher_activity)
        self.ctx.foreground_recover_count += 1
        time.sleep(1.0)

        after_soft = device.get_foreground_package()
        if after_soft == target:
            if self.ctx.logger:
                self.ctx.logger.info("[RECOVER:FORCE] bring_to_front success")
            return "bring_to_front", True

        if self.ctx.logger:
            self.ctx.logger.warning(
                f"[RECOVER:FORCE] bring_to_front failed: current={after_soft}, "
                f"target={target}. restarting app."
            )

        # 3) 마지막 수단 — 프로세스 재시작.
        device.launch_app(target, self.ctx.launcher_activity)
        self.ctx.app_restart_count += 1
        time.sleep(1.0)

        after_hard = device.get_foreground_package()
        return "launch_app", (after_hard == target)

    def _recover_if_needed(self) -> None:
        state = self.ctx.foreground_state
        target = self.ctx.target_package

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

        # _force_recover_to_target과 동일한 단계적 전략 (BACK → bring_to_front
        # → launch_app). BACK이 성공하면 타겟 stack을 보존한 채 복귀하므로
        # main으로 강제 리셋되는 것을 피한다.
        method, recovered = self._force_recover_to_target()
        self.invalidate_current_screen()
        if self.ctx.logger and recovered:
            self.ctx.logger.info(f"[RECOVER] success via {method}")

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
        force_match: bool = False,
    ) -> Screen:
        """
        force_match=True 면 gate_reuse 를 우회하고 항상 visible-only
        tree_signature 매처를 돌린다. 호출자가 직전 swipe 가 스크롤이라
        viewport 가 바뀌었다는 사실을 알 때 사용 — VIEW_SCROLLED 는
        transition_seq 에 잡히지 않아 gate_reuse=True 가 잡혀 직전
        screen_id 가 그대로 재사용되는 회귀를 막는다.
        """
        detected_screen = det.screen

        # ── transition 게이트 ─────────────────────────────────────────────
        # 1차 신호: listener 의 transition_seq (WINDOW_STATE_CHANGED /
        #            VIEW_SELECTED / WINDOWS_CHANGED-top-level).
        # 2차 방어선: XML 의 identity 속성(activity/window_id/rotation/package).
        #            host logcat 이 고부하 시 STATE_CHANGED 라인을 드롭해
        #            trans_seq 가 안 늘어나는 케이스가 실제로 관측됨
        #            (20260601_160453 의 89~93 = Main↔HomeMember↔HomeEditor
        #            오실레이션). APK 의 lastWindowClass 는 dump 시점 값이라
        #            logcat 손실과 무관하게 정확 → 직전 activity 와 다르면
        #            게이트 강제 해제 + 매처 호출.
        configured_thr = getattr(
            self.ctx.settings.screen_id, "match_threshold", 0.0
        )
        listener = getattr(self.ctx, "a11y_listener", None)
        cur_trans_seq = listener.transition_seq() if listener is not None else 0
        prev_screen_value = self.ctx.last_screen_id_value

        identity_changed = (
            (detected_screen.activity or None) != self.ctx.last_activity
            or (detected_screen.package or None) != self.ctx.last_package
            or (detected_screen.rotation or 0) != self.ctx.last_rotation
            or detected_screen.window_id != self.ctx.last_window_id
        )
        # 4속성이 모두 같아도 본문 fragment가 통째로 교체된 케이스(Xiaomi 하단
        # 탭 전환처럼 STATE_CHANGED/SELECTED 이벤트가 안 떠 trans_seq·identity
        # 모두 변화 없음)는 직전과 visible-only tree_signature Jaccard로
        # 분리한다. 임계 미만이면 게이트 해제 → 매처가 정상 호출되어 새
        # screen_id 가 부여된다. 직전/현재 signature가 비면(빈 트리 retry 실패
        # 등) 비교 자체를 건너뛰고 기존 게이트 정책 그대로.
        content_diverged = False
        if (
            prev_screen_value is not None
            and self.ctx.last_tree_signature
            and detected_screen.tree_signature
        ):
            sim = self._multiset_jaccard(
                self.ctx.last_tree_signature,
                detected_screen.tree_signature,
            )
            if sim < configured_thr:
                content_diverged = True

        gate_reuse = (
            not force_match
            and prev_screen_value is not None
            and cur_trans_seq == self.ctx.last_transition_seq
            and not identity_changed
            and not content_diverged
        )

        if gate_reuse:
            # 같은 화면 — 직전 screen_id 그대로 재사용. element 메모리는 새
            # detection 결과로 갱신되게 둔다.
            detected_screen.screen_id = ScreenID(value=prev_screen_value)
            effective_thr = 0.0
        else:
            # 첫 detection 이거나 transition 신호(이벤트 카운터 증가 OR
            # XML identity 변화) 발생 → 매처가 (package, activity, rotation)
            # 버킷에서 Jaccard 로 같은 화면 후보 검색. 다른 activity 가 같은
            # screen_id 로 잘못 합쳐지는 회귀 차단.
            effective_thr = configured_thr

        screen = self.ctx.app_memory.get_or_add_screen(
            detected_screen,
            match_threshold=effective_thr,
        )
        screen_key = screen.screen_id.to_key()
        self.ctx.last_screen_id_value = screen_key
        self.ctx.last_transition_seq = cur_trans_seq
        self.ctx.last_activity = detected_screen.activity or None
        self.ctx.last_package = detected_screen.package or None
        self.ctx.last_rotation = detected_screen.rotation or 0
        self.ctx.last_window_id = detected_screen.window_id
        self.ctx.last_tree_signature = detected_screen.tree_signature
        # ──────────────────────────────────────────────────────────────────

        # 직전 force-recover 이벤트의 dst를 첫 target detection 시점에 채운다.
        pending = self.ctx.recover_graph.last_pending()
        if pending is not None:
            pending.dst_screen_key = screen_key
            pending.dst_snapshot_id = snapshot_id

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
        transition 발생 시점에 메모리를 디스크에 즉시 반영. runner.finalize()의
        종료 flush와 별개로, 도중 비정상 종료 시에도 최신 transition 기준
        상태가 남도록 한다.
        """
        saver = getattr(self.ctx, "memory_saver", None)
        if saver is None:
            return
        try:
            saver.save_app_memory(self.ctx.app_memory)
            saver.save_screen_memory(self.ctx.screen_memory)
            saver.save_packet_memory(self.ctx.packet_memory)
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
