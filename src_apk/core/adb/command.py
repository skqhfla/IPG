from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
import re

from core.adb.client import ADBClient


_CURRENT_FOCUS_RE = re.compile(r"mCurrentFocus=.*\s([\w.]+)\/([\w.$]+)")
_FOCUSED_APP_RE = re.compile(r"mFocusedApp=.*\s([\w.]+)\/([\w.$]+)")
_RESUMED_RE = re.compile(r"mResumedActivity:.*\s([\w.]+)\/([\w.$]+)")


@dataclass(slots=True)
class ADBCommands:
    client: ADBClient

    def run_text(
        self,
        args: list[str],
        *,
        timeout: float = 30.0,
        check: bool = True,
    ) -> str:
        return self.client.run_text(args, timeout=timeout, check=check)

    def shell_text(
        self,
        cmd: str,
        *,
        timeout: float = 30.0,
        check: bool = True,
    ) -> str:
        return self.client.shell_text(cmd, timeout=timeout, check=check)

    # -------------------------
    # input events
    # -------------------------

    def keyevent(self, keycode: str) -> None:
        self.shell_text(f"input keyevent {keycode}")

    def back(self) -> None:
        self.keyevent("KEYCODE_BACK")

    def home(self) -> None:
        self.keyevent("KEYCODE_HOME")

    def wakeup(self) -> None:
        self.keyevent("KEYCODE_WAKEUP")

    def tap(self, x: int, y: int) -> None:
        self.shell_text(f"input tap {x} {y}")

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 250,
    ) -> None:
        self.shell_text(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")

    def input_text(self, text: str) -> None:
        self.shell_text(f'input text "{text}"')

    # -------------------------
    # app control
    # -------------------------

    def launch_app(self, package: str, activity: Optional[str] = None) -> None:
        self.shell_text(f"am force-stop {package}")

        if activity:
            self.shell_text(f"am start -n {package}/{activity}")
        else:
            self.shell_text(
                f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
            )

    def start_app(self, package: str, activity: Optional[str] = None) -> None:
        """
        force-stop 없이 앱을 앞으로 시작.
        recover 용도.
        """
        if activity:
            self.shell_text(f"am start -W -n {package}/{activity}")
        else:
            self.shell_text(
                f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
            )

    def bring_to_front(
        self,
        package: str,
        launcher_activity: Optional[str] = None,
    ) -> None:
        # modal/camera/webview 탈출용
        self.back()
        self.back()
        self.home()

        if launcher_activity:
            self.shell_text(f"am start -W -n {package}/{launcher_activity}")
            return

        self.shell_text(
            f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
        )

    def _parse_foreground_from_dumpsys(self, text: str) -> Optional[tuple[str, str]]:
        """
        dumpsys window windows 파싱

        우선순위:
        1) mCurrentFocus
        2) mFocusedApp
        3) mResumedActivity
        """
        cur: Optional[tuple[str, str]] = None
        foc: Optional[tuple[str, str]] = None
        res: Optional[tuple[str, str]] = None

        for ln in text.splitlines():
            ln = ln.strip()

            if cur is None:
                m = _CURRENT_FOCUS_RE.search(ln)
                if m:
                    cur = (m.group(1), m.group(2))

            if foc is None:
                m = _FOCUSED_APP_RE.search(ln)
                if m:
                    foc = (m.group(1), m.group(2))

            if res is None:
                m = _RESUMED_RE.search(ln)
                if m:
                    res = (m.group(1), m.group(2))

        return cur or foc or res

    def get_foreground_app(self) -> Optional[tuple[str, str]]:
        """
        현재 foreground package/activity를 함께 반환.
        """
        out = self.shell_text(
            "dumpsys window windows",
            timeout=10.0,
            check=False,
        )
        return self._parse_foreground_from_dumpsys(out)

    def get_foreground_package(self) -> str:
        app = self.get_foreground_app()
        if app is None:
            return ""
        pkg, _ = app
        return pkg

    # -------------------------
    # file capture
    # -------------------------

    def screencap_png_to_file(
        self,
        *,
        local_path: Path,
        remote_path: Optional[str] = None,
    ) -> Path:
        if remote_path is None:
            remote_path = f"/sdcard/{local_path.name}"

        self.shell_text(f"screencap -p {remote_path}")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.client.pull(remote_path, local_path)

        try:
            self.shell_text(f"rm {remote_path}", check=False)
        except Exception:
            pass

        return local_path

    def dump_ui_xml_to_file(
        self,
        *,
        local_path: Path,
        remote_path: Optional[str] = None,
    ) -> Path:
        if remote_path is None:
            remote_path = f"/sdcard/{local_path.name}"

        self.shell_text(f"uiautomator dump {remote_path}")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.client.pull(
            remote_path,
            local_path,
            timeout=60.0,
            retries=5,
            sleep_s=0.2,
        )

        try:
            self.shell_text(f"rm {remote_path}", check=False)
        except Exception:
            pass

        return local_path

    def try_dump_ui_xml_to_file(
        self,
        *,
        local_path: Path,
        remote_path: Optional[str] = None,
    ) -> Optional[Path]:
        try:
            return self.dump_ui_xml_to_file(
                local_path=local_path,
                remote_path=remote_path,
            )
        except Exception:
            return None

    # -------------------------
    # log streams
    # -------------------------

    def logcat_kernel_stream(self) -> Iterable[str]:
        proc = self.client.popen(["logcat", "-b", "kernel", "-v", "time"])
        assert proc.stdout is not None

        for line in proc.stdout:
            yield line

    def get_prop(self, key: str) -> str:
        return self.shell_text(f"getprop {key}", check=False).strip()

    def get_screen_size(self) -> tuple[int, int]:
        out = self.shell_text("wm size", check=False)
        for line in out.splitlines():
            line = line.strip()
            if ":" not in line:
                continue
            _, value = line.split(":", 1)
            value = value.strip()
            if "x" not in value:
                continue
            try:
                w_str, h_str = value.split("x", 1)
                return int(w_str), int(h_str)
            except ValueError:
                continue
        return 0, 0

    def get_package_info_text(self, package: str) -> str:
        return self.shell_text(f"dumpsys package {package}", check=False)