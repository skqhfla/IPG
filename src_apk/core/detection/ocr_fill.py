from __future__ import annotations

from core.app_types import Element
from core.detection.ocr import OCRItem


def fill_element_text_from_ocr(
    *,
    elements: list[Element],
    ocr_items: list[OCRItem],
    fill_only_if_empty: bool = True,
) -> list[Element]:
    for element in elements:
        if fill_only_if_empty and element.text:
            continue

        best_text = _find_best_text(element, ocr_items)
        if best_text:
            element.text = best_text

    return elements


def _find_best_text(element: Element, ocr_items: list[OCRItem]) -> str | None:
    ex1, ey1, ex2, ey2 = element.bbox.as_tuple()

    best = None
    best_score = -1.0

    for item in ocr_items:
        ox1, oy1, ox2, oy2 = item.bbox.as_tuple()

        inter_x1 = max(ex1, ox1)
        inter_y1 = max(ey1, oy1)
        inter_x2 = min(ex2, ox2)
        inter_y2 = min(ey2, oy2)

        inter_w = max(0, inter_x2 - inter_x1)
        inter_h = max(0, inter_y2 - inter_y1)
        inter_area = inter_w * inter_h

        if inter_area <= 0:
            continue

        ocr_area = max(1, (ox2 - ox1) * (oy2 - oy1))
        score = inter_area / ocr_area

        if score > best_score:
            best_score = score
            best = item.text

    return best