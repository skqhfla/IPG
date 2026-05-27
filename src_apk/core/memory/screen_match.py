from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from core.app_types import Screen


def _ensure_tree_signature(screen: Screen) -> tuple[str, ...]:
    """
    Screen.tree_signature가 비어 있으면 xml_path에서 lazy 계산해 캐시한다.
    loader 경로(JSON에서 복원된 Screen)는 detector를 거치지 않아 시그니처가
    비어 있는데, 매칭 시점에 채워두면 같은 run 안에서 재호출이 빨라진다.
    """
    if screen.tree_signature:
        return screen.tree_signature

    xml_path = screen.xml_path
    if xml_path is None:
        return ()

    # 순환 import 방지: core.detection.__init__이 BaseDetector → RuntimeContext →
    # AppMemoryStore → screen_match를 끌고 와 cycle을 만들어, 모듈-top 대신 lazy import.
    from core.detection.xml_parser import compute_tree_signature

    try:
        path_obj = xml_path if isinstance(xml_path, Path) else Path(xml_path)
        if not path_obj.exists():
            return ()
        xml_text = path_obj.read_text(encoding="utf-8", errors="ignore")
        root = ET.fromstring(xml_text)
        sig = compute_tree_signature(root)
    except Exception:
        return ()

    screen.tree_signature = sig
    return sig


def _multiset_jaccard(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0

    ca = Counter(a)
    cb = Counter(b)
    keys = set(ca) | set(cb)
    inter = sum(min(ca[k], cb[k]) for k in keys)
    union = sum(max(ca[k], cb[k]) for k in keys)
    if union == 0:
        return 0.0
    return inter / union


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
      2) 버킷 안에서 canonical subtree-hash multiset Jaccard가 최대이고
         threshold 이상이면 그 key 반환. 트리 모든 깊이의 부분구조 카운트를
         비교하므로 RN 라우터 sub-route처럼 native 골격만 공유하고 콘텐츠가
         다른 화면을 분리해 낼 수 있다.
      3) 매칭 실패면 None → 호출자가 신규 화면으로 등록 (해시 폴백).

    candidate의 tree_signature가 비면(예: XML dump 실패, YOLO-only) 구조
    매칭이 불가능하므로 None을 반환해 기존 해시 기반 식별로 폴백한다.
    """
    cand_sig = _ensure_tree_signature(candidate)
    if not cand_sig:
        return None

    cand_win = candidate.window_id
    cand_act = candidate.activity or None
    cand_rot = getattr(candidate, "rotation", 0) or 0

    best_key: str | None = None
    best_sim = -1.0

    for key, scr in existing.items():
        if scr.window_id != cand_win:
            continue
        if (scr.activity or None) != cand_act:
            continue
        # rotation이 다르면 (예: 0 vs 1) 좌표 정규화 결과가 다르므로 같은 화면으로
        # 묶지 않는다. portrait/landscape variant는 별도 screen_id를 가져야 한다.
        if (getattr(scr, "rotation", 0) or 0) != cand_rot:
            continue
        scr_sig = _ensure_tree_signature(scr)
        if not scr_sig:
            continue
        sim = _multiset_jaccard(scr_sig, cand_sig)
        if sim > best_sim:
            best_sim = sim
            best_key = key

    if best_key is not None and best_sim >= threshold:
        return best_key
    return None
