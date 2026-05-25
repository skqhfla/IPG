from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.app_types import Screen, Element


@dataclass(slots=True)
class DetectionResult:

    screen: Screen

    screenshot_path: Path

    xml_path: Optional[Path]

    snapshot_id: str

    yolo_elements: list[Element] | None = None
    uiauto_elements: list[Element] | None = None
    merged_elements: list[Element] | None = None