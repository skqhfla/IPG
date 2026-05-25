from __future__ import annotations

from core.app_types import Screen


def resource_id_set(screen: Screen) -> frozenset[str]:
    """화면 element들의 resource-id 집합 — 구조 골격 fingerprint."""
    return frozenset(
        e.resource_id
        for e in screen.elements
        if e.resource_id
    )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def match_screen(
    *,
    candidate: Screen,
    existing: dict[str, Screen],
    threshold: float,
) -> str | None:
    """
    candidate를 같은 화면으로 볼 기존 screen_key를 찾는다.

    판정:
      1) 같은 (window_id, activity) 버킷으로 후보를 제한
         → activity 전환·다른 window는 무조건 다른 화면.
      2) 버킷 안에서 resource-id 집합 Jaccard 유사도가 최대이고
         threshold 이상이면 그 key 반환 (스크롤·로딩 스피너·탭 전환·
         아이템 재정렬을 모두 흡수).
      3) 매칭 실패면 None → 호출자가 신규 화면으로 등록(해시 폴백).

    window_id도 없고 resource-id도 없으면 구조 매칭이 불가능하므로
    None을 반환해 기존 해시 기반 식별로 폴백한다.
    """
    cand_win = candidate.window_id
    cand_act = candidate.activity or None
    cand_rids = resource_id_set(candidate)

    if cand_win is None and not cand_rids:
        return None

    best_key: str | None = None
    best_sim = -1.0

    for key, scr in existing.items():
        if scr.window_id != cand_win:
            continue
        if (scr.activity or None) != cand_act:
            continue
        sim = _jaccard(resource_id_set(scr), cand_rids)
        if sim > best_sim:
            best_sim = sim
            best_key = key

    if best_key is not None and best_sim >= threshold:
        return best_key
    return None
