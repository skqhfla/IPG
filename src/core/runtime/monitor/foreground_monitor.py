from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple, Any

from core.adb.device import ADBDevice


@dataclass
class ForegroundState:
    """
    watcher가 foreground 상태를 업데이트하면
    RuntimeLoop / Traverser에서 참조할 수 있음.
    """

    _lock: threading.Lock = field(default_factory=threading.Lock)

    _last: Optional[Tuple[str, str]] = None
    _last_ts: float = 0.0

    _is_target: bool = False
    _mismatch_since: Optional[float] = None

    def update(self, pkg: str, act: str, *, target_package: Optional[str] = None) -> None:
        now = time.time()

        with self._lock:
            self._last = (pkg, act)
            self._last_ts = now

            if target_package is None:
                return

            is_target = (pkg == target_package)

            if is_target:
                self._mismatch_since = None
            else:
                if self._is_target:
                    self._mismatch_since = now
                elif self._mismatch_since is None:
                    self._mismatch_since = now

            self._is_target = is_target

    def get(self) -> Optional[Tuple[str, str]]:
        with self._lock:
            return self._last

    def get_with_ts(self) -> Tuple[Optional[Tuple[str, str]], float]:
        with self._lock:
            return self._last, self._last_ts

    def is_target_app(self) -> bool:
        with self._lock:
            return self._is_target

    def mismatch_duration(self) -> float:
        with self._lock:
            if self._is_target or self._mismatch_since is None:
                return 0.0
            return time.time() - self._mismatch_since


def start_foreground_watcher(
    *,
    device: ADBDevice,
    stop_event: threading.Event,
    poll_interval: float = 0.5,
    logger: Optional[Any] = None,
    state: Optional[ForegroundState] = None,
    target_package: Optional[str] = None,
) -> threading.Thread:
    """
    foreground watcher thread

    기능:
    - foreground package/activity polling
    - ForegroundState 업데이트
    """
    poll_interval = max(0.1, float(poll_interval))

    def worker() -> None:
        last: Optional[Tuple[str, str]] = None

        while not stop_event.is_set():
            try:
                parsed = device.get_foreground_app()

                if parsed:
                    pkg, act = parsed

                    if state is not None:
                        state.update(pkg, act, target_package=target_package)

                    if parsed != last:
                        last = parsed

                        if logger:
                            logger.debug(
                                f"[FG] {pkg}/{act} "
                                f"(target={pkg == target_package if target_package else None})"
                            )

            except Exception as e:
                if logger:
                    logger.warning(f"[FG_WATCHER] error: {e!r}")

            stop_event.wait(poll_interval)

    t = threading.Thread(
        target=worker,
        name="foreground-watcher",
        daemon=True,
    )
    t.start()
    return t