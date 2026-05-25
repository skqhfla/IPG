from __future__ import annotations

import logging
from pathlib import Path

from core.config import LogMode


class _ScrollOnlyFilter(logging.Filter):
    """
    scroll-debug 모드: 스크롤 관련 로그 라인만 통과시킨다.

    통과 대상:
      - [SCROLL]    — scroll feedback / same-screen 유지 / over-scroll 보정
      - [POLICY]    — 연속 스크롤 상한 등 policy 결정
      - [A11Y]      — 모든 a11y 이벤트 (스크롤이 어떤 이벤트를 유발하는지 확인)
      - [EXECUTOR]  — 모든 행동(swipe·tap·back). 스크롤이 멈추고 tap으로
                      넘어가는 흐름까지 보여 루프 여부를 바로 판단할 수 있다.
    WARNING 이상은 디버깅 중 실패를 놓치지 않도록 항상 통과.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        msg = record.getMessage()
        if "[SCROLL]" in msg or "[POLICY]" in msg:
            return True
        if "[A11Y]" in msg:
            return True
        if "[EXECUTOR]" in msg:
            return True
        return False


def build_logger(
    *,
    name: str,
    log_mode: LogMode,
    log_path: Path,
    scroll_debug: bool = False,
) -> logging.Logger | None:

    if log_mode == LogMode.NO_LOG:
        return None

    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = False

    if log_mode == LogMode.DEBUG:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logger.setLevel(level)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if scroll_debug:
        # 로거 레벨 필터 — 파일/콘솔 두 핸들러 모두에 적용된다.
        logger.addFilter(_ScrollOnlyFilter())

    return logger