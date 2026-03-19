# src/core/executor/action_executor.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.executor.base import BaseActionExecutor
from core.runtime.context import RuntimeContext


@dataclass(slots=True)
class ActionExecutor(BaseActionExecutor):
    ctx: RuntimeContext
    logger: Any = None
    settle_time_sec: float = 1.0

    def execute(self, action: dict[str, Any]) -> str:
        action_type = action["type"]
        screen_key = self._current_screen_key()

        if action_type == "tap":
            return self._execute_tap(action, screen_key)

        if action_type == "swipe":
            return self._execute_swipe(action, screen_key)

        if action_type == "back":
            return self._execute_back(action, screen_key)

        if action_type == "home":
            return self._execute_home(action, screen_key)

        if action_type == "input":
            return self._execute_input(action, screen_key)

        raise ValueError(f"Unsupported action type: {action_type}")

    def _execute_tap(self, action: dict[str, Any], screen_key: str) -> str:
        x = int(action["x"])
        y = int(action["y"])
        self.ctx.adb_device.tap(x, y)

        element_id = action.get("element_id", "unknown")
        self._log(
            f"[EXECUTOR] screen={screen_key} "
            f"tap ({x},{y}) "
            f"element_id={element_id} "
            f"class={action.get('element_class')} "
            f"text={action.get('element_text')!r}"
        )
        return f"tap@{element_id}"

    def _execute_swipe(self, action: dict[str, Any], screen_key: str) -> str:
        x1 = int(action["x1"])
        y1 = int(action["y1"])
        x2 = int(action["x2"])
        y2 = int(action["y2"])
        duration_ms = int(action.get("duration_ms", 250))

        self.ctx.adb_device.swipe(x1, y1, x2, y2, duration_ms)

        element_id = action.get("element_id", "screen")
        self._log(
            f"[EXECUTOR] screen={screen_key} "
            f"swipe ({x1},{y1})->({x2},{y2}) "
            f"duration_ms={duration_ms} "
            f"element_id={element_id}"
        )
        return f"swipe@{element_id}"

    def _execute_back(self, action: dict[str, Any], screen_key: str) -> str:
        self.ctx.adb_device.back()
        self._log(
            f"[EXECUTOR] screen={screen_key} "
            f"back why={action.get('why')}"
        )
        return "back"

    def _execute_home(self, action: dict[str, Any], screen_key: str) -> str:
        self.ctx.adb_device.home()
        self._log(
            f"[EXECUTOR] screen={screen_key} "
            f"home why={action.get('why')}"
        )
        return "home"

    def _execute_input(self, action: dict[str, Any], screen_key: str) -> str:
        text = str(action["text"])
        self.ctx.adb_device.input_text(text)

        element_id = action.get("element_id", "unknown")
        self._log(
            f"[EXECUTOR] screen={screen_key} "
            f"input text={text!r} "
            f"element_id={element_id}"
        )
        return f"input@{element_id}"

    def _current_screen_key(self) -> str:
        if self.ctx.current_screen_key:
            return self.ctx.current_screen_key

        if self.ctx.current_screen is not None:
            return self.ctx.current_screen.screen_id.to_key()

        return "unknown"

    def _log(self, message: str) -> None:
        logger = self.logger or self.ctx.logger
        if logger:
            logger.info(message)