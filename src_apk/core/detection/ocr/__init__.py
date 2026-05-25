from core.detection.ocr.base import OCRItem, OCREngine
from core.detection.ocr.eaey_ocr import EasyOCREngine
from core.detection.ocr.paddle_ocr import PaddleOCREngine

__all__ = [
    "OCRItem",
    "OCREngine",
    "EasyOCREngine",
    "PaddleOCREngine",
]