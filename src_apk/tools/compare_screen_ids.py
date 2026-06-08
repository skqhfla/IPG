"""
여러 XML 한 묶음에 대해 screen_id 빌드 결과 + tree_signature 통계 + 페어와이즈
Jaccard matrix 를 한 번에 계산해 JSON 으로 stdout 에 출력하는 CLI.

각 XML 을 한 번씩만 파싱하고 tree_signature 를 캐시한 다음 N×N 매트릭스를
만들기 때문에, inspect_screen_id 를 N 번 따로 호출하는 것보다 빠르다.

usage:
  python -m tools.compare_screen_ids \
      --xml d:/.../xml/000005.xml \
      --xml d:/.../xml/000014.xml \
      --xml d:/.../xml/000182.xml \
      [--snapshot-id 000005 ...]   # 명시 안 하면 파일 stem 으로
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

_THIS = Path(__file__).resolve()
_SRC_APK = _THIS.parent.parent
if str(_SRC_APK) not in sys.path:
    sys.path.insert(0, str(_SRC_APK))

from core.detection.xml_parser import parse_uia_xml_text  # noqa: E402


def _multiset_jaccard(
    a: tuple[str, ...], b: tuple[str, ...]
) -> tuple[float, int, int]:
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


def _build_screen_id(
    tree_signature: tuple[str, ...], rotation: int
) -> tuple[str, bool]:
    """(screen_id, is_fallback)"""
    if not tree_signature:
        # inspect_screen_id 의 LayoutTreeScreenIdBuilder fallback 흉내 — 실제론
        # HashScreenIdBuilder 가 elements bbox 로 hash 하지만, compare 입력은
        # XML text 만 있으면 되므로 빈 시그니처는 단순히 'fb_empty' 로 표기.
        return "fb_empty", True
    raw = f"r{rotation % 4}|" + "|".join(tree_signature)
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return sha[:16], False


def compare(xml_paths: list[Path], snapshot_ids: list[str]) -> dict:
    items: list[dict] = []
    sigs: list[tuple[str, ...]] = []
    for path, sid in zip(xml_paths, snapshot_ids):
        try:
            xml_text = path.read_text(encoding="utf-8", errors="ignore")
            _, meta, sig = parse_uia_xml_text(xml_text)
        except Exception as e:
            items.append({
                "snapshot_id": sid,
                "xml": str(path),
                "error": str(e),
            })
            sigs.append(())
            continue
        screen_id, fallback = _build_screen_id(sig, meta.rotation)
        items.append({
            "snapshot_id": sid,
            "xml": str(path),
            "screen_id": screen_id,
            "fallback": fallback,
            "meta": {
                "package": meta.package,
                "activity": meta.activity,
                "window_id": meta.window_id,
                "rotation": meta.rotation,
            },
            "tree_signature": {
                "total": len(sig),
                "unique": len(set(sig)),
            },
        })
        sigs.append(sig)

    # N×N Jaccard matrix
    n = len(items)
    matrix: list[list[dict | None]] = [[None] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                matrix[i][j] = {
                    "jaccard": 1.0,
                    "intersection": len(sigs[i]),
                    "union": len(sigs[i]),
                }
            elif j < i:
                # 대칭 — 위쪽 값 재사용
                matrix[i][j] = matrix[j][i]
            else:
                sim, inter, union = _multiset_jaccard(sigs[i], sigs[j])
                matrix[i][j] = {
                    "jaccard": round(sim, 6),
                    "intersection": inter,
                    "union": union,
                }

    # 모든 snapshot 에 공통인 sub-hash 와 각자만 가진 것의 개수
    if n > 0:
        all_set = set(sigs[0])
        for s in sigs[1:]:
            all_set &= set(s)
        common_count = len(all_set)
    else:
        common_count = 0

    return {
        "snapshots": items,
        "pairwise_jaccard": matrix,
        "common_sub_hashes": common_count,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--xml",
        type=Path,
        action="append",
        required=True,
        help="XML 파일 경로. 여러 번 지정 가능.",
    )
    ap.add_argument(
        "--snapshot-id",
        type=str,
        action="append",
        default=[],
        help="각 --xml 에 대응하는 snapshot_id. 미지정 시 파일 stem 으로.",
    )
    args = ap.parse_args(argv)

    xml_paths: list[Path] = args.xml
    snapshot_ids: list[str] = list(args.snapshot_id or [])
    while len(snapshot_ids) < len(xml_paths):
        snapshot_ids.append(xml_paths[len(snapshot_ids)].stem)
    snapshot_ids = snapshot_ids[: len(xml_paths)]

    try:
        result = compare(xml_paths, snapshot_ids)
    except Exception as e:
        print(json.dumps({"error": f"compare 실패: {e}"}, ensure_ascii=False))
        return 1

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
