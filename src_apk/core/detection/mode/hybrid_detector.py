from __future__ import annotations

from typing import Any

from core.app_types import Screen
from core.detection.base import BaseDetector
from core.detection.merge.strategies import IoUPriorityMerge
from core.detection.ocr_fill import fill_element_text_from_ocr
from core.detection.postprocess import (
    filter_elements_by_modal_if_detected,
    normalize_elements,
)
from core.detection.result import DetectionResult
from core.detection.screen_id import build_screen_id
from core.config.settings import LogMode


class HybridDetector(BaseDetector):
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
        self.merge_strategy = IoUPriorityMerge(
            threshold=ctx.settings.detection.iou_threshold,
            prefer_source="uiautomator",
        )

    def detect(self, snapshot_id: str) -> DetectionResult:
        self._wait_until_stable()

        screenshot_path = self.ctx.paths.screen / f"{snapshot_id}.png"
        xml_path = self.ctx.paths.xml / f"{snapshot_id}.xml"

        self.ctx.adb_device.screencap_png_to_file(screenshot_path)
        dumped_xml, uia_elements, meta, tree_signature = (
            self.dump_and_parse_ui_xml(xml_path)
        )

        model_elements = list(
            self.yolo_model.detect_elements(
                image_path=str(screenshot_path),
            )
        )

        should_run_ocr = (
            self.ocr_engine is not None
            and dumped_xml is None
        )

        if should_run_ocr:
            ocr_items = self.ocr_engine.read(image_path=str(screenshot_path))

            model_elements = fill_element_text_from_ocr(
                elements=model_elements,
                ocr_items=ocr_items,
                fill_only_if_empty=True,
            )

        effective_wh = self.ctx.effective_screen_wh(meta.rotation)

        merged = list(
            self.merge_strategy.merge(
                uia=uia_elements,
                model=model_elements,
                screen_wh=effective_wh,
            )
        )

        before_modal_filter = len(merged)

        merged = filter_elements_by_modal_if_detected(
            merged_elements=merged,
            model_elements=model_elements,
        )

        after_modal_filter = len(merged)

        if (
            self.ctx.logger is not None
            and before_modal_filter != after_modal_filter
        ):
            self.ctx.logger.info(
                f"[MODAL_FILTER] snapshot={snapshot_id} kept "
                f"{after_modal_filter}/{before_modal_filter} elements"
            )

        merged = normalize_elements(merged)

        screen_id = build_screen_id(
            self.ctx.settings,
            merged,
            screen_wh=effective_wh,
            tree_signature=tree_signature,
            rotation=meta.rotation,
        )

        screen = Screen(
            screen_id=screen_id,
            elements=merged,
            screenshot_path=screenshot_path,
            xml_path=dumped_xml,
            window_id=meta.window_id,
            activity=meta.activity,
            package=meta.package,
            rotation=meta.rotation,
            tree_signature=tree_signature,
        )

        debug_enabled = (
            self.ctx.settings.runtime.log_mode == LogMode.DEBUG
        )

        result = DetectionResult(
            screen=screen,
            snapshot_id=snapshot_id,
            screenshot_path=screenshot_path,
            xml_path=dumped_xml,
        )

        if debug_enabled:
            result.yolo_elements = model_elements
            result.uiauto_elements = uia_elements
            result.merged_elements = merged

        return result