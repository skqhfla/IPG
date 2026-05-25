#src/core/models/yolov8.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Sequence

from core.app_types import BBox, Element

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None  # type: ignore


@dataclass(slots=True)
class YoloV8Adapter:
    """
    ultralytics YOLOv8 -> list[Element]

    - weights: local model weight path
    - conf: confidence threshold
    - iou: NMS IoU threshold
    - device: "cpu", "cuda", "0" 등 ultralytics 규칙 사용
    - max_det: maximum number of detections
    """
    weights: str
    conf: float = 0.25
    iou: float = 0.7
    device: str = "cpu"
    max_det: int = 300

    name: str = "yolov8"
    _model: Any = None

    def __post_init__(self) -> None:
        if YOLO is None:
            raise RuntimeError(
                "ultralytics YOLO is not available. Install the 'ultralytics' package first."
            )

        self._model = YOLO(self.weights)

    def detect_elements(self, *, image_path: str) -> Sequence[Element]:
        results = self._model.predict(
            source=image_path,
            conf=self.conf,
            iou=self.iou,
            device=self.device,
            max_det=self.max_det,
            verbose=False,
        )

        elements: List[Element] = []

        if not results:
            return elements

        result = results[0]
        names = getattr(result, "names", None) or {}

        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return elements

        xyxy = boxes.xyxy
        cls = boxes.cls

        xyxy_list = xyxy.tolist() if hasattr(xyxy, "tolist") else list(xyxy)
        cls_list = cls.tolist() if hasattr(cls, "tolist") else list(cls)

        for (x1, y1, x2, y2), class_idx in zip(xyxy_list, cls_list):
            bbox = BBox(
                x1=int(x1),
                y1=int(y1),
                x2=int(x2),
                y2=int(y2),
            )

            class_id = int(class_idx)
            class_name = str(names.get(class_id, class_id))

            elements.append(
                Element(
                    element_id="",
                    cls=class_name,
                    bbox=bbox,
                    source="yolo",
                )
            )

        return elements