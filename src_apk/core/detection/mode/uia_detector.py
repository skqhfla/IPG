from __future__ import annotations

from core.app_types import Screen
from core.detection.base import BaseDetector
from core.detection.postprocess import normalize_elements
from core.detection.result import DetectionResult
from core.detection.screen_id import build_screen_id


class UIAutomatorDetector(BaseDetector):
    def detect(self, snapshot_id: str) -> DetectionResult:
        self._wait_until_stable()

        screenshot_path = self.ctx.paths.screen / f"{snapshot_id}.png"
        self.ctx.adb_device.screencap_png_to_file(screenshot_path)

        xml_path = self.ctx.paths.xml / f"{snapshot_id}.xml"
        dumped_xml, elements, meta, tree_signature = (
            self.dump_and_parse_ui_xml(xml_path)
        )

        elements = normalize_elements(elements)

        effective_wh = self.ctx.effective_screen_wh(meta.rotation)

        screen_id = build_screen_id(
            self.ctx.settings,
            elements,
            screen_wh=effective_wh,
            tree_signature=tree_signature,
            rotation=meta.rotation,
        )

        screen = Screen(
            screen_id=screen_id,
            elements=elements,
            screenshot_path=screenshot_path,
            xml_path=dumped_xml,
            window_id=meta.window_id,
            activity=meta.activity,
            package=meta.package,
            rotation=meta.rotation,
            tree_signature=tree_signature,
        )

        return DetectionResult(
            snapshot_id=snapshot_id,
            screen=screen,
            screenshot_path=screenshot_path,
            xml_path=dumped_xml,
        )
