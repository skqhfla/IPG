from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from core.app_types import BBox
from core.detection.ocr import OCREngine, OCRItem


@dataclass(slots=True)
class PaddleOCREngine(OCREngine):
    lang: str = "korean"
    gpu: bool = False
    logger: Any = None

    name: str = "paddleocr"
    _ocr: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        from paddleocr import PaddleOCR

        if self.logger:
            self.logger.info(
                "[PaddleOCREngine] init PaddleOCR lang=%s gpu=%s",
                self.lang,
                self.gpu,
            )

        try:
            device = "gpu" if self.gpu else "cpu"
            self._ocr = PaddleOCR(lang=self.lang, device=device)
            return
        except Exception as e:
            if self.logger:
                self.logger.warning("[PaddleOCREngine] PaddleOCR(device=..) failed: %s", e)

        try:
            self._ocr = PaddleOCR(lang=self.lang, use_gpu=bool(self.gpu))
            return
        except Exception as e:
            if self.logger:
                self.logger.warning("[PaddleOCREngine] PaddleOCR(use_gpu=..) failed: %s", e)

        self._ocr = PaddleOCR(lang=self.lang)

    def read(self, *, image_path: str) -> list[OCRItem]:
        log = self.logger

        if log:
            log.info("[PaddleOCREngine] read path=%s exists=%s", image_path, Path(image_path).exists())

        raw = None
        try:
            raw = self._call_engine(image_path)
        except Exception as e:
            if log:
                log.warning("[PaddleOCREngine] ocr(path) failed: %s", e)

        if not raw:
            if log:
                log.warning("[PaddleOCREngine] raw empty -> fallback to numpy image")
            image = self._load_image_bgr(image_path)
            try:
                raw = self._call_engine(image)
            except Exception as e:
                if log:
                    log.warning("[PaddleOCREngine] ocr(numpy) failed: %s", e)
                raw = None

        if not raw:
            return []

        items = self._to_items_from_paddleocr_raw(raw)
        if items:
            return items

        return self._to_items_from_predict_raw(raw)

    def _call_engine(self, inp: Any) -> Any:
        if hasattr(self._ocr, "ocr"):
            try:
                return self._ocr.ocr(inp, cls=True)
            except Exception:
                return self._ocr.ocr(inp)

        if hasattr(self._ocr, "predict"):
            return self._ocr.predict(inp)

        raise RuntimeError(f"Unsupported OCR engine object: {type(self._ocr)}")

    def _load_image_bgr(self, image_path: str) -> np.ndarray:
        image = cv2.imread(image_path)
        if image is not None:
            return image

        rgb = Image.open(image_path).convert("RGB")
        arr = np.array(rgb)
        return arr[:, :, ::-1]

    def _to_items_from_paddleocr_raw(self, raw: Any) -> list[OCRItem]:
        items: list[OCRItem] = []

        if not raw:
            return items

        lines = raw[0] if isinstance(raw, list) and raw and isinstance(raw[0], list) else raw
        if not isinstance(lines, list):
            return items

        for line in lines:
            try:
                box = line[0]
                text_conf = line[1]
                text = str(text_conf[0]).strip()
                conf = float(text_conf[1]) if len(text_conf) > 1 else 0.0

                if not text:
                    continue

                pts = np.asarray(box, dtype=np.float32).reshape(-1, 2)
                xs = pts[:, 0]
                ys = pts[:, 1]

                items.append(
                    OCRItem(
                        bbox=BBox(
                            x1=int(xs.min()),
                            y1=int(ys.min()),
                            x2=int(xs.max()),
                            y2=int(ys.max()),
                        ),
                        text=text,
                        confidence=conf,
                        engine=self.name,
                    )
                )
            except Exception:
                continue

        return items

    def _to_items_from_predict_raw(self, raw: Any) -> list[OCRItem]:
        items: list[OCRItem] = []

        if not raw:
            return items

        if isinstance(raw, list) and raw and isinstance(raw[0], dict):
            for item in raw:
                try:
                    rec_texts = item.get("rec_texts")
                    rec_scores = item.get("rec_scores")
                    rec_polys = self._pick_first_not_none(item.get("rec_polys"), item.get("dt_polys"))
                    rec_boxes = self._pick_first_not_none(item.get("rec_boxes"), item.get("dt_boxes"))

                    if not isinstance(rec_texts, list) or not rec_texts:
                        continue

                    if not isinstance(rec_scores, list):
                        rec_scores = [0.0] * len(rec_texts)

                    if rec_polys is not None:
                        try:
                            n_polys = len(rec_polys)
                        except Exception:
                            n_polys = 0

                        n = min(len(rec_texts), len(rec_scores), n_polys)
                        added = 0

                        for i in range(n):
                            text = str(rec_texts[i]).strip()
                            if not text:
                                continue

                            conf = float(rec_scores[i]) if i < len(rec_scores) else 0.0
                            poly = rec_polys[i]

                            pts = np.asarray(poly, dtype=np.float32).reshape(-1, 2)
                            xs = pts[:, 0]
                            ys = pts[:, 1]

                            items.append(
                                OCRItem(
                                    bbox=BBox(
                                        x1=int(xs.min()),
                                        y1=int(ys.min()),
                                        x2=int(xs.max()),
                                        y2=int(ys.max()),
                                    ),
                                    text=text,
                                    confidence=conf,
                                    engine=self.name,
                                )
                            )
                            added += 1

                        if added > 0:
                            continue

                    if rec_boxes is not None:
                        boxes_arr = np.asarray(rec_boxes)

                        if boxes_arr.ndim == 1 and boxes_arr.size >= 4:
                            boxes_arr = boxes_arr.reshape(1, -1)

                        if boxes_arr.ndim != 2 or boxes_arr.shape[1] < 4:
                            continue

                        n = min(len(rec_texts), len(rec_scores), int(boxes_arr.shape[0]))

                        for i in range(n):
                            text = str(rec_texts[i]).strip()
                            if not text:
                                continue

                            conf = float(rec_scores[i]) if i < len(rec_scores) else 0.0
                            x1, y1, x2, y2 = map(int, boxes_arr[i, :4].tolist())

                            items.append(
                                OCRItem(
                                    bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2),
                                    text=text,
                                    confidence=conf,
                                    engine=self.name,
                                )
                            )
                except Exception:
                    continue

        return items

    def _pick_first_not_none(self, *vals: Any) -> Any:
        for value in vals:
            if value is not None:
                return value
        return None