from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from core.runtime.context import RuntimeContext
from .result import DetectionResult


class BaseDetector(ABC):
    DUMP_TIMEOUT_SEC = 5.0

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
        APK 기반 프레임워크에서는 a11y service가 CONTENT_DEBOUNCE_MS로 자체
        디바운싱을 하고, loop.interval_sec가 추가 sleep을 제공한다. dumpsys
        polling은 불필요.
        """
        return
