#src/core/adb/errors.py
from __future__ import annotations


class ADBNoDeviceError(RuntimeError):
    pass


class ADBCommandError(RuntimeError):
    def __init__(
        self,
        cmd: str,
        returncode: int,
        *,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"ADB command failed ({returncode}): {cmd}\nstderr={stderr}")