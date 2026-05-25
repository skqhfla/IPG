from __future__ import annotations

from dataclasses import dataclass

import easyocr

from core.app_types import BBox
from core.detection.ocr import OCREngine, OCRItem


@dataclass(slots=True)
class EasyOCREngine(OCREngine):
    name: str = "easyocr"
    languages: tuple[str, ...] = ("ko", "en")
    gpu: bool = False

    def __post_init__(self) -> None:
        self._reader = easyocr.Reader(list(self.languages), gpu=self.gpu)

    def read(self, *, image_path: str) -> list[OCRItem]:
        results = self._reader.readtext(image_path)
        items: list[OCRItem] = []

        for result in results:
            try:
                bbox, text, conf = result
                xs = [point[0] for point in bbox]
                ys = [point[1] for point in bbox]

                items.append(
                    OCRItem(
                        bbox=BBox(
                            x1=int(min(xs)),
                            y1=int(min(ys)),
                            x2=int(max(xs)),
                            y2=int(max(ys)),
                        ),
                        text=str(text).strip(),
                        confidence=float(conf),
                        engine=self.name,
                    )
                )
            except Exception:
                continue

        return items