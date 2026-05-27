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
    """device_listener APK(main+test) 미설치 또는 instrumentation 미응답 시 발생."""


class A11yEventListener:
    """
    device_listener instrumentation 을 `am instrument -w` 로 띄우고,
    logcat tag `IPG_EVT` 로 흘리는 JSON 이벤트를 백그라운드 스레드로
    수신·파싱해 queue 에 누적한다.

    `request_dump_and_wait()` 는 sentinel 파일을 touch 해서 instrumentation 의
    polling loop 를 깨우고 다음 DUMP_WRITTEN 을 기다린다 (clear → touch → wait).
    """

    TAG = "IPG_EVT"
    LISTENER_PACKAGE = "dev.ipg.listener"
    TEST_PACKAGE = "dev.ipg.listener.test"
    TEST_RUNNER = "dev.ipg.listener.test/androidx.test.runner.AndroidJUnitRunner"
    TEST_CLASS = "dev.ipg.listener.IpgInstrumentationTest#run"
    # device-side path the instrumentation polls (also surfaced in SERVICE_CONNECTED.triggerFile)
    TRIGGER_FILE = (
        "/storage/emulated/0/Android/data/dev.ipg.listener/files/dump_now.trigger"
    )
    VERIFY_PROBE_TIMEOUT_SEC = 15.0  # cold dex/class init can take a few seconds

    # '화면이 아직 그려지고 있다'는 신호로 간주할 a11y 이벤트 타입.
    # wait_for_content_quiet가 이 타입 이벤트의 도착 간격으로 안정성을 판정.
    CONTENT_EVENT_TYPES: tuple[str, ...] = (
        "WINDOW_CONTENT_CHANGED",
        "VIEW_SCROLLED",
        "WINDOW_STATE_CHANGED",
    )

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
        self._instr_proc = None

        # 이벤트 도착 시 monotonic하게 증가하는 카운터. wait_for_content_quiet가
        # 큐를 소비하지 않고 폴링으로 안정성을 판정할 수 있게 한다 — 다른
        # 컨슈머(wait_for_scroll_evt, request_dump_and_wait)의 큐 사용과 충돌 없음.
        self._content_seq = 0
        self._seq_lock = threading.Lock()

    # -----------------------------
    # lifecycle
    # -----------------------------

    def start(self) -> None:
        if self._thread is not None:
            return

        # 1. instrumentation 을 먼저 띄운다. `am instrument -w` 는 test 가 끝날
        #    때까지 block 하므로, test 의 while-loop 가 도는 동안 이 Popen 도 살아있다.
        #    NOTE: client.popen prepends only `adb` (no `shell`), so we add it ourselves.
        self._instr_proc = self._client.popen([
            "shell",
            "am", "instrument", "-w", "-m",
            "-e", "class", self.TEST_CLASS,
            self.TEST_RUNNER,
        ])

        # 2. logcat tail. -v raw: 메시지 본문(JSON)만. -T 1: 시작 시점 이후 라인만.
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
        if self._instr_proc is not None:
            try:
                self._instr_proc.terminate()
            except Exception:
                pass
            self._instr_proc = None
        # Belt-and-suspenders: kill the on-device process so a hung
        # instrumentation doesn't leak a UiAutomation registration.
        try:
            self._client.shell_text(
                f"am force-stop {self.LISTENER_PACKAGE}", check=False, timeout=5.0,
            )
        except Exception:
            pass

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

    def content_seq(self) -> int:
        """현재까지 누적된 content/scroll/state-change 이벤트 카운터."""
        with self._seq_lock:
            return self._content_seq

    def wait_for_content_quiet(
        self,
        *,
        poll_ms: int,
        required_quiet_polls: int,
        timeout_sec: float,
    ) -> dict:
        """
        a11y CONTENT_EVENT_TYPES 이벤트가 연속해서 `required_quiet_polls`회의
        polling 동안 도착하지 않을 때까지 대기. 실효 quiet window는
        대략 `poll_ms × required_quiet_polls` 밀리초.

        로딩 스피너·애니메이션이 계속 돌면 timeout_sec까지 기다린 뒤 강제 종료
        ('reason': 'timeout'). 화면이 이미 정지된 상태면 거의 즉시 'quiet' 반환.

        큐는 건드리지 않고 카운터만 폴링하므로 다른 컨슈머와 안전하게 공존.

        Returns: {'reason': 'quiet'|'timeout', 'elapsed_ms': float, 'events': int}
        """
        poll_sec = max(0.01, poll_ms / 1000.0)
        required = max(1, int(required_quiet_polls))

        start = time.monotonic()
        deadline = start + max(0.0, float(timeout_sec))
        initial_seq = self.content_seq()
        last_seq = initial_seq
        consecutive_quiet = 0

        while True:
            cur_seq = self.content_seq()
            if cur_seq != last_seq:
                consecutive_quiet = 0
                last_seq = cur_seq
            else:
                consecutive_quiet += 1

            now = time.monotonic()
            if consecutive_quiet >= required:
                return {
                    "reason": "quiet",
                    "elapsed_ms": (now - start) * 1000.0,
                    "events": cur_seq - initial_seq,
                }

            if now >= deadline:
                return {
                    "reason": "timeout",
                    "elapsed_ms": (now - start) * 1000.0,
                    "events": cur_seq - initial_seq,
                }

            time.sleep(poll_sec)

    # -----------------------------
    # availability check
    # -----------------------------

    def verify_available(self) -> None:
        """
        instrumentation 이 정상적으로 떠서 SERVICE_CONNECTED 를 emit 했는지 검증.
        실패 시 A11yServiceUnavailable.
        """
        for pkg in (self.LISTENER_PACKAGE, self.TEST_PACKAGE):
            if not self._is_package_installed(pkg):
                raise A11yServiceUnavailable(
                    f"device_listener APK 가 단말에 설치돼 있지 않음 ({pkg}). "
                    f"빌드 후 두 APK 를 모두 install 하세요:\n"
                    f"  adb install -r device_listener/app/build/outputs/apk/debug/app-debug.apk\n"
                    f"  adb install -r device_listener/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
                )

        # start() 가 이미 `am instrument` 를 띄웠으니, 여기서는 SERVICE_CONNECTED
        # 가 logcat 으로 흘러오기만 기다리면 된다. cold start 는 dex 변환 때문에
        # 수 초 걸릴 수 있어 VERIFY_PROBE_TIMEOUT_SEC 을 넉넉히 잡음.
        connected = self.wait_for(
            type_filter=("SERVICE_CONNECTED",),
            timeout_sec=self.VERIFY_PROBE_TIMEOUT_SEC,
        )
        if connected is None:
            raise A11yServiceUnavailable(
                f"instrumentation 이 {self.VERIFY_PROBE_TIMEOUT_SEC}s 내 "
                "SERVICE_CONNECTED 를 emit 하지 않음. "
                "`am instrument` 가 즉시 죽었거나 (\"UiAutomationService already "
                "registered\" 등), test APK 가 잘못된 서명일 수 있음. "
                "디바이스 재부팅 후 재시도하거나, `adb shell am instrument ...` 를 "
                "직접 실행해 stdout 을 확인하세요."
            )

        # 추가로 trigger 경로가 동작하는지 한 번 probe
        evt = self.request_dump_and_wait(timeout_sec=self.VERIFY_PROBE_TIMEOUT_SEC)
        if evt is None or not evt.xml_path:
            raise A11yServiceUnavailable(
                f"SERVICE_CONNECTED 은 받았지만 trigger-file 응답이 "
                f"{self.VERIFY_PROBE_TIMEOUT_SEC}s 내 안 옴. "
                "instrumentation 의 trigger poll loop 가 멈춘 듯."
            )

        if self._logger:
            self._logger.info(
                f"[A11Y] verified: instrumentation up, probe_xml={evt.xml_path}"
            )

    def _is_package_installed(self, pkg: str) -> bool:
        try:
            out = self._client.shell_text(
                f"pm path {pkg}",
                check=False,
                timeout=5.0,
            ).strip()
        except Exception:
            return False
        return out.startswith("package:")

    # -----------------------------
    # request-response helper
    # -----------------------------

    def request_dump_and_wait(
        self,
        *,
        timeout_sec: float = 5.0,
        pkg: Optional[str] = None,  # kept for API compat; not used by instrumentation
    ) -> Optional[A11yEvent]:
        """
        Sentinel 파일을 touch 해서 instrumentation 의 polling loop 를 깨운다.
        다음 DUMP_WRITTEN(또는 MANUAL_DUMP) 까지 기다린 뒤 반환.
        queue 는 호출 직전에 clear 되므로 stale event 매칭은 없다.
        """
        del pkg  # unused
        self.clear()

        try:
            self._client.shell_text(
                f"touch {self.TRIGGER_FILE}", check=False, timeout=5.0,
            )
        except Exception as e:
            if self._logger:
                self._logger.warning(f"[A11Y] trigger touch failed: {e}")
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

            if evt.type in self.CONTENT_EVENT_TYPES:
                with self._seq_lock:
                    self._content_seq += 1

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
