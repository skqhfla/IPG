from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.adb.a11y_event_listener import A11yEventListener
from core.adb.device import ADBDevice
from core.adb.netstats import NetstatsSampler
from core.app_types.run_meta import AppMeta, DeviceMeta
from core.app_types.screen import Screen
from core.config import Settings
from core.graph.recover_graph import RecoverGraph
from core.graph.utg import UTGGraphData
from core.memory.app_memory import AppMemoryStore
from core.memory.packet_memory import PacketMemoryStore
from core.memory.screen_memory import ScreenMemoryStore
from core.persistence.memory_saver import MemorySaver
from core.utils.path_manager import PathManager
from core.runtime.monitor.foreground_monitor import ForegroundState


@dataclass(slots=True)
class RuntimeContext:
    settings: Settings
    paths: PathManager

    adb_device: ADBDevice
    target_app_name: str
    target_package: str
    target_uid: int | None = None
    launcher_activity: str | None = None
    netstats_sampler: NetstatsSampler | None = None

    app_memory: AppMemoryStore = field(default_factory=AppMemoryStore)
    screen_memory: ScreenMemoryStore = field(default_factory=ScreenMemoryStore)
    packet_memory: PacketMemoryStore = field(default_factory=PacketMemoryStore)
    utg: UTGGraphData = field(default_factory=UTGGraphData)
    # 비-타겟 dump → force-recover 이력. app_memory/UTG와 분리 보존.
    recover_graph: RecoverGraph = field(default_factory=RecoverGraph)

    foreground_state: ForegroundState = field(default_factory=ForegroundState)

    device_meta: DeviceMeta | None = None
    app_meta: AppMeta | None = None

    detector: Any = None
    executor: object | None = None
    traverser: object | None = None

    start_ts: str | None = None
    end_ts: str | None = None
    duration_sec: float | None = None

    current_screen_key: str | None = None
    previous_screen_key: str | None = None

    current_screen: Screen | None = None
    previous_screen: Screen | None = None

    # 가장 최근에 register된 detection의 snapshot_id (파일명, 예: "000007").
    # packet_memory가 통합된 screen_id 외에 어떤 snapshot에서 측정되었는지도
    # 함께 기록할 수 있게 step 사이에 유지한다.
    current_snapshot_id: str | None = None

    screen_visit_count: dict[str, int] = field(default_factory=dict)

    app_restart_count: int = 0
    foreground_recover_count: int = 0
    excluded_escape_count: int = 0
    terminal_reason: str | None = None

    step_count: int = 0
    same_screen_streak: int = 0
    excluded_streak: int = 0
    # tap/back 없이 연속된 스크롤 swipe 횟수 (무한 스크롤 루프 차단용).
    consecutive_scroll_count: int = 0

    screen_history: list[str] = field(default_factory=list)

    excluded_screen_ids: set[str] = field(default_factory=set)

    logger: Any = None

    a11y_listener: A11yEventListener | None = None
    memory_saver: MemorySaver | None = None

    # transition 게이트 상태: 직전 detection 시점의 screen_id 값과 listener
    # transition_seq 스냅샷. 다음 detection 진입 시 비교해 카운터 증가가 없으면
    # 매처를 건너뛰고 같은 screen_id 를 재사용 — intra-screen 갱신(스크롤·
    # 컨텐츠 변화)으로 트리 시그니처가 살짝 흔들려도 screen_id 가 유지된다.
    last_screen_id_value: str | None = None
    last_transition_seq: int = 0
    # logcat 드롭 방어선: XML 의 identity 속성(activity/window_id/rotation)
    # 직전 값. logcat 이 STATE_CHANGED 를 놓쳐 trans_seq 가 변화 없음에도 dump
    # 자체의 identity 가 바뀌었다면 게이트를 강제 해제하고 매처를 호출. 매처는
    # window_id 를 버킷에서 제외하므로 같은 화면 재방문(window_id 만 새로 발급
    # 받은 케이스)은 Jaccard 로 자연히 합쳐지고, 진짜 다른 화면(Jaccard 낮음)
    # 만 분리된다.
    last_activity: str | None = None
    last_package: str | None = None
    last_rotation: int = 0
    last_window_id: int | None = None
    # 직전 등록된 화면의 visible-only tree_signature. 게이트 4속성
    # (activity/window_id/package/rotation)이 모두 일치하더라도 본문 fragment
    # 가 통째로 교체된 케이스(Xiaomi 하단 탭 — STATE_CHANGED/SELECTED 이벤트가
    # 안 떠 trans_seq·identity 모두 변화 없음)를 잡기 위해, content Jaccard 가
    # match_threshold 미만이면 게이트를 해제해 매처를 호출한다.
    last_tree_signature: tuple[str, ...] = field(default_factory=tuple)

    @property
    def screen_wh(self) -> tuple[int, int] | None:
        if self.device_meta is None:
            return None
        return (
            int(self.device_meta.screen_width),
            int(self.device_meta.screen_height),
        )

    def effective_screen_wh(self, rotation: int = 0) -> tuple[int, int] | None:
        """
        주어진 회전(0/1/2/3)에서의 실제 디스플레이 (width, height).
        a11y dump의 bounds·screencap이 회전된 좌표계로 보고되므로, 90°/270°에서는
        device-native portrait wh를 swap해 반환한다.
        """
        wh = self.screen_wh
        if wh is None:
            return None
        if rotation % 2 == 1:
            return (wh[1], wh[0])
        return wh