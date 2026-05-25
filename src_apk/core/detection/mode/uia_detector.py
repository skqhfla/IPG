from __future__ import annotations

from core.app_types import Screen
from core.detection.base import BaseDetector
from core.detection.postprocess import normalize_elements
from core.detection.result import DetectionResult
from core.detection.screen_id import build_screen_id
from core.detection.xml_parser import HierarchyMeta, parse_uia_xml


class UIAutomatorDetector(BaseDetector):
    def detect(self, snapshot_id: str) -> DetectionResult:
        self._wait_until_stable()

        screenshot_path = self.ctx.paths.screen / f"{snapshot_id}.png"
        self.ctx.adb_device.screencap_png_to_file(screenshot_path)

        xml_path = self.ctx.paths.xml / f"{snapshot_id}.xml"
        dumped_xml = self.dump_ui_xml(xml_path)

        if dumped_xml is None:
            elements = []
            meta = HierarchyMeta()
        else:
            elements, meta = parse_uia_xml(dumped_xml)

        elements = normalize_elements(elements)

        screen_id = build_screen_id(
            self.ctx.settings,
            elements,
            screen_wh=self.ctx.screen_wh,
        )

        screen = Screen(
            screen_id=screen_id,
            elements=elements,
            screenshot_path=screenshot_path,
            xml_path=dumped_xml,
            window_id=meta.window_id,
            activity=meta.activity,
        )

        return DetectionResult(
            snapshot_id=snapshot_id,
            screen=screen,
            screenshot_path=screenshot_path,
            xml_path=dumped_xml,
        )
