from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScreenIdKind(str, Enum):
    LAYOUT_TREE = "layout_tree"
    LAYOUT_BBOX = "layout_bbox"
    HASH = "hash"


class UiDetectionMode(str, Enum):
    UIAUTOMATOR = "uiautomator"
    YOLO = "yolo"
    HYBRID = "hybrid"


class OcrMode(str, Enum):
    NONE = "none"
    PADDLE = "paddle"
    TESSERACT = "tesseract"


class ScreenTransitionMode(str, Enum):
    SCREEN_ID = "screen_id"


class ComputeDevice(str, Enum):
    CPU = "cpu"
    GPU = "gpu"


class LogMode(str, Enum):
    DEBUG = "debug"
    NORMAL = "normal"
    NO_LOG = "no-log"


@dataclass(slots=True)
class TraversalConfig:
    loop_threshold: int
    back_threshold: int
    same_screen_threshold: int
    timeout_sec: int
    interval_sec: int


@dataclass(slots=True)
class DetectionConfig:
    ocr_mode: OcrMode
    ui_detection_mode: UiDetectionMode
    screen_transition_mode: ScreenTransitionMode
    iou_threshold: float


@dataclass(slots=True)
class PacketConfig:
    packet_threshold: int
    capture_time_sec: int


@dataclass(slots=True)
class InputConfig:
    swipe_start_ratio: float
    swipe_end_ratio: float


@dataclass(slots=True)
class RuntimeConfig:
    compute_device: ComputeDevice
    log_mode: LogMode
    enable_utg: bool
    draw_detection: bool
    foreground_poll_interval_sec: float = 1.5


@dataclass(slots=True)
class ScreenIdConfig:
    kind: ScreenIdKind
    algorithm: str
    threshold: float | None = None


@dataclass(slots=True)
class Settings:
    traversal: TraversalConfig
    detection: DetectionConfig
    packet: PacketConfig
    input: InputConfig
    runtime: RuntimeConfig
    screen_id: ScreenIdConfig