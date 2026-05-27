#src/core/persistence/recover_graph_render.py
from __future__ import annotations

from collections import Counter
from pathlib import Path

from core.graph.recover_graph import RecoverGraph


def render_recover_graph_png(path: Path, graph: RecoverGraph) -> None:
    """
    recover 이벤트 그래프 시각화.

    노드:
      - target screen (src/dst)         : 라이트블루 사각형
      - non-target package marker        : 살몬 다이아몬드 (패키지별 1개)
    엣지:
      - src_screen --(src_event_key)--> non_target  (실선, 빨강)
      - non_target --(recover_method)--> dst_screen (점선, 초록)

    동일한 (src, non_target) 쌍은 횟수만 카운트해 라벨에 표시한다.
    """
    import matplotlib.pyplot as plt
    import networkx as nx

    path.parent.mkdir(parents=True, exist_ok=True)

    if not graph.events:
        plt.figure(figsize=(6, 4))
        plt.text(
            0.5, 0.5,
            "No recover events\n(target package never lost)",
            ha="center", va="center", fontsize=11,
        )
        plt.axis("off")
        plt.savefig(path, bbox_inches="tight")
        plt.close()
        return

    g = nx.MultiDiGraph()

    target_nodes: set[str] = set()
    nontarget_nodes: set[str] = set()

    # (src_node, dst_node, label) -> count
    in_edges: Counter = Counter()  # target → non-target
    out_edges: Counter = Counter()  # non-target → target

    for evt in graph.events:
        nt_node = f"pkg:{evt.non_target_package or '<unknown>'}"
        nontarget_nodes.add(nt_node)

        if evt.src_screen_key:
            src_node = f"scr:{evt.src_screen_key[:8]}"
            target_nodes.add(src_node)
            label = evt.src_event_key or "(unknown_action)"
            in_edges[(src_node, nt_node, label)] += 1

        if evt.dst_screen_key:
            dst_node = f"scr:{evt.dst_screen_key[:8]}"
            target_nodes.add(dst_node)
            method = evt.recover_method or "recover"
            ok = "✓" if evt.recovered_to_target else "✗"
            label = f"{method} {ok}"
            out_edges[(nt_node, dst_node, label)] += 1

    for node in target_nodes:
        g.add_node(node, kind="target")
    for node in nontarget_nodes:
        g.add_node(node, kind="non_target")

    for (s, d, label), n in in_edges.items():
        text = f"{label} ×{n}" if n > 1 else label
        g.add_edge(s, d, label=text, kind="in")
    for (s, d, label), n in out_edges.items():
        text = f"{label} ×{n}" if n > 1 else label
        g.add_edge(s, d, label=text, kind="out")

    pos = nx.spring_layout(g, seed=42, k=1.2)

    fig_w = max(10, 1.6 * g.number_of_nodes())
    fig_h = max(6, 1.0 * g.number_of_nodes())
    plt.figure(figsize=(fig_w, fig_h))
    ax = plt.gca()

    target_list = [n for n, d in g.nodes(data=True) if d.get("kind") == "target"]
    nontarget_list = [n for n, d in g.nodes(data=True) if d.get("kind") == "non_target"]

    nx.draw_networkx_nodes(
        g, pos, nodelist=target_list,
        node_color="#9ec5ee", node_shape="s", node_size=2200, edgecolors="#456", linewidths=1.0,
    )
    nx.draw_networkx_nodes(
        g, pos, nodelist=nontarget_list,
        node_color="#f4a582", node_shape="D", node_size=2400, edgecolors="#a33", linewidths=1.0,
    )

    in_edge_list = [(u, v, k) for u, v, k, d in g.edges(keys=True, data=True) if d.get("kind") == "in"]
    out_edge_list = [(u, v, k) for u, v, k, d in g.edges(keys=True, data=True) if d.get("kind") == "out"]

    nx.draw_networkx_edges(
        g, pos, edgelist=[(u, v) for u, v, _ in in_edge_list],
        edge_color="#c0392b", arrows=True, arrowstyle="->", arrowsize=18,
        connectionstyle="arc3,rad=0.1",
    )
    nx.draw_networkx_edges(
        g, pos, edgelist=[(u, v) for u, v, _ in out_edge_list],
        edge_color="#27ae60", arrows=True, arrowstyle="->", arrowsize=18,
        style="dashed", connectionstyle="arc3,rad=0.1",
    )

    nx.draw_networkx_labels(g, pos, font_size=8)

    edge_labels: dict[tuple[str, str], str] = {}
    for u, v, _k, d in g.edges(keys=True, data=True):
        # 다중 엣지는 같은 위치에 겹쳐 그려지므로 ; 로 join
        prev = edge_labels.get((u, v))
        text = d.get("label", "")
        edge_labels[(u, v)] = f"{prev}; {text}" if prev else text

    nx.draw_networkx_edge_labels(g, pos, edge_labels=edge_labels, font_size=7)

    summary = graph.to_dict()["summary"]
    title = (
        f"Recover Graph — total={summary['total']}, "
        f"recovered={summary['recovered_to_target']}, "
        f"by_pkg={summary['by_package']}"
    )
    plt.title(title, fontsize=10)
    plt.axis("off")
    plt.savefig(path, bbox_inches="tight", dpi=120)
    plt.close()
