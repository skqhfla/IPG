from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import time

from core.runtime.context import RuntimeContext
from .result import DetectionResult


class BaseDetector(ABC):
    def __init__(self, ctx: RuntimeContext) -> None:
        self.ctx = ctx

    @abstractmethod
    def detect(self, snapshot_id: str) -> DetectionResult:
        raise NotImplementedError

    def _wait_until_stable(self) -> None:
        """
        screen capture 직전에 호출. WindowManager 상태가 안정될 때까지 대기.
        dumpsys window windows 출력을 주기적으로 해시하여 연속 일치 여부로 판단.
        """
        cfg = self.ctx.settings.traversal
        poll_interval = cfg.stability_poll_interval_ms / 1000.0
        max_wait = cfg.stability_max_wait_sec
        required = max(cfg.stability_required_matches, 2)

        deadline = time.monotonic() + max_wait
        last_hash: str | None = None
        matches = 0

        while True:
            try:
                output = self.ctx.adb_device.shell_text(
                    "dumpsys window windows",
                    timeout=5.0,
                    check=False,
                )
            except Exception as e:
                if self.ctx.logger:
                    self.ctx.logger.warning(
                        f"[STABILITY] probe 실패: {e}, 대기 생략"
                    )
                return

            h = hashlib.sha256(output.encode("utf-8", errors="ignore")).hexdigest()

            if h == last_hash:
                matches += 1
                if matches >= required - 1:
                    return
            else:
                last_hash = h
                matches = 0

            if time.monotonic() >= deadline:
                if self.ctx.logger:
                    self.ctx.logger.warning(
                        f"[STABILITY] step={self.ctx.step_count} "
                        f"{max_wait}s 내 안정화 실패, 캡처 진행"
                    )
                return

            time.sleep(poll_interval)
