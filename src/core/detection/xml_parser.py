from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from core.app_types import BBox, Element


_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def simplify_android_class(name: str) -> str:
    if not name:
        return ""
    s = name.strip()
    if "." in s:
        return s.rsplit(".", 1)[-1]
    return s


def parse_bounds(bounds_str: str) -> tuple[int, int, int, int] | None:
    if not bounds_str:
        return None

    m = _BOUNDS_RE.fullmatch(bounds_str.strip())
    if not m:
        return None

    x1, y1, x2, y2 = map(int, m.groups())
    return x1, y1, x2, y2


def trim_to_xml(text: str) -> str:
    """
    adb 출력 앞에 불필요한 로그가 섞였을 때 XML 시작 지점으로 trim
    """
    start = text.find("<?xml")
    if start == -1:
        start = text.find("<hierarchy")

    if start > 0:
        return text[start:]
    return text


def parse_uia_xml(xml_path: Path) -> list[Element]:
    try:
        xml_text = xml_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    return parse_uia_xml_text(xml_text)


def parse_uia_xml_text(xml_text: str) -> list[Element]:
    xml_text = trim_to_xml(xml_text)
    root = ET.fromstring(xml_text)

    elements: list[Element] = []

    def is_layout(class_name: str) -> bool:
        s = class_name or ""
        return s.endswith("Layout") or s.endswith("ViewGroup")

    def has_meaningful_content(attrs: dict[str, str]) -> bool:
        return bool(
            (attrs.get("text") or "").strip()
            or (attrs.get("content-desc") or "").strip()
            or (attrs.get("resource-id") or "").strip()
        )

    def walk(node: ET.Element) -> None:
        if node.tag == "node":
            attrs = node.attrib
            raw_class = attrs.get("class") or ""
            class_name = simplify_android_class(raw_class)

            parsed = parse_bounds(attrs.get("bounds", ""))
            if parsed is None:
                for child in list(node):
                    walk(child)
                return

            x1, y1, x2, y2 = parsed
            bbox = BBox(x1=x1, y1=y1, x2=x2, y2=y2)

            # unlabeled layout / viewgroup는 직접 element로 만들지 않고 자식만 탐색
            if is_layout(class_name) and not has_meaningful_content(attrs):
                for child in list(node):
                    walk(child)
                return

            elements.append(
                Element(
                    element_id="",
                    cls=class_name or "unknown",
                    bbox=bbox,
                    source="uiautomator",
                    resource_id=attrs.get("resource-id") or None,
                    text=attrs.get("text") or None,
                    description=attrs.get("content-desc") or None,
                )
            )

        for child in list(node):
            walk(child)

    walk(root)
    return elements