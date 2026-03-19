#src/core/models/base.py
from __future__ import annotations

from typing import Protocol, Sequence

from core.app_types import Element


class ElementModel(Protocol):
    """
    Pluggable model interface.

    Input:
        image_path: screenshot file path

    Output:
        sequence of detected UI Elements
    """

    name: str

    def detect_elements(
        self,
        *,
        image_path: str,
    ) -> Sequence[Element]:
        ...