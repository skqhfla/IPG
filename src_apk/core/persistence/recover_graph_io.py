#src/core/persistence/recover_graph_io.py
from __future__ import annotations

from pathlib import Path

from core.graph.recover_graph import RecoverGraph

from .json_io import write_json


def save_recover_graph(path: Path, graph: RecoverGraph) -> None:
    """이벤트가 0개여도 빈 그래프를 떨궈 둔다 — 부재가 의도된 상태임을 표시."""
    write_json(path, graph.to_dict())
