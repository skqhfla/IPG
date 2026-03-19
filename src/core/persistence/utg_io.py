#src/core/persistence/utg_io.py
from __future__ import annotations

from pathlib import Path

from core.app_types import EventType
from core.graph.utg import UTGEdge, UTGGraphData, UTGNode

from .json_io import read_json, write_json


def save_utg(path: Path, utg: UTGGraphData) -> None:
    write_json(path, utg.to_dict())


def load_utg(path: Path) -> UTGGraphData:
    graph = UTGGraphData()

    if not path.exists():
        return graph

    payload = read_json(path)

    max_index = -1

    for node_data in payload.get("nodes", []):
        node = UTGNode(
            screen_id=node_data["screen_id"],
            index=node_data["index"],
            snapshots=set(node_data.get("snapshots", [])),
            screenshot_path=node_data.get("screenshot_path"),
            first_snapshot_id=node_data.get("first_snapshot_id"),
            last_snapshot_id=node_data.get("last_snapshot_id"),
        )
        graph.nodes[node.screen_id] = node
        max_index = max(max_index, node.index)

    for edge_data in payload.get("edges", []):
        edge = UTGEdge(
            src=edge_data["src"],
            dst=edge_data["dst"],
            event_type=EventType(edge_data["event_type"]),
            event_key=edge_data.get("event_key"),
            description=edge_data.get("description"),
            src_snapshot_id=edge_data.get("src_snapshot_id"),
            dst_snapshot_id=edge_data.get("dst_snapshot_id"),
        )
        graph.edges.append(edge)

    graph._next_index = max_index + 1
    return graph