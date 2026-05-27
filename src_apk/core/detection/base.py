from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path

from core.app_types import Element
from core.detection.xml_parser import HierarchyMeta, parse_uia_xml
from core.runtime.context import RuntimeContext
from .result import DetectionResult


class BaseDetector(ABC):
    DUMP_TIMEOUT_SEC = 5.0
    # a11y가 surface 위(카메라 라이브뷰)나 시스템 다이얼로그(결제 시트)에서
    # 빈 hierarchy를 종종 준다. quiet window 직후 dump가 끼면 트리가 아직
    # 채워지지 않은 채 응답이 와서 모든 화면이 'empty_tree_*' 하나로 collapse
    # 되므로, 1회 retry로 안정성을 확보한다.
    DUMP_RETRY_ATTEMPTS = 2
    DUMP_RETRY_SLEEP_SEC = 0.4

    def __init__(self, ctx: RuntimeContext) -> None:
        self.ctx = ctx

    @abstractmethod
    def detect(self, snapshot_id: str) -> DetectionResult:
        raise NotImplementedError

    def dump_ui_xml(self, local_path: Path) -> Path | None:
        """
        APK a11y listener가 ctx에 있으면 그쪽으로 dump 받고,
        실패하거나 listener가 없으면 `uiautomator dump`로 fallback.
        """
        dumped = self._dump_via_listener(local_path)
        if dumped is not None:
            return dumped
        return self.ctx.adb_device.try_dump_ui_xml_to_file(local_path=local_path)

    def dump_and_parse_ui_xml(
        self,
        local_path: Path,
    ) -> tuple[Path | None, list[Element], HierarchyMeta, tuple[str, ...]]:
        """
        dump + parse를 한 묶음으로 처리하고, tree_signature가 비면 짧게
        기다렸다가 최대 DUMP_RETRY_ATTEMPTS 회까지 재시도한다.

        Returns:
            (dumped_xml_path, uia_elements, hierarchy_meta, tree_signature)
            마지막 시도까지 빈 트리면 마지막 attempt의 산출물(빈 elements/
            기본 meta/빈 signature)을 돌려준다 — 호출자가 screen_id fallback
            (예: HashScreenIdBuilder)으로 자연히 빠지게 둔다.
        """
        dumped_xml: Path | None = None
        uia_elements: list[Element] = []
        meta = HierarchyMeta()
        tree_signature: tuple[str, ...] = ()

        for attempt in range(1, self.DUMP_RETRY_ATTEMPTS + 1):
            dumped_xml = self.dump_ui_xml(local_path)
            if dumped_xml is not None:
                uia_elements, meta, tree_signature = parse_uia_xml(dumped_xml)
                if tree_signature:
                    return dumped_xml, uia_elements, meta, tree_signature

            if attempt < self.DUMP_RETRY_ATTEMPTS:
                if self.ctx.logger:
                    self.ctx.logger.warning(
                        f"[DUMP] empty tree "
                        f"(attempt {attempt}/{self.DUMP_RETRY_ATTEMPTS}) — retry"
                    )
                time.sleep(self.DUMP_RETRY_SLEEP_SEC)

        if self.ctx.logger:
            self.ctx.logger.warning(
                f"[DUMP] empty tree after {self.DUMP_RETRY_ATTEMPTS} attempts "
                f"→ screen_id hash fallback"
            )
        return dumped_xml, uia_elements, meta, tree_signature

    def _dump_via_listener(self, local_path: Path) -> Path | None:
        listener = getattr(self.ctx, "a11y_listener", None)
        if listener is None:
            return None

        evt = listener.request_dump_and_wait(
            timeout_sec=self.DUMP_TIMEOUT_SEC,
            pkg=self.ctx.target_package,
        )
        if evt is None or not evt.xml_path:
            if self.ctx.logger:
                self.ctx.logger.warning(
                    "[A11Y] DUMP_WRITTEN 미수신 — uiautomator dump fallback"
                )
            return None

        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self.ctx.adb_device._client.pull(  # type: ignore[attr-defined]
                evt.xml_path,
                local_path,
                timeout=30.0,
                retries=3,
                sleep_s=0.1,
            )
            return local_path
        except Exception as e:
            if self.ctx.logger:
                self.ctx.logger.warning(
                    f"[A11Y] pull 실패 ({evt.xml_path}): {e} — fallback"
                )
            return None

    def _wait_until_stable(self) -> None:
        """
        화면 렌더링이 안정될 때까지 대기 후 screencap+dump을 진행하게 한다.

        a11y listener가 흘리는 WINDOW_CONTENT_CHANGED / VIEW_SCROLLED /
        WINDOW_STATE_CHANGED 이벤트의 도착 간격을 감지해, 일정 quiet window
        동안 새 이벤트가 없으면 안정 판정. 로딩 스피너·점진 렌더링·애니메이션
        도중에 캡처가 들어가 PNG와 XML이 불일치하는 것을 막는다.

        config:
          stability_poll_interval_ms : 카운터 폴링 주기
          stability_required_matches : 연속 quiet poll 횟수
          stability_max_wait_sec     : 최대 대기 (초과 시 timeout 으로 강제 진행)
        실효 quiet window ≈ poll × matches.

        listener가 없거나 timeout > 0이 아니면 즉시 반환.
        """
        listener = getattr(self.ctx, "a11y_listener", None)
        if listener is None:
            return

        cfg = self.ctx.settings.traversal
        timeout = getattr(cfg, "stability_max_wait_sec", 0.0)
        if not timeout or timeout <= 0:
            return

        result = listener.wait_for_content_quiet(
            poll_ms=getattr(cfg, "stability_poll_interval_ms", 100),
            required_quiet_polls=getattr(cfg, "stability_required_matches", 2),
            timeout_sec=timeout,
        )

        logger = getattr(self.ctx, "logger", None)
        if logger is not None:
            logger.info(
                f"[STABLE] reason={result['reason']} "
                f"elapsed={result['elapsed_ms']:.0f}ms "
                f"events={result['events']}"
            )
