#src/core/graph/utg.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from core.app_types import EventKey
from core.app_types.event_types import EventType


@dataclass(frozen=True, slots=True)
class UTGEdge:
    """
    screen_id 기반 화면 전이 edge
    """
    src: str
    dst: str
    event_type: EventType
    event_key: EventKey | None = None
    description: Optional[str] = None

    src_snapshot_id: Optional[str] = None
    dst_snapshot_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "src": self.src,
            "dst": self.dst,
            "event_type": self.event_type.value,
            "event_key": self.event_key,
            "description": self.description,
            "src_snapshot_id": self.src_snapshot_id,
            "dst_snapshot_id": self.dst_snapshot_id,
        }


@dataclass(slots=True)
class UTGNode:
    """
    screen_id로 식별되는 unique screen node.
    하나의 node는 여러 snapshot을 가질 수 있다.
    """
    screen_id: str
    index: int
    screenshot_path : str

    snapshots: Set[str] = field(default_factory=set)
    first_snapshot_id: Optional[str] = None
    last_snapshot_id: Optional[str] = None

    def add_snapshot(self, snapshot_id: str) -> None:
        if not snapshot_id:
            return
        self.snapshots.add(snapshot_id)
        if self.first_snapshot_id is None:
            self.first_snapshot_id = snapshot_id
        self.last_snapshot_id = snapshot_id

    def to_dict(self) -> dict:
        return {
            "screen_id": self.screen_id,
            "index": self.index,
            "snapshots": sorted(self.snapshots),
            "first_snapshot_id": self.first_snapshot_id,
            "last_snapshot_id": self.last_snapshot_id,
        }


@dataclass(slots=True)
class UTGGraphData:
    """
    UI Transition Graph
    - nodes key: screen_id
    - edges: screen_id -> screen_id
    """
    nodes: Dict[str, UTGNode] = field(default_factory=dict)
    edges: List[UTGEdge] = field(default_factory=list)
    _next_index: int = 0

    def get_or_create_node(
        self,
        screen_id: str,
        *,
        snapshot_id: Optional[str] = None,
        screenshot_path: Optional[str] = None,
    ) -> UTGNode:
        node = self.nodes.get(screen_id)
        if node is None:
            node = UTGNode(
                screen_id=screen_id,
                index=self._next_index,
                screenshot_path=screenshot_path,
            )
            self.nodes[screen_id] = node
            self._next_index += 1

        else:
            if screenshot_path and not node.screenshot_path:
                node.screenshot_path = screenshot_path

        if snapshot_id:
            node.add_snapshot(snapshot_id)

        return node

    def add_transition(
        self,
        *,
        src_screen: str,
        dst_screen: str,
        event_type: EventType,
        event_key: EventKey | None = None,
        description: Optional[str] = None,
        src_snapshot_id: Optional[str] = None,
        dst_snapshot_id: Optional[str] = None,
        src_screenshot_path: Optional[str] = None,
        dst_screenshot_path: Optional[str] = None,
    ) -> UTGEdge:
        self.get_or_create_node(src_screen, snapshot_id=src_snapshot_id, screenshot_path=src_screenshot_path)
        self.get_or_create_node(dst_screen, snapshot_id=dst_snapshot_id, screenshot_path=dst_screenshot_path)

        edge = UTGEdge(
            src=src_screen,
            dst=dst_screen,
            event_type=event_type,
            event_key=event_key,
            description=description,
            src_snapshot_id=src_snapshot_id,
            dst_snapshot_id=dst_snapshot_id,
        )

        if edge not in self.edges:
            self.edges.append(edge)

        return edge

    def to_dict(self) -> dict:
        return {
            "nodes": [self.nodes[k].to_dict() for k in sorted(self.nodes.keys())],
            "edges": [e.to_dict() for e in self.edges],
        }