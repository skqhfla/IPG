from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from core.adb.client import ADBClient
from core.runtime.monitor.foreground_monitor import ForegroundState


@dataclass(frozen=True, slots=True)
class A11yEvent:
    ts: int                  # device epoch ms (APK가 emit한 JSON.ts)
    type: str                # SERVICE_CONNECTED / WINDOW_STATE_CHANGED / DUMP_WRITTEN / ...
    pkg: str
    session: Optional[str]
    xml_path: Optional[str]  # DUMP_WRITTEN에서만 채워짐. device-side absolute path.
    raw: dict


@dataclass(frozen=True, slots=True)
class ScrollSummary:
    """
    단일 swipe 제스처 동안 수집한 VIEW_SCROLLED 이벤트 요약.

    last_evt   : 마지막 VIEW_SCROLLED (최종 scroll 위치 판정용)
    total_dx/dy: 모든 VIEW_SCROLLED의 scrollDelta 누적합(부호 포함)
                 = 이번 swipe로 콘텐츠가 총 이동한 양 → overlap 판정에 사용
    samples    : 수신한 VIEW_SCROLLED 이벤트 수 (0이면 미수신)
    delta_measured: scrollDelta 값이 하나라도 유효했는가
    """
    last_evt: Optional["A11yEvent"]
    total_dx: int
    total_dy: int
    samples: int
    delta_measured: bool

    @property
    def received(self) -> bool:
        return self.last_evt is not None


class A11yServiceUnavailable(RuntimeError):
    """device_listener APK 미설치 / 접근성 OFF / 서비스 미응답 시 발생."""


class A11yEventListener:
    """
    device_listener APK가 logcat tag `IPG_EVT`로 흘리는 JSON 이벤트를
    백그라운드 스레드로 수신·파싱해 queue에 누적한다.

    `request_dump_and_wait()`는 broadcast 전송 + 다음 DUMP_WRITTEN 수신을
    한 호출로 묶는다 (clear → broadcast → wait).
    """

    TAG = "IPG_EVT"
    BROADCAST_ACTION = "dev.ipg.listener.DUMP_NOW"
    LISTENER_PACKAGE = "dev.ipg.listener"
    A11Y_COMPONENT = "dev.ipg.listener/.IpgAccessibilityService"
    VERIFY_PROBE_TIMEOUT_SEC = 5.0

    def __init__(
        self,
        *,
        client: ADBClient,
        logger: Any = None,
        foreground_state: ForegroundState | None = None,
        target_package: str | None = None,
    ) -> None:
        self._client = client
        self._logger = logger
        self._foreground_state = foreground_state
        self._target_package = target_package
        self._queue: queue.Queue[A11yEvent] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc = None

    # -----------------------------
    # lifecycle
    # -----------------------------

    def start(self) -> None:
        if self._thread is not None:
            return

        # -v raw: 메시지 본문(JSON)만 출력. -T 1: 시작 시점 이후 라인만.
        self._proc = self._client.popen(
            ["logcat", "-s", f"{self.TAG}:I", "-v", "raw", "-T", "1"],
        )

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="a11y-evt-listener",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # -----------------------------
    # queue ops
    # -----------------------------

    def clear(self) -> None:
        with self._queue.mutex:
            self._queue.queue.clear()

    def wait_for(
        self,
        *,
        type_filter: tuple[str, ...],
        timeout_sec: float,
    ) -> Optional[A11yEvent]:
        deadline = time.monotonic() + timeout_sec
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                evt = self._queue.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if evt.type in type_filter:
                return evt

    def wait_for_scroll_evt(
        self,
        *,
        timeout_sec: float,
        settle_sec: float = 0.15,
    ) -> ScrollSummary:
        """
        swipe 후 VIEW_SCROLLED 이벤트를 수집해 ScrollSummary로 반환.

        - RecyclerView 등은 단일 swipe(특히 fling)에 여러 VIEW_SCROLLED를
          연속 emit하므로, 마지막 이벤트(최종 위치)와 함께 모든 이벤트의
          scrollDelta 누적합(= 이번 swipe로 이동한 총량)을 함께 모은다.
          누적합은 overlap 보장 판정(한 viewport 이상 건너뛰었는지)에 쓰인다.
        - timeout_sec 안에 첫 이벤트가 안 오면 samples=0.
        - 첫 이벤트 수신 후 settle_sec 동안 추가 이벤트가 없으면 종료.
        """
        deadline = time.monotonic() + timeout_sec
        last_evt: Optional[A11yEvent] = None
        total_dx = 0
        total_dy = 0
        samples = 0
        delta_measured = False

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            # 첫 이벤트 전: 전체 timeout 까지 / 이후: settle_sec 안에 새 이벤트 없으면 종료
            wait = min(remaining, 0.5 if last_evt is None else settle_sec)

            try:
                evt = self._queue.get(timeout=wait)
            except queue.Empty:
                if last_evt is not None:
                    break
                continue

            if evt.type != "VIEW_SCROLLED":
                continue

            last_evt = evt
            samples += 1

            dx = evt.raw.get("scrollDeltaX")
            dy = evt.raw.get("scrollDeltaY")
            if isinstance(dx, (int, float)):
                total_dx += int(dx)
                delta_measured = True
            if isinstance(dy, (int, float)):
                total_dy += int(dy)
                delta_measured = True

        return ScrollSummary(
            last_evt=last_evt,
            total_dx=total_dx,
            total_dy=total_dy,
            samples=samples,
            delta_measured=delta_measured,
        )

    # -----------------------------
    # availability check
    # -----------------------------

    def verify_available(self) -> None:
        """
        device_listener APK가 설치돼 있고 접근성 서비스가 활성·응답 가능한지 검증.
        세 단계 모두 통과해야 None 반환, 아니면 A11yServiceUnavailable 발생.
        """
        if not self._is_package_installed():
            raise A11yServiceUnavailable(
                f"device_listener APK가 단말에 설치돼 있지 않음 "
                f"({self.LISTENER_PACKAGE}). "
                f"`device_listener/` 빌드 후 `adb install -r`로 설치하세요."
            )

        if not self._is_a11y_enabled():
            raise A11yServiceUnavailable(
                "접근성 서비스가 활성화돼 있지 않음. "
                "단말: 설정 → 접근성 → IPG Listener → 사용. "
                f"(컴포넌트: {self.A11Y_COMPONENT})"
            )

        evt = self.request_dump_and_wait(timeout_sec=self.VERIFY_PROBE_TIMEOUT_SEC)
        if evt is None or not evt.xml_path:
            raise A11yServiceUnavailable(
                f"DUMP_NOW broadcast에 {self.VERIFY_PROBE_TIMEOUT_SEC}s 내 "
                "응답 없음. APK 설치·접근성 ON 상태지만 서비스가 살아있지 "
                "않거나 logcat 권한 문제일 수 있음."
            )

        if self._logger:
            self._logger.info(
                f"[A11Y] verified: pkg={self.LISTENER_PACKAGE}, "
                f"probe_xml={evt.xml_path}"
            )

    def _is_package_installed(self) -> bool:
        try:
            out = self._client.shell_text(
                f"pm path {self.LISTENER_PACKAGE}",
                check=False,
                timeout=5.0,
            ).strip()
        except Exception:
            return False
        return out.startswith("package:")

    def _is_a11y_enabled(self) -> bool:
        try:
            enabled = self._client.shell_text(
                "settings get secure accessibility_enabled",
                check=False,
                timeout=5.0,
            ).strip()
            if enabled != "1":
                return False

            services = self._client.shell_text(
                "settings get secure enabled_accessibility_services",
                check=False,
                timeout=5.0,
            ).strip()
        except Exception:
            return False

        if not services or services.lower() == "null":
            return False

        for entry in services.split(":"):
            if self._matches_component(entry.strip()):
                return True
        return False

    def _matches_component(self, entry: str) -> bool:
        if not entry:
            return False
        # 정규형 `pkg/.Class` 와 `pkg/pkg.Class` 모두 매칭
        return entry == self.A11Y_COMPONENT or entry.startswith(
            f"{self.LISTENER_PACKAGE}/"
        )

    # -----------------------------
    # request-response helper
    # -----------------------------

    def request_dump_and_wait(
        self,
        *,
        timeout_sec: float = 5.0,
        pkg: Optional[str] = None,
    ) -> Optional[A11yEvent]:
        """
        DUMP_NOW broadcast 전송 후 다음 DUMP_WRITTEN 수신.
        broadcast 직전 queue를 clear하므로 stale event 매칭은 없다.
        """
        self.clear()

        cmd = f"am broadcast -a {self.BROADCAST_ACTION}"
        if pkg is not None:
            cmd += f" --es pkg {pkg}"
        try:
            self._client.shell_text(cmd, check=False, timeout=5.0)
        except Exception as e:
            if self._logger:
                self._logger.warning(f"[A11Y] broadcast failed: {e}")
            return None

        return self.wait_for(
            type_filter=("DUMP_WRITTEN",),
            timeout_sec=timeout_sec,
        )

    # -----------------------------
    # background reader
    # -----------------------------

    def _run(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return

        for line in proc.stdout:
            if self._stop.is_set():
                break

            text = line.strip()
            if not text or not text.startswith("{"):
                continue

            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue

            evt = A11yEvent(
                ts=int(payload.get("ts", 0)),
                type=str(payload.get("type", "")),
                pkg=str(payload.get("pkg", "")),
                session=payload.get("session"),
                xml_path=payload.get("xml"),
                raw=payload,
            )

            if (
                evt.type == "WINDOW_STATE_CHANGED"
                and self._foreground_state is not None
                and evt.pkg
            ):
                cls = str(payload.get("class", ""))
                self._foreground_state.update(
                    evt.pkg,
                    cls,
                    target_package=self._target_package,
                )

            self._log_event(evt)

            try:
                self._queue.put_nowait(evt)
            except queue.Full:
                pass

    def _log_event(self, evt: A11yEvent) -> None:
        if self._logger is None:
            return

        p = evt.raw
        parts = [f"type={evt.type}"]

        if evt.pkg:
            parts.append(f"pkg={evt.pkg}")

        cls = p.get("class")
        if cls:
            parts.append(f"class={cls}")

        text = p.get("text")
        if text:
            parts.append(f"text={text!r}")

        if evt.type == "WINDOW_CONTENT_CHANGED":
            change = p.get("change")
            if change:
                parts.append(f"change={change}")

        elif evt.type == "VIEW_SCROLLED":
            sx = p.get("scrollX")
            sy = p.get("scrollY")
            if sx is not None or sy is not None:
                parts.append(f"scroll=({sx},{sy})")
            dx = p.get("scrollDeltaX")
            dy = p.get("scrollDeltaY")
            if dx is not None or dy is not None:
                parts.append(f"delta=({dx},{dy})")

        elif evt.type == "DUMP_WRITTEN":
            seq = p.get("seq")
            if seq is not None:
                parts.append(f"seq={seq}")
            trigger = p.get("trigger")
            if trigger:
                parts.append(f"trigger={trigger}")
            if evt.xml_path:
                parts.append(f"xml={evt.xml_path}")

        elif evt.type == "SERVICE_CONNECTED":
            api = p.get("apiLevel")
            if api is not None:
                parts.append(f"api={api}")
            mode = p.get("screenshotMode")
            if mode:
                parts.append(f"screenshotMode={mode}")

        src = p.get("source")
        if isinstance(src, dict):
            src_bits = []
            rid = src.get("resourceId")
            if rid:
                src_bits.append(f"rid={rid}")
            scls = src.get("class")
            if scls:
                src_bits.append(f"src_class={scls}")
            stxt = src.get("text")
            if stxt:
                src_bits.append(f"src_text={stxt!r}")
            if src_bits:
                parts.append(" ".join(src_bits))

        self._logger.info("[A11Y] " + " ".join(parts))
