#src/core/detection/postprocess.py
from __future__ import annotations

from core.app_types import BBox, Element


DANGER_KEYWORDS = {
    "로그인",
    "로그아웃",
    "삭제",
    "회원탈퇴",
    "초기화",
    "제거",
    "해제",
    "결제",
    "구매",
}


def normalize_elements(elements: list[Element]) -> list[Element]:
    """
    1. 위험 키워드 기반 is_actionable 판정
    2. 위치 기준 정렬
    3. screen-local element_id 부여
    """
    for element in elements:
        text_blob = f"{element.text or ''} {element.description or ''}".strip()

        if any(keyword in text_blob for keyword in DANGER_KEYWORDS):
            element.is_actionable = False

    elements.sort(key=lambda e: (e.bbox.y1, e.bbox.x1, e.bbox.y2, e.bbox.x2))

    for idx, element in enumerate(elements):
        element.element_id = f"el_{idx:04d}"

    return elements


def filter_elements_by_modal_if_detected(
    *,
    merged_elements: list[Element],
    model_elements: list[Element],
    min_coverage: float = 0.85,
    keep_modal_itself: bool = True,
) -> list[Element]:
    """
    YOLO/model detection 결과에서 modal이 감지되면,
    modal 영역 내부 element만 남긴다.

    기준:
    - model_elements 중 cls == "modal" 인 가장 큰 bbox를 active modal로 사용
    - merged_elements 중
      - modal 자신은 유지(keep_modal_itself=True일 때)
      - element 중심점이 modal 내부에 있고
      - element bbox의 modal 내부 포함 비율이 min_coverage 이상이면 유지
    """
    modal = _pick_active_modal_from_model(model_elements)
    if modal is None:
        return list(merged_elements)

    modal_bbox = modal.bbox
    kept: list[Element] = []

    for element in merged_elements:
        cls_name = (element.cls or "").lower()

        if keep_modal_itself and cls_name == "modal":
            kept.append(element)
            continue

        area = _area(element.bbox)
        if area <= 0:
            continue

        inter = _intersection_area(element.bbox, modal_bbox)
        coverage = inter / area if area > 0 else 0.0

        if _center_in(element.bbox, modal_bbox) and coverage >= float(min_coverage):
            kept.append(element)

    return kept


def _pick_active_modal_from_model(model_elements: list[Element]) -> Element | None:
    """
    model detection 결과 중 modal 후보를 골라
    가장 큰 modal 하나를 활성 modal로 간주한다.
    """
    modals = [
        element
        for element in model_elements
        if (element.cls or "").lower() == "modal"
        and (element.source or "").lower() == "yolo"
    ]

    if not modals:
        return None

    modals.sort(key=lambda e: _area(e.bbox), reverse=True)
    return modals[0]


def _area(bbox: BBox) -> int:
    return max(0, bbox.x2 - bbox.x1) * max(0, bbox.y2 - bbox.y1)


def _intersection_area(a: BBox, b: BBox) -> int:
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)

    w = max(0, ix2 - ix1)
    h = max(0, iy2 - iy1)
    return w * h


def _center_in(inner: BBox, outer: BBox) -> bool:
    cx = (inner.x1 + inner.x2) // 2
    cy = (inner.y1 + inner.y2) // 2
    return outer.x1 <= cx <= outer.x2 and outer.y1 <= cy <= outer.y2