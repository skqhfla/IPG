from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from core.app_types import BBox, Element


_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


@dataclass(frozen=True, slots=True)
class HierarchyMeta:
    """
    a11y dump XML의 <hierarchy> 루트 속성 — 화면 식별에 쓰인다.
    device_listener APK가 emit (구버전 APK면 None).
    """
    window_id: int | None = None
    activity: str | None = None
    # 실제 렌더된 윈도우의 package. 타겟 앱 외 화면(런처/시스템 다이얼로그/외부 앱)이
    # foreground로 튀어 dump가 떠도, 여기에 그 패키지가 박혀 나오므로 게이팅에 쓴다.
    package: str | None = None
    # 디스플레이 회전 (0/1/2/3 = 0°/90°/180°/270°). a11y dump가 이 회전 기준의
    # 좌표로 bounds를 보고하므로, normalize용 screen_wh도 같은 회전으로 swap해야 한다.
    rotation: int = 0


def _parse_hierarchy_meta(root: ET.Element) -> HierarchyMeta:
    wid_raw = root.get("window-id")
    window_id: int | None = None
    if wid_raw is not None:
        try:
            window_id = int(wid_raw)
        except ValueError:
            window_id = None

    act_raw = (root.get("activity") or "").strip()
    activity = act_raw or None

    pkg_raw = (root.get("package") or "").strip()
    package = pkg_raw or None

    rot_raw = root.get("rotation")
    rotation = 0
    if rot_raw is not None:
        try:
            rotation = int(rot_raw) % 4
        except ValueError:
            rotation = 0

    return HierarchyMeta(
        window_id=window_id,
        activity=activity,
        package=package,
        rotation=rotation,
    )


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
    # a11y 노드가 음수 면적/뒤집힌 bounds로 나오는 케이스 (off-screen, 비정상 레이아웃)
    if x1 > x2 or y1 > y2:
        return None
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


# content-desc 동적 패턴 정규화. snapshot마다 흔들리는 값(시간/카운터/네트워크
# 속도 등)을 placeholder로 치환해, 라벨이 의미적으로 같은 노드끼리 같은 hash를
# 가지도록 한다. 안정적인 라벨(버튼명 등)은 그대로 유지되어 화면 분리에 기여.
_RE_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_RE_DATE = re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b")
_RE_NUM = re.compile(r"(?<![\w])-?\d[\d,]*(?![\w])")


def _normalize_desc(s: str) -> str:
    if not s:
        return ""
    s = _RE_TIME.sub("<TIME>", s)
    s = _RE_DATE.sub("<DATE>", s)
    s = _RE_NUM.sub("<N>", s)
    return s


def compute_tree_signature(root: ET.Element) -> tuple[str, ...]:
    """
    XML hierarchy를 canonical subtree-hash multiset으로 변환한다.

    각 <node>의 subtree를 `class[d:normalized_desc](sorted_child_hashes)`
    형태로 직렬화해 해시한 뒤, 모든 <node>에서 나온 해시를 수집한다.
    형제 순서가 흔들려도 안정적이고, 노드 라벨에 정규화된 content-desc를
    섞어 같은 컨테이너 형상이라도 노출된 라벨(버튼명 등)이 다르면 다른
    화면으로 분리한다.

    desc 정규화는 시간/날짜/숫자 카운터(`<TIME>/<DATE>/<N>`)만 치환하므로
    네트워크 속도·timestamp 같은 동적 값은 노이즈가 되지 않고, '음소거'·
    '전체화면' 같은 안정 라벨은 그대로 hash에 들어가 화면 변화를 잡는다.
    """
    bag: list[str] = []
    _subtree_hash(root, bag)
    return tuple(sorted(bag))


def _subtree_hash(node: ET.Element, out: list[str]) -> str:
    label = ""
    is_real_node = (node.tag == "node")
    if is_real_node:
        cls = simplify_android_class(node.attrib.get("class") or "")
        desc = _normalize_desc((node.attrib.get("content-desc") or "").strip())
        label = f"{cls}[d:{desc}]" if desc else cls

    child_hashes = [_subtree_hash(c, out) for c in list(node)]
    child_hashes.sort()

    serial = f"{label}({','.join(child_hashes)})"
    h = hashlib.sha1(serial.encode("utf-8")).hexdigest()[:12]

    # <hierarchy> 루트는 시그니처에 포함하지 않는다 — 모든 화면에 공통이라 noise.
    if is_real_node:
        out.append(h)
    return h


def parse_uia_xml(
    xml_path: Path,
) -> tuple[list[Element], HierarchyMeta, tuple[str, ...]]:
    try:
        xml_text = xml_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return [], HierarchyMeta(), ()

    return parse_uia_xml_text(xml_text)


def parse_uia_xml_text(
    xml_text: str,
) -> tuple[list[Element], HierarchyMeta, tuple[str, ...]]:
    xml_text = trim_to_xml(xml_text)
    root = ET.fromstring(xml_text)

    meta = _parse_hierarchy_meta(root)
    tree_signature = compute_tree_signature(root)
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

            is_scrollable = (attrs.get("scrollable", "").lower() == "true")

            # unlabeled layout / viewgroup는 직접 element로 만들지 않고 자식만 탐색.
            # 단, scrollable container는 swipe target이 되어야 하므로 유지.
            if (
                is_layout(class_name)
                and not has_meaningful_content(attrs)
                and not is_scrollable
            ):
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
                    is_scrollable=is_scrollable,
                )
            )

        for child in list(node):
            walk(child)

    walk(root)
    return elements, meta, tree_signature