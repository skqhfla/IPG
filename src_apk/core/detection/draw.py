from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence, Tuple, Union

from PIL import Image, ImageDraw, ImageFont

from core.app_types import BBox, Element


BBoxLike = Union[BBox, Tuple[int, int, int, int]]


def _ensure_bbox(b: BBoxLike) -> BBox:
    if isinstance(b, BBox):
        return b

    if isinstance(b, (tuple, list)) and len(b) == 4:
        x1, y1, x2, y2 = b
        return BBox(
            x1=int(x1),
            y1=int(y1),
            x2=int(x2),
            y2=int(y2),
        )

    raise TypeError(f"Unsupported bbox type: {type(b)}")


def _build_label(e: Element) -> str:
    parts: list[str] = []

    element_id = getattr(e, "element_id", None)
    if element_id:
        parts.append(str(element_id))

    source = getattr(e, "source", None)
    if source:
        parts.append(f"src={source}")

    if not parts:
        return "unknown"

    return " | ".join(parts)


def draw_elements_on_image(
    *,
    image_path: Path,
    elements: Sequence[Element],
    out_path: Path,
    title: Optional[str] = None,
) -> Path:
    """
    Draw bounding boxes + labels on screenshot.

    Current project assumptions:
    - Element has `bbox`
    - BBox has x1, y1, x2, y2
    - Optional fields: cls, element_id, text, source
    """
    image_path = Path(image_path)
    out_path = Path(out_path)

    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    for e in elements:
        bbox = _ensure_bbox(e.bbox)
        x1, y1, x2, y2 = bbox.x1, bbox.y1, bbox.x2, bbox.y2

        draw.rectangle([x1, y1, x2, y2], outline="red", width=2)

        label = _build_label(e)

        text_x = x1 + 2
        text_y = max(0, y1 - 12)

        if font:
            draw.text((text_x, text_y), label, fill="red", font=font)
        else:
            draw.text((text_x, text_y), label, fill="red")

    if title:
        if font:
            draw.text((10, 10), str(title), fill="red", font=font)
        else:
            draw.text((10, 10), str(title), fill="red")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)

    return out_path