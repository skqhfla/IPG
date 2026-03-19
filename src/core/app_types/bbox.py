from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BBox:
    """Pixel-based bounding box (x1, y1, x2, y2)."""

    x1: int
    y1: int
    x2: int
    y2: int

    def __post_init__(self) -> None:
        if self.x1 > self.x2:
            raise ValueError(f"x1({self.x1}) > x2({self.x2})")
        if self.y1 > self.y2:
            raise ValueError(f"y1({self.y1}) > y2({self.y2})")

    def __iter__(self):
        # legacy compatibility
        yield self.x1
        yield self.y1
        yield self.x2
        yield self.y2

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.x1, self.y1, self.x2, self.y2

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def cx(self) -> int:
        return (self.x1 + self.x2) // 2

    @property
    def cy(self) -> int:
        return (self.y1 + self.y2) // 2