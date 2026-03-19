from __future__ import annotations

from abc import ABC, abstractmethod

from core.runtime.context import RuntimeContext
from .result import DetectionResult


class BaseDetector(ABC):
    def __init__(self, ctx: RuntimeContext) -> None:
        self.ctx = ctx

    @abstractmethod
    def detect(self, snapshot_id: str) -> DetectionResult:
        raise NotImplementedError