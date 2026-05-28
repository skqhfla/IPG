#src/core/memory/packet_memory.py
from __future__ import annotations

from collections.abc import Iterable

from core.adb.netstats import PacketStat
from core.app_types import EventKey


# 같은 (screen_id, event_key)가 서로 다른 snapshot(파일명)에서 다시 발생할 수
# 있으므로, 측정 단위를 snapshot_id까지 내려 보관한다. 이렇게 해야 통합된
# screen_id 아래에 묶이는 여러 snapshot 각각의 측정값을 보존할 수 있다.
LEGACY_SNAPSHOT_KEY = "_unknown_"


class PacketMemoryStore:
    def __init__(self) -> None:
        # screen_key -> snapshot_id -> event_key -> PacketStat
        self._data: dict[str, dict[str, dict[EventKey, PacketStat]]] = {}

    def has_screen(self, screen_key: str) -> bool:
        return screen_key in self._data

    def add_event(
        self,
        screen_key: str,
        event_key: EventKey,
        stat: PacketStat,
        *,
        snapshot_id: str | None = None,
    ) -> None:
        # snapshot_id가 None이면 legacy 호환용 sentinel을 사용한다.
        snap = snapshot_id or LEGACY_SNAPSHOT_KEY
        # 같은 (screen, snapshot, event) 재발생 시 최신 측정값으로 덮어쓴다.
        self._data.setdefault(screen_key, {}).setdefault(snap, {})[event_key] = stat

    def has_event(
        self,
        screen_key: str,
        event_key: EventKey,
        *,
        snapshot_id: str | None = None,
    ) -> bool:
        snaps = self._data.get(screen_key, {})
        if snapshot_id is None:
            return any(event_key in events for events in snaps.values())
        return event_key in snaps.get(snapshot_id, {})

    def get_stat(
        self,
        screen_key: str,
        event_key: EventKey,
        *,
        snapshot_id: str | None = None,
    ) -> PacketStat | None:
        snaps = self._data.get(screen_key, {})
        if snapshot_id is not None:
            return snaps.get(snapshot_id, {}).get(event_key)
        # snapshot 지정이 없으면 가장 최근(파일명 사전순 마지막) snapshot에서 찾는다.
        for snap in sorted(snaps.keys(), reverse=True):
            stat = snaps[snap].get(event_key)
            if stat is not None:
                return stat
        return None

    def get_events(self, screen_key: str) -> dict[EventKey, PacketStat]:
        # 모든 snapshot의 이벤트를 평탄화해 반환 (같은 event_key가 여러 snapshot에
        # 있으면 사전순 마지막 snapshot의 값으로 덮어쓴다).
        flat: dict[EventKey, PacketStat] = {}
        for snap in sorted(self._data.get(screen_key, {}).keys()):
            flat.update(self._data[screen_key][snap])
        return flat

    def get_snapshots(self, screen_key: str) -> dict[str, dict[EventKey, PacketStat]]:
        return dict(self._data.get(screen_key, {}))

    def get_all_events(self) -> dict[str, dict[str, dict[EventKey, PacketStat]]]:
        return self._data

    def iter_events(
        self,
    ) -> Iterable[tuple[str, dict[str, dict[EventKey, PacketStat]]]]:
        return self._data.items()

    def screen_count(self) -> int:
        return len(self._data)

    def total_event_count(self) -> int:
        return sum(
            len(events)
            for snaps in self._data.values()
            for events in snaps.values()
        )

    def to_dict(self) -> dict[str, dict[str, dict[str, dict[str, dict[str, int]]]]]:
        # 새 스키마:
        # {screen_key: {"snapshots": {snapshot_id: {"events": {event_key: stat}}}}}
        return {
            screen_key: {
                "snapshots": {
                    snapshot_id: {
                        "events": {
                            event_key: stat.to_dict()
                            for event_key, stat in sorted(events.items())
                        }
                    }
                    for snapshot_id, events in sorted(snapshots.items())
                }
            }
            for screen_key, snapshots in self._data.items()
        }
