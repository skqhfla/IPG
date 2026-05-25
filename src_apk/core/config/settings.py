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
    node_loop_repetition: int
    stability_poll_interval_ms: int
    stability_max_wait_sec: float
    stability_required_matches: int
    excluded_streak_threshold: int = 3
    swipe_directions: tuple[str, ...] = ("down", "up")
    swipe_settle_ms: int = 500
    # 연속 스크롤 viewport 간 최소 겹침 비율 (0.3 → 30% overlap 보장).
    scroll_overlap_ratio: float = 0.3
    # 스크롤 swipe 지속시간(ms). 길수록 fling(관성 스크롤)이 줄어
    # 한 번에 건너뛰는 양이 작아진다.
    scroll_swipe_duration_ms: int = 800
    # tap/back 없이 연속으로 허용하는 최대 스크롤 횟수. 초과 시 policy가
    # 스크롤 후보를 건너뛰고 tap/back으로 강제 전환 → 무한 스크롤 루프 차단.
    max_consecutive_scrolls: int = 12


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
    # 화면 동일성 매칭(window_id+activity 버킷 내 resource-id Jaccard)
    # 임계값. 이 이상이면 같은 화면으로 묶음. 0이면 매칭 비활성(해시만 사용).
    match_threshold: float = 0.6


@dataclass(slots=True)
class Settings:
    traversal: TraversalConfig
    detection: DetectionConfig
    packet: PacketConfig
    input: InputConfig
    runtime: RuntimeConfig
    screen_id: ScreenIdConfig