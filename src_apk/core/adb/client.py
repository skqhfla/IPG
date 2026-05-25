from __future__ import annotations

from pathlib import Path
import subprocess
import time
from typing import Any, Optional, Sequence

from core.adb.errors import ADBCommandError, ADBNoDeviceError


class ADBClient:
    """
    가장 얇은 ADB 실행 레이어.

    책임:
    - adb 명령 실행
    - stdout/stderr 반환
    - 실패 시 ADBCommandError 발생
    - 선택적 로깅

    비책임:
    - UI dump 정책(strict/try)
    - 파일 경로 관리
    - 상위 retry 정책
    - 앱 탐색 로직
    """

    def __init__(
        self,
        *,
        device_serial: Optional[str] = None,
        adb_path: str = "adb",
        logger: Optional[Any] = None,
    ) -> None:
        self.device_serial = device_serial
        self.adb_path = adb_path
        self.logger = logger

    # -------------------------
    # device state
    # -------------------------

    def has_device(self) -> bool:
        try:
            out = self.run_text(["get-state"], check=False).strip()
            return out in ("device", "recovery", "sideload")
        except Exception:
            return False

    def require_device(self) -> None:
        if not self.has_device():
            raise ADBNoDeviceError("adb: no devices/emulators found")

    # -------------------------
    # public APIs
    # -------------------------

    def run_text(
        self,
        args: Sequence[str],
        *,
        timeout: Optional[float] = 30.0,
        check: bool = True,
        encoding: str = "utf-8",
        max_chars: Optional[int] = None,
    ) -> str:
        """
        adb <args> 실행 후 stdout을 text로 반환.
        """
        stdout_b, stderr_b, rc, cmd_str, elapsed_ms = self._run_bytes(
            args,
            timeout=timeout,
        )

        out_full = _decode_all(stdout_b, encoding=encoding)
        err_full = _decode_all(stderr_b, encoding=encoding)

        if max_chars is not None and max_chars > 0:
            out_full = out_full[:max_chars]

        out = out_full.strip()
        err = err_full.strip()

        if check and rc != 0:
            raise ADBCommandError(
                cmd_str,
                rc,
                stdout=out,
                stderr=err,
            )

        return out

    def shell_text(
        self,
        command: str,
        *,
        timeout: Optional[float] = 30.0,
        check: bool = True,
        encoding: str = "utf-8",
        max_chars: Optional[int] = None,
    ) -> str:
        return self.run_text(
            ["shell", command],
            timeout=timeout,
            check=check,
            encoding=encoding,
            max_chars=max_chars,
        )

    def exec_out_bytes(
        self,
        args: Sequence[str],
        *,
        timeout: Optional[float] = 30.0,
        check: bool = True,
    ) -> bytes:
        stdout_b, stderr_b, rc, cmd_str, elapsed_ms = self._run_bytes(
            ["exec-out"] + list(args),
            timeout=timeout,
        )

        self._log(
            cmd_str,
            ok=(rc == 0),
            elapsed_ms=elapsed_ms,
            stdout_preview=f"<{len(stdout_b)} bytes>",
            stderr_preview=_safe_decode(stderr_b),
        )

        if check and rc != 0:
            raise ADBCommandError(
                cmd_str,
                rc,
                stdout=f"<{len(stdout_b)} bytes>",
                stderr=_safe_decode(stderr_b).strip(),
            )

        return stdout_b

    def popen(
        self,
        args: Sequence[str],
        *,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text: bool = True,
    ) -> subprocess.Popen:
        """
        스트리밍용 subprocess 실행.
        예: logcat 워커.
        Android logcat은 UTF-8 stream이므로 시스템 기본 코덱(cp949 등)에 의존하지 않게 명시.
        """
        cmd_list = self._base_cmd() + list(args)
        return subprocess.Popen(
            cmd_list,
            stdout=stdout,
            stderr=stderr,
            text=text,
            encoding="utf-8" if text else None,
            errors="replace" if text else None,
        )

    def pull(
        self,
        remote_path: str,
        local_path: Path,
        *,
        timeout: float = 30.0,
        retries: int = 5,
        sleep_s: float = 0.2,
    ) -> None:
        last_err: Exception | None = None

        for _ in range(retries):
            try:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                self.run_text(
                    ["pull", remote_path, str(local_path)],
                    timeout=timeout,
                    check=True,
                )
                return
            except Exception as e:
                last_err = e
                time.sleep(sleep_s)

        if last_err is not None:
            raise last_err

    # -------------------------
    # internal
    # -------------------------

    def _base_cmd(self) -> list[str]:
        cmd = [self.adb_path]
        if self.device_serial:
            cmd += ["-s", self.device_serial]
        return cmd

    def _run_bytes(
        self,
        args: Sequence[str],
        *,
        timeout: Optional[float],
    ) -> tuple[bytes, bytes, int, str, int]:
        cmd_list = self._base_cmd() + list(args)
        cmd_str = " ".join(cmd_list)

        t0 = time.monotonic()
        proc = subprocess.run(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            timeout=timeout,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        stdout_b = proc.stdout or b""
        stderr_b = proc.stderr or b""
        rc = proc.returncode

        self._log(
            cmd_str,
            ok=(rc == 0),
            elapsed_ms=elapsed_ms,
            stdout_preview=_preview(stdout_b),
            stderr_preview=_preview(stderr_b),
        )

        return stdout_b, stderr_b, rc, cmd_str, elapsed_ms

    def _log(
        self,
        cmd_str: str,
        *,
        ok: bool,
        elapsed_ms: int,
        stdout_preview: str,
        stderr_preview: str,
    ) -> None:
        if not self.logger:
            return

        try:
            if hasattr(self.logger, "command"):
                self.logger.command(
                    cmd_str,
                    ok=ok,
                    elapsed_ms=elapsed_ms,
                    stdout=stdout_preview,
                    stderr=stderr_preview,
                    serial=self.device_serial,
                )
            else:
                msg = f"[ADB] ({'OK' if ok else 'FAIL'}) {elapsed_ms}ms {cmd_str}"
                if ok:
                    self.logger.info(msg)
                else:
                    self.logger.warning(
                        msg
                        + f" stdout={stdout_preview[:300]}"
                        + f" stderr={stderr_preview[:300]}"
                    )
        except Exception:
            pass


def _safe_decode(
    b: bytes,
    *,
    encoding: str = "utf-8",
    limit: int = 5000,
) -> str:
    if not b:
        return ""
    return b.decode(encoding, errors="replace")[:limit]


def _decode_all(
    b: bytes,
    *,
    encoding: str = "utf-8",
) -> str:
    if not b:
        return ""
    return b.decode(encoding, errors="replace")


def _preview(
    b: bytes,
    *,
    encoding: str = "utf-8",
    limit: int = 5000,
) -> str:
    if not b:
        return ""
    return b.decode(encoding, errors="replace")[:limit]