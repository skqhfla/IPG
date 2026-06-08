from __future__ import annotations

from typing import Any

from core.app_types import Screen
from core.detection.base import BaseDetector
from core.detection.ocr_fill import fill_element_text_from_ocr
from core.detection.postprocess import filter_elements_by_modal_if_detected, normalize_elements
from core.detection.result import DetectionResult
from core.detection.screen_id import build_screen_id


class YOLODetector(BaseDetector):
    def __init__(
        self,
        ctx,
        *,
        yolo_model: Any,
        ocr_engine: Any = None,
    ) -> None:
        super().__init__(ctx)
        self.yolo_model = yolo_model
        self.ocr_engine = ocr_engine

    def detect(self, snapshot_id: str) -> DetectionResult:
        self._wait_until_stable()

        screenshot_path = self.ctx.paths.screen / f"{snapshot_id}.png"
        self.ctx.adb_device.screencap_png_to_file(screenshot_path)

        elements = list(
            self.yolo_model.detect_elements(
                image_path=str(screenshot_path),
            )
        )

        if self.ocr_engine is not None:
            ocr_items = self.ocr_engine.read(image_path=str(screenshot_path))
            elements = fill_element_text_from_ocr(
                elements=elements,
                ocr_items=ocr_items,
                fill_only_if_empty=True,
            )

        filtered = filter_elements_by_modal_if_detected(
            merged_elements=elements,
            model_elements=elements,
        )

        elements = normalize_elements(filtered)

        screen_id = build_screen_id(
            self.ctx.settings,
            elements,
            screen_wh=self.ctx.screen_wh,
        )

        screen = Screen(
            screen_id=screen_id,
            elements=elements,
            screenshot_path=screenshot_path,
            xml_path=None,
        )

        return DetectionResult(
            snapshot_id=snapshot_id,
            screen=screen,
            screenshot_path=screenshot_path,
            xml_path=None,
        )