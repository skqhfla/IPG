from __future__ import annotations

import shutil

from core.adb import ADBClient, ADBDevice
from core.adb.a11y_event_listener import A11yEventListener, A11yServiceUnavailable
from core.adb.metadata import collect_app_meta, collect_device_meta
from core.config import Settings
from core.config.app_packages import get_app_package
from core.detection.factory import create_detector
from core.graph.utg import UTGGraphData
from core.memory.app_memory import AppMemoryStore
from core.memory.packet_memory import PacketMemoryStore
from core.memory.screen_memory import ScreenMemoryStore
from core.persistence.exceptions_io import ExceptionsIO
from core.runtime.context import RuntimeContext
from core.utils.path_manager import PathManager


_HELP = """\
Setup 모드 명령어:
  add            - 현재 기기 화면을 감지해 제외 목록에 추가
  list           - 등록된 제외 화면 목록 보기
  remove <id>    - 제외 목록에서 제거 (앞부분 일치로 검색 가능)
  help           - 이 도움말 보기
  quit           - 종료
"""


class SetupRunner:
    def __init__(
        self,
        *,
        settings: Settings,
        paths: PathManager,
        app_name: str,
        launcher_activity: str | None = None,
        device_serial: str | None = None,
        adb_path: str = "adb",
        logger=None,
    ) -> None:
        self.settings = settings
        self.paths = paths
        self.app_name = app_name
        self.launcher_activity = launcher_activity
        self.device_serial = device_serial
        self.adb_path = adb_path
        self.logger = logger

        self.ctx: RuntimeContext | None = None
        self.exceptions_io = ExceptionsIO(paths)
        self._capture_counter = 0

        self._a11y_listener: A11yEventListener | None = None
        self._adb_client: ADBClient | None = None

    def initialize(self) -> None:
        client = ADBClient(
            device_serial=self.device_serial,
            adb_path=self.adb_path,
            logger=self.logger,
        )
        self._adb_client = client
        device = ADBDevice.create(client=client)
        device.require_device()

        target_package = get_app_package(self.app_name)

        device.wakeup()
        device.launch_app(target_package, self.launcher_activity)

        device_meta = collect_device_meta(device)
        app_meta = collect_app_meta(
            device,
            app_name=self.app_name,
            package=target_package,
        )

        self.ctx = RuntimeContext(
            settings=self.settings,
            paths=self.paths,
            adb_device=device,
            target_app_name=self.app_name,
            target_package=target_package,
            launcher_activity=self.launcher_activity,
            app_memory=AppMemoryStore(),
            screen_memory=ScreenMemoryStore(),
            packet_memory=PacketMemoryStore(),
            utg=UTGGraphData(),
            device_meta=device_meta,
            app_meta=app_meta,
            logger=self.logger,
        )

        # A11y listener — runner와 동일한 dump 경로를 쓰기 위해 setup에서도 시작.
        # device_listener APK가 미설치/비활성 상태면 A11yServiceUnavailable 발생.
        self._a11y_listener = A11yEventListener(
            client=client,
            logger=self.logger,
            foreground_state=self.ctx.foreground_state,
            target_package=self.ctx.target_package,
        )
        self._a11y_listener.start()

        try:
            self._a11y_listener.verify_available()
        except A11yServiceUnavailable:
            self._a11y_listener.stop()
            self._a11y_listener = None
            raise

        self.ctx.a11y_listener = self._a11y_listener

        self.ctx.detector = create_detector(self.ctx)

    def run(self) -> None:
        self.initialize()
        assert self.ctx is not None

        print(f"\n[Setup 모드] 앱={self.app_name}")
        print(f"예외 파일: {self.paths.exceptions_file}")
        existing = self.exceptions_io.load_screen_ids()
        print(f"기존 등록된 제외 화면 {len(existing)}개 로드됨.")
        print(_HELP)

        try:
            self._command_loop()
        finally:
            if self._a11y_listener is not None:
                self._a11y_listener.stop()
                self._a11y_listener = None

        print("[Setup 모드] 종료.")

    # -------------------------------------------------
    # command loop
    # -------------------------------------------------

    def _command_loop(self) -> None:
        while True:
            try:
                raw = input("setup> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return

            if not raw:
                continue

            parts = raw.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("quit", "q", "exit"):
                return
            if cmd in ("help", "h", "?"):
                print(_HELP)
                continue
            if cmd == "list":
                self._cmd_list()
                continue
            if cmd == "add":
                self._cmd_add()
                continue
            if cmd == "remove":
                if not arg:
                    print("사용법: remove <screen_id>")
                    continue
                self._cmd_remove(arg)
                continue

            print(f"알 수 없는 명령어: '{cmd}'. 'help'를 입력하면 명령어 목록이 나옵니다.")

    def _cmd_list(self) -> None:
        data = self.exceptions_io.load()
        entries = data.get("exclusions", [])
        if not entries:
            print("(등록된 제외 화면 없음)")
            return
        for i, e in enumerate(entries):
            sid = e.get("screen_id", "?")
            ts = e.get("registered_at", "?")
            print(f"  #{i:<3} {sid}  등록시각={ts}")

    def _cmd_add(self) -> None:
        assert self.ctx is not None
        self._capture_counter += 1
        snapshot_id = f"setup_{self._capture_counter:04d}"

        try:
            det = self.ctx.detector.detect(snapshot_id)
        except Exception as e:
            print(f"감지 실패: {e}")
            return

        screen_id = det.screen.screen_id.to_key()

        saved_path = None
        if det.screenshot_path is not None and det.screenshot_path.exists():
            dst_dir = self.paths.exceptions_screenshots
            dst_dir.mkdir(parents=True, exist_ok=True)
            saved_path = dst_dir / f"{screen_id}.png"
            shutil.copyfile(det.screenshot_path, saved_path)

        added = self.exceptions_io.add_screen(screen_id, saved_path)
        if added:
            print(f"[+] 등록됨: {screen_id}")
            if saved_path is not None:
                print(f"    스크린샷: {saved_path}")
        else:
            print(f"[=] 이미 등록된 화면: {screen_id}")

    def _cmd_remove(self, query: str) -> None:
        data = self.exceptions_io.load()
        entries = data.get("exclusions", [])
        matches = [e for e in entries if e.get("screen_id", "").startswith(query)]
        if not matches:
            print(f"일치하는 항목 없음: '{query}'")
            return
        if len(matches) > 1:
            print(f"중복됨 — {len(matches)}개 일치:")
            for e in matches:
                print(f"  {e.get('screen_id')}")
            return
        full_id = matches[0]["screen_id"]
        if self.exceptions_io.remove_screen(full_id):
            print(f"[-] 제거됨: {full_id}")
        else:
            print(f"찾을 수 없음: {full_id}")
