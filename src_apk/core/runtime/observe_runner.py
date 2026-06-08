from __future__ import annotations

import threading

from core.adb import ADBClient, ADBDevice
from core.adb.a11y_event_listener import A11yEventListener, A11yServiceUnavailable
from core.adb.netstats import NetstatsSampler, PacketStat, resolve_uid
from core.config import Settings
from core.config.app_packages import get_app_package
from core.runtime.monitor.foreground_monitor import ForegroundState
from core.utils.path_manager import PathManager


_HELP = """\
Observe 모드 명령어 (이벤트/패킷은 백그라운드에서 계속 기록됨):
  cap | c | <Enter>  - 지금 화면의 XML + 스크린샷 + 이벤트 JSON 캡처
  help | h | ?       - 이 도움말
  quit | q           - 종료 (Ctrl+C 도 가능)
"""


class ObserveRunner:
    """
    수동 관찰 모드. 프레임워크는 어떤 이벤트도 트리거하지 않는다(executor·traverser
    없음). 사용자가 기기를 직접 조작하는 동안 device_listener instrumentation이
    흘리는 a11y 이벤트를 실시간으로 스트리밍하고(listener._log_event), 타겟 앱
    UID의 패킷 누적치를 주기적으로 샘플링해 직전 대비 변화량을 함께 출력한다.

    a11y 이벤트는 listener 백그라운드 스레드가 logger로 직접 찍으므로([A11Y]),
    이 러너의 메인 루프는 패킷 델타([PACKET])만 같은 logger로 흘려 두 스트림이
    콘솔/로그파일에서 시간순으로 섞이게 한다.
    """

    DUMP_TIMEOUT_SEC = 5.0

    def __init__(
        self,
        *,
        settings: Settings,
        paths: PathManager,
        app_name: str,
        device_serial: str | None = None,
        adb_path: str = "adb",
        logger=None,
    ) -> None:
        self.settings = settings
        self.paths = paths
        self.app_name = app_name
        self.device_serial = device_serial
        self.adb_path = adb_path
        self.logger = logger

        self._adb_client: ADBClient | None = None
        self._device: ADBDevice | None = None
        self._a11y_listener: A11yEventListener | None = None
        self._sampler: NetstatsSampler | None = None
        self._target_package: str = ""
        self._target_uid: int | None = None

        self._capture_counter = 0
        # request_dump_and_wait(메인)와 백그라운드 queue.clear()가 같은 큐를
        # 건드리므로, DUMP_WRITTEN 대기 중 clear가 끼어들지 않게 직렬화한다.
        self._cap_lock = threading.Lock()

    # -------------------------------------------------
    # lifecycle
    # -------------------------------------------------

    def initialize(self) -> None:
        client = ADBClient(
            device_serial=self.device_serial,
            adb_path=self.adb_path,
            logger=self.logger,
        )
        self._adb_client = client
        device = ADBDevice.create(client=client)
        device.require_device()
        self._device = device

        # 화면만 켠다 — 앱은 실행하지 않는다(기기 현재 상태 유지).
        device.wakeup()

        target_package = get_app_package(self.app_name)
        self._target_package = target_package

        # 패킷 측정용 UID. 앱이 foreground가 아니어도 설치돼 있으면 해석된다.
        uid = resolve_uid(device, target_package)
        self._target_uid = uid
        if uid is None:
            if self.logger:
                self.logger.warning(
                    f"[NETSTATS] {target_package} UID 해석 실패 — 패킷 측정 비활성화"
                )
            self._sampler = None
        else:
            self._sampler = NetstatsSampler(
                device=device,
                uid=uid,
                logger=self.logger,
            )

        # listener는 foreground_state를 갱신할 뿐 traversal엔 쓰이지 않는다.
        foreground_state = ForegroundState()
        listener = A11yEventListener(
            client=client,
            logger=self.logger,
            foreground_state=foreground_state,
            target_package=target_package,
        )
        listener.start()
        try:
            listener.verify_available()
        except A11yServiceUnavailable:
            listener.stop()
            self._a11y_listener = None
            raise
        self._a11y_listener = listener

    def run(self) -> None:
        self.initialize()

        interval = max(0.5, float(self.settings.packet.capture_time_sec))
        print(f"\n[Observe 모드] 앱={self.app_name} ({self._target_package})")
        print(
            "프레임워크는 이벤트를 트리거하지 않습니다. 기기를 직접 조작하세요.\n"
            f"a11y 이벤트는 [A11Y]로 계속 스트리밍되고, 패킷 변화량은 [PACKET]으로 "
            f"{interval:.0f}초마다 출력됩니다."
        )
        if self._sampler is None:
            print("패킷 측정 비활성화 (UID 해석 실패) — a11y 이벤트만 스트리밍합니다.")
        print(_HELP)

        stop_event = threading.Event()
        bg = threading.Thread(
            target=self._background_loop,
            args=(interval, stop_event),
            name="observe-bg",
            daemon=True,
        )
        bg.start()
        try:
            self._command_loop()
        finally:
            stop_event.set()
            bg.join(timeout=2.0)
            if self._a11y_listener is not None:
                self._a11y_listener.stop()
                self._a11y_listener = None
        print("[Observe 모드] 종료.")

    # -------------------------------------------------
    # command loop (foreground) — on-demand 캡처 트리거
    # -------------------------------------------------

    def _command_loop(self) -> None:
        while True:
            try:
                raw = input("observe> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return

            cmd = raw.lower()
            if cmd in ("quit", "q", "exit"):
                return
            if cmd in ("help", "h", "?"):
                print(_HELP)
                continue
            if cmd in ("", "cap", "c", "dump", "d"):
                self._capture()
                continue
            print(f"알 수 없는 명령어: '{raw}'. 'help' 참고.")

    def _capture(self) -> None:
        """지금 화면의 XML + 스크린샷 + 이벤트 JSON 을 호스트 세션 폴더로 수집.

        스크린샷은 일반 모드와 동일하게 `adb screencap`(현재 화면)으로 직접 찍고,
        XML/JSON 은 listener 의 manual dump(trigger 파일) → DUMP_WRITTEN 의
        device 경로를 pull 한다. 이벤트 스트리밍/패킷 샘플링은 그대로 계속된다.
        """
        listener = self._a11y_listener
        device = self._device
        client = self._adb_client
        if listener is None or device is None or client is None:
            print("  캡처 불가: listener/device 미초기화")
            return

        self._capture_counter += 1
        name = f"observe_{self._capture_counter:04d}"

        png = self.paths.screen / f"{name}.png"
        png_ok = False
        try:
            device.screencap_png_to_file(png)
            png_ok = png.exists()
        except Exception as e:
            self._warn(f"[CAPTURE] screencap 실패: {e}")

        xml = self.paths.xml / f"{name}.xml"
        json_path = self.paths.memory / f"{name}.json"
        xml_ok = False
        json_ok = False

        with self._cap_lock:
            evt = listener.request_dump_and_wait(timeout_sec=self.DUMP_TIMEOUT_SEC)

        if evt is not None and evt.xml_path:
            try:
                client.pull(evt.xml_path, xml, timeout=30.0, retries=3, sleep_s=0.1)
                xml_ok = xml.exists()
            except Exception as e:
                self._warn(f"[CAPTURE] xml pull 실패 ({evt.xml_path}): {e}")

            meta = evt.raw.get("meta")
            if meta:
                try:
                    client.pull(meta, json_path, timeout=30.0, retries=3, sleep_s=0.1)
                    json_ok = json_path.exists()
                except Exception as e:
                    self._warn(f"[CAPTURE] json pull 실패 ({meta}): {e}")
        else:
            self._warn("[CAPTURE] DUMP_WRITTEN 미수신 — xml/json 생략")

        msg = f"[CAPTURE] {name} png={png_ok} xml={xml_ok} json={json_ok}"
        if self.logger:
            self.logger.info(msg)
        print(f"  {msg}\n  → {self.paths.base}")

    # -------------------------------------------------
    # background loop — 패킷 샘플링 + 큐 유지
    # -------------------------------------------------

    def _background_loop(self, interval: float, stop_event: threading.Event) -> None:
        sampler = self._sampler
        before: PacketStat | None = sampler.sample() if sampler is not None else None

        while not stop_event.wait(interval):
            # 이벤트는 listener 백그라운드 스레드가 이미 [A11Y]로 로깅했으므로
            # 큐 사본은 불필요 — 무한 적재 방지를 위해 비운다. 캡처의
            # request_dump_and_wait 와 동일 큐를 다투지 않도록 lock 으로 직렬화.
            if self._a11y_listener is not None:
                with self._cap_lock:
                    self._a11y_listener.clear()

            if sampler is None:
                continue

            after = sampler.sample()
            if after is None:
                continue
            if before is not None:
                delta = after.delta(before)
                if delta.total_packets() > 0:
                    self._log_packet(delta, interval)
            before = after

    def _warn(self, msg: str) -> None:
        if self.logger:
            self.logger.warning(msg)
        else:
            print(msg)

    def _log_packet(self, delta: PacketStat, interval: float) -> None:
        msg = (
            f"[PACKET] window={interval:.0f}s "
            f"tx_pkts={delta.tx_packets} rx_pkts={delta.rx_packets} "
            f"tx_bytes={delta.tx_bytes} rx_bytes={delta.rx_bytes}"
        )
        if self.logger:
            self.logger.info(msg)
        else:
            print(msg)
