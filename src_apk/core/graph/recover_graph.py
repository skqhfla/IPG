#src/core/graph/recover_graph.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(slots=True)
class RecoverEvent:
    """
    비-타겟 화면이 dump되어 force-recover가 일어난 단일 이벤트.

    필드는 게이트 시점에 알 수 있는 것만 즉시 채우고, 다음 target detection
    성공 시점에 dst_screen_key / dst_snapshot_id를 lazy로 채운다.
    """
    step: int
    timestamp: str
    stage: str                           # 'before' | 'after'
    snapshot_id: str                     # 비-타겟 dump의 snapshot_id

    non_target_package: Optional[str] = None
    non_target_activity: Optional[str] = None

    # stage='after'에서만 의미. before 단계는 current_screen=None이라 src는 None.
    src_screen_key: Optional[str] = None
    src_snapshot_id: Optional[str] = None
    src_event_key: Optional[str] = None  # 비-타겟으로 빠지게 한 action

    # recover 직후 다음 detection에서 채워짐
    dst_screen_key: Optional[str] = None
    dst_snapshot_id: Optional[str] = None

    recover_method: Optional[str] = None  # 'bring_to_front' | 'launch_app'
    recovered_to_target: bool = False

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "timestamp": self.timestamp,
            "stage": self.stage,
            "snapshot_id": self.snapshot_id,
            "non_target_package": self.non_target_package,
            "non_target_activity": self.non_target_activity,
            "src_screen_key": self.src_screen_key,
            "src_snapshot_id": self.src_snapshot_id,
            "src_event_key": self.src_event_key,
            "dst_screen_key": self.dst_screen_key,
            "dst_snapshot_id": self.dst_snapshot_id,
            "recover_method": self.recover_method,
            "recovered_to_target": self.recovered_to_target,
        }


@dataclass(slots=True)
class RecoverGraph:
    """
    비-타겟 dump → recover 이벤트의 연대순 리스트.

    target app의 UTG / app_memory와 완전히 분리되어 보존된다 — 비-타겟 화면이
    target 학습 데이터에 섞이는 contamination을 방지하면서도, recover의
    빈도·트리거·도달 화면을 별도로 추적해 디버깅·튜닝에 쓸 수 있다.
    """
    events: List[RecoverEvent] = field(default_factory=list)

    def add(self, event: RecoverEvent) -> None:
        self.events.append(event)

    def last_pending(self) -> Optional[RecoverEvent]:
        """dst가 아직 채워지지 않은 가장 최근 이벤트."""
        for evt in reversed(self.events):
            if evt.dst_screen_key is None:
                return evt
        return None

    def count(self) -> int:
        return len(self.events)

    def package_counts(self) -> dict[str, int]:
        """비-타겟 패키지별 발생 횟수."""
        out: dict[str, int] = {}
        for evt in self.events:
            key = evt.non_target_package or "<unknown>"
            out[key] = out.get(key, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {
            "events": [evt.to_dict() for evt in self.events],
            "summary": {
                "total": len(self.events),
                "by_package": self.package_counts(),
                "recovered_to_target": sum(
                    1 for e in self.events if e.recovered_to_target
                ),
            },
        }
