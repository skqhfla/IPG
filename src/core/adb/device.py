from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from core.adb.client import ADBClient
from core.adb.command import ADBCommands


@dataclass(slots=True)
class ADBDevice:
    _client: ADBClient
    _cmd: ADBCommands

    @classmethod
    def create(cls, *, client: ADBClient) -> "ADBDevice":
        return cls(
            _client=client,
            _cmd=ADBCommands(client=client),
        )

    # -------------------------
    # device state
    # -------------------------

    def has_device(self) -> bool:
        return self._client.has_device()

    def require_device(self) -> None:
        self._client.require_device()

    # -------------------------
    # app/device actions
    # -------------------------

    def wakeup(self) -> None:
        self._cmd.wakeup()

    def launch_app(self, package: str, activity: Optional[str] = None) -> None:
        self._cmd.launch_app(package, activity)

    def start_app(self, package: str, activity: Optional[str] = None) -> None:
        self._cmd.start_app(package, activity)

    def bring_to_front(
        self,
        package: str,
        launcher_activity: Optional[str] = None,
    ) -> None:
        self._cmd.bring_to_front(package, launcher_activity)

    def get_foreground_app(self) -> Optional[tuple[str, str]]:
        return self._cmd.get_foreground_app()

    def get_foreground_package(self) -> str:
        return self._cmd.get_foreground_package()

    def back(self) -> None:
        self._cmd.back()

    def home(self) -> None:
        self._cmd.home()

    def tap(self, x: int, y: int) -> None:
        self._cmd.tap(x, y)

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 250,
    ) -> None:
        self._cmd.swipe(x1, y1, x2, y2, duration_ms)

    def input_text(self, text: str) -> None:
        self._cmd.input_text(text)

    # -------------------------
    # file capture
    # -------------------------

    def screencap_png_to_file(
        self,
        local_path: Path,
        remote_path: Optional[str] = None,
    ) -> Path:
        return self._cmd.screencap_png_to_file(
            local_path=local_path,
            remote_path=remote_path,
        )

    def dump_ui_xml_to_file(
        self,
        local_path: Path,
        remote_path: Optional[str] = None,
    ) -> Path:
        return self._cmd.dump_ui_xml_to_file(
            local_path=local_path,
            remote_path=remote_path,
        )

    def try_dump_ui_xml_to_file(
        self,
        local_path: Path,
        remote_path: Optional[str] = None,
    ) -> Optional[Path]:
        return self._cmd.try_dump_ui_xml_to_file(
            local_path=local_path,
            remote_path=remote_path,
        )
    
    def get_prop(self, key: str) -> str:
        return self._cmd.get_prop(key)

    def get_screen_size(self) -> tuple[int, int]:
        return self._cmd.get_screen_size()

    def get_package_info_text(self, package: str) -> str:
        return self._cmd.get_package_info_text(package)

    # -------------------------
    # shell/log access
    # -------------------------

    def iter_kernel_log(self) -> Iterable[str]:
        return self._cmd.logcat_kernel_stream()

    def shell_text(
        self,
        cmd: str,
        *,
        timeout: float = 30.0,
        check: bool = True,
    ) -> str:
        return self._cmd.shell_text(cmd, timeout=timeout, check=check)

    def shell(
        self,
        args: list[str],
        *,
        timeout: float = 30.0,
        check: bool = True,
    ) -> str:
        return self._cmd.run_text(["shell"] + list(args), timeout=timeout, check=check)