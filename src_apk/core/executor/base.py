#src/core/executor/base.py
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseActionExecutor(ABC):
    @abstractmethod
    def execute(self, action: dict) -> str:
        """
        action을 실제로 실행하고,
        기록용 event_key 문자열을 반환한다.
        """
        raise NotImplementedError