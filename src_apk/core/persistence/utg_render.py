# src/core/persistence/utg_render.py
from __future__ import annotations

from pathlib import Path

from core.graph.utg import UTGGraphData


def render_utg_png(path: Path, utg: UTGGraphData) -> None:
    import matplotlib.pyplot as plt
    import networkx as nx
    from matplotlib.offsetbox import OffsetImage, AnnotationBbox

    graph = nx.DiGraph()

    # 노드 추가
    for screen_id, node in utg.nodes.items():
        graph.add_node(
            screen_id,
            label=f"{node.index}: {screen_id}",
            screenshot=node.screenshot_path if hasattr(node, "screenshot_path") else None,
        )

    # 엣지 추가
    for edge in utg.edges:
        if edge.event_key:
            edge_label = edge.event_key
        else:
            edge_label = edge.event_type.value

        graph.add_edge(edge.src, edge.dst, label=edge_label)

    plt.figure(figsize=(14, 10))

    if graph.number_of_nodes() == 0:
        plt.text(0.5, 0.5, "Empty UTG", ha="center", va="center")
        plt.axis("off")
        path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(path, bbox_inches="tight")
        plt.close()
        return

    pos = nx.spring_layout(graph, seed=42)

    edge_labels = nx.get_edge_attributes(graph, "label")

    # edge 먼저 그림
    nx.draw_networkx_edges(graph, pos, arrows=True, arrowstyle="->", arrowsize=18)

    # 이미지 노드 그리기
    ax = plt.gca()

    for node in graph.nodes(data=True):
        screen_id = node[0]
        attrs = node[1]
        screenshot = attrs.get("screenshot")

        x, y = pos[screen_id]

        if screenshot and Path(screenshot).exists():
            img = plt.imread(screenshot)
            imagebox = OffsetImage(img, zoom=0.15)
            ab = AnnotationBbox(imagebox, (x, y), frameon=True)
            ax.add_artist(ab)
        else:
            ax.scatter(x, y, s=1800)

        # label 표시
        ax.text(
            x,
            y - 0.08,
            attrs["label"],
            ha="center",
            va="top",
            fontsize=7,
        )

    nx.draw_networkx_edge_labels(graph, pos, edge_labels=edge_labels, font_size=7)

    plt.axis("off")
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(path, bbox_inches="tight")
    plt.close()