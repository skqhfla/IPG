"""
XML 한 장(또는 raw text)을 받아 screen_id가 어떻게 만들어지는지, 그리고
주어진 app_memory.json 안 기존 화면들과 어떻게 매칭되는지 step-by-step
trace를 JSON으로 stdout 에 출력하는 CLI.

Monitor 의 'Screen ID 검사' 탭이 이 스크립트를 spawn 해서 결과를 시각화한다.
runtime 도구와 동일한 컴포넌트(xml_parser, screen_id builder, match_screen)
를 사용하므로 실제 파이프라인과 1:1로 일치하는 결과가 나온다.

usage:
  python -m tools.inspect_screen_id --xml path/to/000182.xml \
      [--app-memory path/to/app_memory.json] [--threshold 0.6]

  python -m tools.inspect_screen_id --xml-text "@/tmp/raw.xml" ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

# src_apk 루트를 sys.path 에 올려서 core.* import 가 동작하게 한다.
_THIS = Path(__file__).resolve()
_SRC_APK = _THIS.parent.parent
if str(_SRC_APK) not in sys.path:
    sys.path.insert(0, str(_SRC_APK))

from core.detection.xml_parser import (  # noqa: E402
    HierarchyMeta,
    compute_tree_signature,
    parse_uia_xml_text,
)


def _multiset_jaccard(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[float, int, int]:
    """(jaccard, intersection_size, union_size)"""
    if not a and not b:
        return 1.0, 0, 0
    if not a or not b:
        return 0.0, 0, len(a) + len(b)
    ca, cb = Counter(a), Counter(b)
    keys = set(ca) | set(cb)
    inter = sum(min(ca[k], cb[k]) for k in keys)
    union = sum(max(ca[k], cb[k]) for k in keys)
    if union == 0:
        return 0.0, 0, 0
    return inter / union, inter, union


def _build_id_trace(
    tree_signature: tuple[str, ...],
    rotation: int,
) -> dict:
    """LayoutTreeScreenIdBuilder.build 와 동일한 직렬화·해싱을 재현하면서
    중간 산출물(raw 문자열, full sha256)을 함께 노출한다. 빌더 자체를 호출
    하면 최종 16자만 받는데, UI 에선 raw → sha → trim 의 흐름을 보여주고
    싶어서 직접 재구성한다."""
    if not tree_signature:
        return {
            "fallback": True,
            "note": "tree_signature 가 비어 있어 HashScreenIdBuilder fallback ('fb_' prefix)",
        }

    raw = f"r{rotation % 4}|" + "|".join(tree_signature)
    sha_full = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {
        "fallback": False,
        "rotation_prefix": f"r{rotation % 4}",
        "raw_preview": raw[:256] + ("…" if len(raw) > 256 else ""),
        "raw_length": len(raw),
        "sha256_full": sha_full,
        "screen_id": sha_full[:16],
        "builder": "LayoutTreeScreenIdBuilder",
    }


def _meta_to_dict(meta: HierarchyMeta) -> dict:
    return {
        "package": meta.package,
        "activity": meta.activity,
        "window_id": meta.window_id,
        "rotation": meta.rotation,
    }


def _element_to_dict(el) -> dict:
    bbox = el.bbox
    return {
        "cls": el.cls,
        "resource_id": el.resource_id,
        "text": el.text,
        "description": el.description,
        "bbox": [bbox.x1, bbox.y1, bbox.x2, bbox.y2],
        "is_scrollable": getattr(el, "is_scrollable", False),
        "is_visible_to_user": getattr(el, "is_visible_to_user", True),
    }


def _load_existing_screens(app_memory_path: Path) -> dict[str, dict]:
    """app_memory.json 에서 screens 만 끌고와 minimal dict 로 보관."""
    payload = json.loads(app_memory_path.read_text(encoding="utf-8"))
    return payload.get("screens", {})


def _existing_tree_signature(
    screen_data: dict,
    app_memory_path: Path,
) -> tuple[str, ...]:
    """저장된 Screen 은 tree_signature 를 직렬화하지 않으므로 xml_path 에서
    lazy 계산. xml_path 가 상대 경로(보통 outputs_APK/.../xml/.xml)라
    repo 루트를 기준으로 해석한다."""
    raw_path = screen_data.get("xml_path")
    if not raw_path:
        return ()
    p = Path(raw_path)
    if not p.is_absolute():
        # app_memory.json 은 outputs_APK/.../json/ 안에 있으므로 두 단계 올라가면 run dir.
        # 그러나 저장된 경로는 보통 'outputs_APK\...\xml\000089.xml' 처럼
        # repo 루트 기준이라, repo 루트(=src_apk 의 부모)를 시도한다.
        repo_root = _SRC_APK.parent
        candidate = repo_root / p
        if candidate.exists():
            p = candidate
        else:
            # 마지막 폴백: app_memory.json 옆 ../xml/<basename>
            run_dir = app_memory_path.parent.parent
            candidate2 = run_dir / "xml" / p.name
            if candidate2.exists():
                p = candidate2
    if not p.exists():
        return ()
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(p.read_text(encoding="utf-8", errors="ignore"))
        return compute_tree_signature(root)
    except Exception:
        return ()


def _trace_matching(
    *,
    cand_meta: HierarchyMeta,
    cand_sig: tuple[str, ...],
    app_memory_path: Path | None,
    threshold: float,
) -> dict:
    """match_screen 의 (1) 버킷 필터 → (2) 후보별 Jaccard → (3) 최선 선택
    단계를 그대로 따라가며, 각 단계의 상태를 dict 로 누적해 반환한다."""
    if app_memory_path is None:
        return {"enabled": False, "reason": "app_memory 경로 미지정"}

    if not app_memory_path.exists():
        return {"enabled": False, "reason": f"app_memory 파일 없음: {app_memory_path}"}

    if not cand_sig:
        return {
            "enabled": True,
            "threshold": threshold,
            "bucket": _bucket_str(cand_meta),
            "reason": "candidate tree_signature 가 비어 있어 매칭 skip → hash fallback",
            "candidates": [],
        }

    screens = _load_existing_screens(app_memory_path)

    cand_pkg = cand_meta.package or None
    cand_act = cand_meta.activity or None
    cand_rot = cand_meta.rotation or 0

    bucket_str = _bucket_str(cand_meta)

    candidates_out: list[dict] = []
    best_key: str | None = None
    best_sim: float = -1.0
    best_inter = 0
    best_union = 0

    for key, sd in screens.items():
        scr_pkg = sd.get("package") or None
        scr_act = sd.get("activity") or None
        scr_rot = int(sd.get("rotation") or 0)

        bucket_match = (
            scr_pkg == cand_pkg
            and scr_act == cand_act
            and scr_rot == cand_rot
        )

        entry = {
            "screen_id": sd.get("screen_id") or key,
            "window_id": sd.get("window_id"),
            "package": scr_pkg,
            "activity": scr_act,
            "rotation": scr_rot,
            "snapshot_count": len(sd.get("snapshots") or []),
            "in_bucket": bucket_match,
        }

        if not bucket_match:
            entry["jaccard"] = None
            entry["intersection"] = None
            entry["union"] = None
            entry["passes_threshold"] = False
            entry["skip_reason"] = "bucket mismatch"
            candidates_out.append(entry)
            continue

        scr_sig = _existing_tree_signature(sd, app_memory_path)
        if not scr_sig:
            entry["jaccard"] = None
            entry["intersection"] = None
            entry["union"] = None
            entry["passes_threshold"] = False
            entry["skip_reason"] = "기존 화면 tree_signature 계산 실패 (xml 없음 등)"
            candidates_out.append(entry)
            continue

        sim, inter, union = _multiset_jaccard(scr_sig, cand_sig)
        entry["jaccard"] = round(sim, 6)
        entry["intersection"] = inter
        entry["union"] = union
        entry["passes_threshold"] = sim >= threshold
        candidates_out.append(entry)

        if sim > best_sim:
            best_sim = sim
            best_key = key
            best_inter = inter
            best_union = union

    # 같은 버킷 안에서만 정렬: in-bucket → jaccard desc, 그 외는 뒤로.
    candidates_out.sort(
        key=lambda x: (
            0 if x["in_bucket"] else 1,
            -(x["jaccard"] if x["jaccard"] is not None else -1.0),
        )
    )

    decision: dict
    if best_key is not None and best_sim >= threshold:
        sd = screens[best_key]
        decision = {
            "matched": True,
            "screen_id": sd.get("screen_id") or best_key,
            "jaccard": round(best_sim, 6),
            "intersection": best_inter,
            "union": best_union,
            "note": "기존 화면과 동일하다고 판정 → 같은 screen_id 재사용",
        }
    elif best_key is not None:
        sd = screens[best_key]
        decision = {
            "matched": False,
            "best_candidate_screen_id": sd.get("screen_id") or best_key,
            "best_jaccard": round(best_sim, 6),
            "threshold": threshold,
            "note": (
                f"버킷 안 최대 Jaccard={best_sim:.3f} 이 임계 {threshold} 미만 "
                f"→ 신규 screen_id 등록"
            ),
        }
    else:
        decision = {
            "matched": False,
            "note": "같은 버킷에 기존 화면 없음 → 신규 screen_id 등록",
        }

    return {
        "enabled": True,
        "threshold": threshold,
        "bucket": bucket_str,
        "total_existing_screens": len(screens),
        "candidates": candidates_out,
        "decision": decision,
    }


def _bucket_str(meta: HierarchyMeta) -> str:
    return (
        f"{meta.package or '?'} | {meta.activity or '?'} | r{(meta.rotation or 0) % 4}"
    )


def _existing_classification(
    *,
    snapshot_id: str | None,
    app_memory_path: Path | None,
) -> dict | None:
    """이 snapshot_id 가 app_memory.json 안 어떤 screen 에 이미 들어있는지
    조회. 매처 시뮬레이션(_trace_matching)이 representative XML(보통 최신
    snapshot)을 기준으로 동작하는 것과 달리, '실제 run 결과로 이 snapshot 이
    어디에 분류돼 있나' 를 보여준다. 둘이 어긋나면 매처가 representative 만
    보는 한계가 드러나는 지점."""
    if not snapshot_id or not app_memory_path or not app_memory_path.exists():
        return None
    try:
        screens = _load_existing_screens(app_memory_path)
    except Exception:
        return None
    for key, sd in screens.items():
        snaps = sd.get("snapshots") or []
        if snapshot_id in snaps:
            return {
                "snapshot_id": snapshot_id,
                "screen_id": sd.get("screen_id") or key,
                "activity": sd.get("activity"),
                "window_id": sd.get("window_id"),
                "total_snapshots_in_screen": len(snaps),
                "representative_xml": sd.get("xml_path"),
            }
    return {
        "snapshot_id": snapshot_id,
        "screen_id": None,
        "note": "이 snapshot 은 app_memory.json 의 어떤 screen 에도 등록돼 있지 않음",
    }


def inspect(
    *,
    xml_text: str,
    xml_label: str,
    app_memory_path: Path | None,
    threshold: float,
    snapshot_id: str | None = None,
) -> dict:
    elements, meta, tree_signature = parse_uia_xml_text(xml_text)
    id_trace = _build_id_trace(tree_signature, meta.rotation)

    return {
        "input": {
            "xml": xml_label,
            "app_memory": str(app_memory_path) if app_memory_path else None,
            "threshold": threshold,
            "snapshot_id": snapshot_id,
        },
        "meta": _meta_to_dict(meta),
        "tree_signature": {
            "total": len(tree_signature),
            "unique": len(set(tree_signature)),
            "preview": list(tree_signature[:20]),
        },
        "id_build": id_trace,
        "elements": {
            "count": len(elements),
            "preview": [_element_to_dict(e) for e in elements[:50]],
        },
        "existing_classification": _existing_classification(
            snapshot_id=snapshot_id,
            app_memory_path=app_memory_path,
        ),
        "match": _trace_matching(
            cand_meta=meta,
            cand_sig=tree_signature,
            app_memory_path=app_memory_path,
            threshold=threshold,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    # Windows 기본 stdout 인코딩(cp949 등)에서 XML 본문에 섞인 특수문자
    # (•, …, 이모지 등)가 JSON 직렬화 시 UnicodeEncodeError 를 일으키므로
    # 강제로 UTF-8 로 재설정한다. Python 3.7+ 지원.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--xml", type=Path, help="XML 파일 경로")
    src.add_argument(
        "--xml-text",
        type=str,
        help="XML 본문 (또는 '@/path'로 파일 지정). stdin 도 지원: '-'",
    )
    ap.add_argument(
        "--app-memory",
        type=Path,
        default=None,
        help="app_memory.json 경로 — 기존 화면들과의 매칭 단계를 출력",
    )
    ap.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="match_threshold (Jaccard). 0이면 매처 비활성, 디폴트 0.6",
    )
    ap.add_argument(
        "--snapshot-id",
        type=str,
        default=None,
        help="이 XML 의 snapshot_id (예: '000182'). 주면 app_memory 안 어느"
        " screen 에 이미 분류돼 있는지 함께 출력. xml 파일명에서 자동 추론.",
    )

    args = ap.parse_args(argv)

    snapshot_id = args.snapshot_id
    if args.xml is not None:
        try:
            xml_text = args.xml.read_text(encoding="utf-8", errors="ignore")
        except FileNotFoundError:
            print(json.dumps({"error": f"xml 파일 없음: {args.xml}"}, ensure_ascii=False))
            return 2
        xml_label = str(args.xml)
        if snapshot_id is None:
            # 'outputs_APK/.../xml/000182.xml' → '000182'
            snapshot_id = args.xml.stem
    else:
        raw = args.xml_text
        if raw == "-":
            xml_text = sys.stdin.read()
            xml_label = "<stdin>"
        elif raw.startswith("@"):
            xml_text = Path(raw[1:]).read_text(encoding="utf-8", errors="ignore")
            xml_label = raw[1:]
        else:
            xml_text = raw
            xml_label = "<inline>"

    try:
        result = inspect(
            xml_text=xml_text,
            xml_label=xml_label,
            app_memory_path=args.app_memory,
            threshold=args.threshold,
            snapshot_id=snapshot_id,
        )
    except Exception as e:
        print(json.dumps({"error": f"inspect 실패: {e}"}, ensure_ascii=False))
        return 1

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
