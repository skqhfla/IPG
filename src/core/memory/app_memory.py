
#src/core/memory/app_memory.py
from __future__ import annotations

from typing import Iterable

from core.app_types import Element, EventKey, Screen


class AppMemoryStore:
    def __init__(self) -> None:
        self._screens: dict[str, Screen] = {}
        self._snapshots: dict[str, set[str]] = {}

    @staticmethod
    def make_screen_key(screen: Screen) -> str:
        return screen.screen_id.to_key()

    def has_screen(self, screen_key: str) -> bool:
        return screen_key in self._screens

    def get_screen(self, screen_key: str) -> Screen | None:
        return self._screens.get(screen_key)

    def upsert_screen(self, screen: Screen) -> None:
        """
        동일 screen_key면 동일한 detection 결과로 간주하므로 덮어쓰지 않음.
        """
        screen_key = self.make_screen_key(screen)
        if screen_key not in self._screens:
            self._screens[screen_key] = screen

    def get_all_screens(self) -> dict[str, Screen]:
        return self._screens

    def iter_screens(self) -> Iterable[tuple[str, Screen]]:
        return self._screens.items()
    
    def add_snapshot(self, screen_key: str, snapshot_id: str) -> None:
        self._snapshots.setdefault(screen_key, set()).add(snapshot_id)

    def get_snapshots(self, screen_key: str) -> set[str]:
        return self._snapshots.get(screen_key, set())

    def get_elements(self, screen_key: str) -> list[Element]:
        screen = self.get_screen(screen_key)
        if screen is None:
            return []
        return screen.elements

    def get_actionable_elements(self, screen_key: str) -> list[Element]:
        screen = self.get_screen(screen_key)
        if screen is None:
            return []
        return [element for element in screen.elements if element.is_actionable]

    def get_element(self, screen_key: str, element_id: str) -> Element | None:
        screen = self.get_screen(screen_key)
        if screen is None:
            return None

        for element in screen.elements:
            if element.element_id == element_id:
                return element
        return None

    def get_or_add_screen(self, screen: Screen) -> Screen:
        screen_key = self.make_screen_key(screen)
        existing = self._screens.get(screen_key)
        if existing is not None:
            if screen.screenshot_path is not None:
                existing.screenshot_path = screen.screenshot_path
            if screen.xml_path is not None:
                existing.xml_path = screen.xml_path
            return existing

        self._screens[screen_key] = screen
        return screen

    def mark_event_executed(
        self,
        screen_key: str,
        element_id: str,
        event_key: EventKey,
    ) -> None:
        element = self.get_element(screen_key, element_id)
        if element is None:
            raise KeyError(
                f"Element not found: screen_key={screen_key}, element_id={element_id}"
            )
        element.mark_executed(event_key)

    def has_executed_event(
        self,
        screen_key: str,
        element_id: str,
        event_key: EventKey,
    ) -> bool:
        element = self.get_element(screen_key, element_id)
        if element is None:
            return False
        return element.has_executed(event_key)

    def get_unexecuted_actionable_elements(
        self,
        screen_key: str,
    ) -> list[Element]:
        """
        아직 어떤 event도 수행하지 않은 actionable element들만 반환.
        나중에 traversal policy가 event 종류별로 더 세밀하게 판단할 수 있음.
        """
        screen = self.get_screen(screen_key)
        if screen is None:
            return []

        result: list[Element] = []
        for element in screen.elements:
            if not element.is_actionable:
                continue
            if element.executed_events:
                continue
            result.append(element)
        return result

    def screen_count(self) -> int:
        return len(self._screens)
    
    def to_dict(self) -> dict[str, dict]:
        result: dict[str, dict] = {}

        for screen_key, screen in self._screens.items():
            result[screen_key] = {
                "screen_id": screen.screen_id.to_key(),
                "snapshots": sorted(self._snapshots.get(screen_key, set())),
                "screenshot_path": (
                    str(screen.screenshot_path) if screen.screenshot_path else None
                ),
                "xml_path": str(screen.xml_path) if screen.xml_path else None,
                "elements": [
                    {
                        "element_id": element.element_id,
                        "class": element.cls,
                        "bbox": list(element.bbox.as_tuple()),
                        "source": element.source,
                        "resource_id": element.resource_id,
                        "text": element.text,
                        "description": element.description,
                        "executed_events": sorted(element.executed_events),
                        "is_actionable": element.is_actionable,
                        "note": element.note,
                    }
                    for element in screen.elements
                ],
            }

        return result