from __future__ import annotations

import torch

from core.config import ComputeDevice, OcrMode, UiDetectionMode
from core.config.model_paths import MODEL_PATH
from core.detection.base import BaseDetector
from core.detection.mode.hybrid_detector import HybridDetector
from core.detection.mode.uia_detector import UIAutomatorDetector
from core.detection.mode.yolo_detector import YOLODetector
from core.detection.models import YoloV8Adapter
from core.detection.ocr import PaddleOCREngine
from core.runtime.context import RuntimeContext


def create_detector(ctx: RuntimeContext) -> BaseDetector:
    mode = ctx.settings.detection.ui_detection_mode

    if mode == UiDetectionMode.UIAUTOMATOR:
        return UIAutomatorDetector(ctx)

    if mode == UiDetectionMode.YOLO:
        yolo_model = _init_yolo_model(ctx)
        ocr_engine = _init_ocr_engine(ctx)
        return YOLODetector(
            ctx,
            yolo_model=yolo_model,
            ocr_engine=ocr_engine,
        )

    if mode == UiDetectionMode.HYBRID:
        yolo_model = _init_yolo_model(ctx)
        ocr_engine = _init_ocr_engine(ctx)
        return HybridDetector(
            ctx,
            yolo_model=yolo_model,
            ocr_engine=ocr_engine,
        )

    raise ValueError(f"Unsupported detection mode: {mode}")


def _init_yolo_model(ctx: RuntimeContext) -> YoloV8Adapter:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"YOLO model file not found: {MODEL_PATH}")

    device = "cpu"
    if (
        ctx.settings.runtime.compute_device == ComputeDevice.GPU
        and torch.cuda.is_available()
    ):
        device = "0"

    return YoloV8Adapter(
        weights=str(MODEL_PATH),
        conf=0.25,
        iou=0.7,
        device=device,
        max_det=300,
    )

def _init_ocr_engine(ctx: RuntimeContext):
    mode = ctx.settings.detection.ocr_mode

    if mode == OcrMode.NONE:
        return None

    if mode == OcrMode.PADDLE:
        return PaddleOCREngine(
            lang="korean",
            gpu=(ctx.settings.runtime.compute_device == ComputeDevice.GPU),
            logger=ctx.logger,
        )

    if mode == OcrMode.TESSERACT:
        # TODO: Tesseract 엔진 wrapper 추가 시 연결
        raise NotImplementedError("Tesseract OCR engine wrapper is not implemented yet.")

    raise ValueError(f"Unsupported OCR mode: {mode}")