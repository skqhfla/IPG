import { useEffect, useState, useRef, useMemo } from 'react';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
  Panel,
  useReactFlow,
  ReactFlowProvider,
  Position,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from '@dagrejs/dagre';
import ScreenNode from './ScreenNode.jsx';

// ── 노드 크기 상수 ─────────────────────────────────────────────────
const NODE_W = 170;
const NODE_H = 210;



// ── dagre 자동 레이아웃 ────────────────────────────────────────────
function getLayoutedElements(nodes, edges, direction = 'LR') {
  const g = new dagre.graphlib.Graph({ multigraph: true });
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: direction,
    ranksep: direction === 'LR' ? 120 : 80,
    nodesep: direction === 'LR' ? 60 : 100,
    edgesep: 30,
    marginx: 40,
    marginy: 40,
  });

  nodes.forEach(n => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  edges.forEach((e, i) => g.setEdge(e.source, e.target, {}, `e${i}`));

  dagre.layout(g);

  return {
    nodes: nodes.map(n => {
      const pos = g.node(n.id);
      return {
        ...n,
        position: {
          x: pos.x - NODE_W / 2,
          y: pos.y - NODE_H / 2,
        },
      };
    }),
    edges,
  };
}

// ── 커스텀 노드 타입 등록 ─────────────────────────────────────────
const nodeTypes = { screen: ScreenNode };

// ── 엣지 색상 팔레트 (이벤트 타입별) ──────────────────────────────
const edgeColor = (eventType) => {
  const map = {
    tap: '#00d4ff',
    swipe: '#a78bfa',
    scroll: '#34d399',
    longpress: '#fb923c',
    back: '#f87171',
  };
  return map[eventType] ?? '#94a3b8';
};

// ── 방향에 따른 노드 연결 위치 ────────────────────────────────────
function getNodePortPositions(direction) {
  if (direction === 'TB') {
    return {
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    };
  }

  return {
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  };
}

// ── 내부 그래프 (FitView 사용을 위해 Provider 내부에 위치) ────────
function GraphInner({ data, jsonPath, blobUrlMap }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNodes, setSelectedNodes] = useState([]); // [NodeA, NodeB]
  const [direction, setDirection] = useState('LR');
  const [displayMode, setDisplayMode] = useState('trigger'); // 'all' | 'trigger'
  
  // 이미지별 렌더링/원본 크기 정보 (A: 0번, B: 1번)
  const [imgSizeA, setImgSizeA] = useState({ w: 0, h: 0, nw: 0, nh: 0 });
  const [imgSizeB, setImgSizeB] = useState({ w: 0, h: 0, nw: 0, nh: 0 });
  
  const [hoverPos, setHoverPos] = useState({ x: 0, y: 0, ox: 0, oy: 0, visible: false });
  const [hoveredNode, setHoveredNode] = useState(null);
  const [hoveredEdge, setHoveredEdge] = useState(null);
  
  const imgRefA = useRef(null);
  const imgRefB = useRef(null);
  const { fitView } = useReactFlow();

  // ── 이미지 로드 시 원본 크기 저장 ──────────────────────────────────
  const handleImageLoad = (idx, e) => {
    const { naturalWidth, naturalHeight } = e.target;
    if (idx === 0) setImgSizeA(prev => ({ ...prev, nw: naturalWidth, nh: naturalHeight }));
    else setImgSizeB(prev => ({ ...prev, nw: naturalWidth, nh: naturalHeight }));
  };

  // ── 이미지 크기 변화 감지 (ResizeObserver) ────────────────────────
  useEffect(() => {
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.target === imgRefA.current) {
          const { width, height } = entry.contentRect;
          setImgSizeA(prev => ({ ...prev, w: width, h: height }));
        }
        if (entry.target === imgRefB.current) {
          const { width, height } = entry.contentRect;
          setImgSizeB(prev => ({ ...prev, w: width, h: height }));
        }
      }
    });

    if (imgRefA.current) observer.observe(imgRefA.current);
    if (imgRefB.current) observer.observe(imgRefB.current);

    return () => observer.disconnect();
  }, [selectedNodes]);

  // ── 선택된 노드들의 트리거 요소 ID 추출 ─────────────────────────
  const triggerElementIds = useMemo(() => {
    if (selectedNodes.length === 0 || !data?.edges) return new Set();
    const ids = new Set();
    const selectedIds = selectedNodes.map(n => n.screen_id);
    data.edges.forEach(e => {
      if (selectedIds.includes(e.src) && e.event_key) {
        const parts = e.event_key.split('@');
        if (parts.length > 1) ids.add(parts[1]);
      }
    });
    return ids;
  }, [selectedNodes, data?.edges]);

  // ── 1. 레이아웃 엔진 (데이터나 방향이 바뀔 때만 실행) ───────────────────────
  useEffect(() => {
    if (!data?.nodes || !data?.edges) return;

    const { sourcePosition, targetPosition } = getNodePortPositions(direction);

    // 기본 노드 생성
    const rawNodes = data.nodes.map(n => ({
      id: n.screen_id,
      type: 'screen',
      position: { x: 0, y: 0 },
      sourcePosition,
      targetPosition,
      data: {
        ...n,
        jsonPath,
        blobUrlMap,
        direction,
      },
    }));

    // 기본 엣지 생성 (중복 제거)
    const seen = new Set();
    const rawEdges = data.edges
      .filter(e => {
        const key = `${e.src}::${e.dst}::${e.event_key}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .map((e, i) => ({
        id: `edge-${i}`,
        source: e.src,
        target: e.dst,
        type: 'smoothstep',
        pathOptions: { borderRadius: 16 },
        label: e.event_key ?? e.event_type,
        data: e,
      }));

    // 레이아웃 계산
    const { nodes: layoutedNodes, edges: layoutedEdges } =
      getLayoutedElements(rawNodes, rawEdges, direction);

    setNodes(layoutedNodes);
    setEdges(layoutedEdges);

    // 화면 맞춤 (한 번만 실행)
    requestAnimationFrame(() => {
      fitView({ padding: 0.12, duration: 400 });
    });
  }, [data, direction, jsonPath, blobUrlMap, setNodes, setEdges, fitView]);

  // ── 2. 시각적 주입 (호버/선택 상태 반영) ──────────────────────────────
  const displayNodes = useMemo(() => {
    return nodes.map(n => ({
      ...n,
      selected: selectedNodes.some(sn => sn.screen_id === n.id),
      data: {
        ...n.data,
        onOpenPreview: (e) => {
          if (e?.shiftKey) {
            setSelectedNodes(prev => {
              const alreadySelected = prev.some(sn => sn.screen_id === n.id);
              if (alreadySelected) return prev.filter(sn => sn.screen_id !== n.id);
              if (prev.length >= 2) return [prev[1], n.data];
              return [...prev, n.data];
            });
          } else {
            setSelectedNodes([n.data]);
          }
        },
      }
    }));
  }, [nodes, selectedNodes]);

  const displayEdges = useMemo(() => {
    return edges.map((edge) => {
      const e = edge.data;
      const color = edgeColor(e.event_type);
      const isSelected = hoveredEdge === edge.id;
      const isRelatedToHoveredNode = hoveredNode && (e.src === hoveredNode || e.dst === hoveredNode);
      const isRelatedToSelectedNodes = selectedNodes.some(sn => e.src === sn.screen_id || e.dst === sn.screen_id);
      
      const shouldHighlight = isSelected || isRelatedToHoveredNode || isRelatedToSelectedNodes;
      const isDimmed = (hoveredNode || hoveredEdge || selectedNodes.length > 0) && !shouldHighlight;

      return {
        ...edge,
        animated: shouldHighlight,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 14,
          height: 14,
          color: isDimmed ? 'rgba(148, 163, 184, 0.1)' : color,
        },
        style: {
          ...edge.style,
          stroke: isDimmed ? 'rgba(148, 163, 184, 0.1)' : color,
          strokeWidth: shouldHighlight ? 3 : 1.5,
          transition: 'stroke 0.2s, stroke-width 0.2s',
        },
        labelStyle: {
          fill: isDimmed ? 'rgba(148, 163, 184, 0.1)' : '#94a3b8',
          fontSize: 9,
          fontFamily: "'JetBrains Mono', monospace",
          opacity: isDimmed ? 0.3 : 1,
          transition: 'opacity 0.2s, fill 0.2s',
        },
        labelBgStyle: {
          fill: '#0d1526',
          fillOpacity: isDimmed ? 0.1 : 0.9,
        },
        labelBgPadding: [4, 6],
        labelBgBorderRadius: 4,
        zIndex: shouldHighlight ? 10 : 1,
      };
    });
  }, [edges, hoveredNode, hoveredEdge, selectedNodes]);

  if (!data) return null;

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <ReactFlow
        nodes={displayNodes}
        edges={displayEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        onNodeMouseEnter={(_, node) => setHoveredNode(node.id)}
        onNodeMouseLeave={() => setHoveredNode(null)}
        onEdgeMouseEnter={(_, edge) => setHoveredEdge(edge.id)}
        onEdgeMouseLeave={() => setHoveredEdge(null)}
        onClick={() => {
          // 배경 클릭 시 선택 해제 (Shift 안 누른 경우만)
          // ReactFlow 내부 이벤트 처리를 고려하여 Panel 밖에서 동작하게 유도 필요할 수도 있음
        }}
        minZoom={0.05}
        maxZoom={3}
        defaultEdgeOptions={{ zIndex: 1 }}
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          color="rgba(255,255,255,0.06)"
          gap={24}
          size={1.5}
        />

        <Controls showInteractive={false} />

        <MiniMap
          nodeColor={() => '#00d4ff'}
          maskColor="rgba(8,12,20,0.82)"
          pannable
          zoomable
        />

        <Panel position="top-right">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div className="graph-controls">
              <span className="graph-controls-label">레이아웃</span>
              <button
                className={`layout-btn ${direction === 'LR' ? 'active' : ''}`}
                onClick={() => setDirection('LR')}
              >
                → 좌→우
              </button>
              <button
                className={`layout-btn ${direction === 'TB' ? 'active' : ''}`}
                onClick={() => setDirection('TB')}
              >
                ↓ 위→아래
              </button>
            </div>

            <div className="graph-stats-panel">
              <span>노드 <b>{data.nodes.length}</b></span>
              <span>|</span>
              <span>전환 <b>{data.edges.length}</b></span>
            </div>
          </div>
        </Panel>
      </ReactFlow>

      {selectedNodes.length > 0 && (
        <div className={`node-preview-panel ${selectedNodes.length === 2 ? 'is-diff' : ''}`}>
          <button
            className="node-preview-close"
            onClick={() => setSelectedNodes([])}
          >
            ✕
          </button>

          <div className="node-preview-header">
            <div className="node-preview-title">
              {selectedNodes.length === 1 
                ? `화면 #${selectedNodes[0].index}` 
                : `비교 모드 (#${selectedNodes[0].index} ↔ #${selectedNodes[1].index})`
              }
            </div>
            
            {selectedNodes.length === 1 ? (
              <div className="node-preview-instruction">
                💡 <b>Shift + Click</b>으로 다른 화면을 선택하면 비교할 수 있습니다.
              </div>
            ) : (
              <div className="node-preview-instruction">
                비교 화면(B)의 요소 변화를 색상으로 확인하세요.
              </div>
            )}
          </div>

          <div className="preview-mode-toggle">
            <button 
              className={displayMode === 'trigger' ? 'active' : ''} 
              onClick={() => setDisplayMode('trigger')}
            >
              📍 트리거만
            </button>
            <button 
              className={displayMode === 'all' ? 'active' : ''} 
              onClick={() => setDisplayMode('all')}
            >
              🔍 전체 요소
            </button>
          </div>

          <div className="preview-content-area">
            {selectedNodes.map((node, nodeIdx) => (
              <div key={node.screen_id} className="preview-item">
                <div className="preview-item-label">
                  {selectedNodes.length === 2 ? (nodeIdx === 0 ? '기본 (A)' : '대상 (B)') : ''}
                </div>
                <div className="node-preview-image-wrap">
                  {node.first_snapshot_id ? (
                    <div className="bbox-container" style={{ 
                      aspectRatio: (nodeIdx === 0 ? imgSizeA.nw : imgSizeB.nw) && (nodeIdx === 0 ? imgSizeA.nh : imgSizeB.nh) 
                        ? `${nodeIdx === 0 ? imgSizeA.nw : imgSizeB.nw} / ${nodeIdx === 0 ? imgSizeA.nh : imgSizeB.nh}` 
                        : 'auto' 
                    }}>
                      <img
                        ref={nodeIdx === 0 ? imgRefA : imgRefB}
                        src={
                          blobUrlMap?.[node.first_snapshot_id] ??
                          (jsonPath
                            ? `/api/snapshot?jsonPath=${encodeURIComponent(jsonPath)}&id=${node.first_snapshot_id}`
                            : '')
                        }
                        alt={`Screen ${node.index}`}
                        onLoad={(e) => handleImageLoad(nodeIdx, e)}
                      />
                      
                      {/* 바운딩 박스 오버레이 */}
                      {(() => {
                        const screens = data.screens || data.app_memory?.screens;
                        const screenA = screens?.[selectedNodes[0].screen_id];
                        const screenB = selectedNodes.length === 2 ? screens?.[selectedNodes[1].screen_id] : null;
                        const currentScreen = screens?.[node.screen_id];
                        
                        // 현재 이미지 정보
                        const currentImgSize = nodeIdx === 0 ? imgSizeA : imgSizeB;
                        if (!currentScreen?.elements || currentImgSize.w === 0) return null;

                        const sw = currentImgSize.nw || 1080;
                        const sh = currentImgSize.nh || 1920;

                        // Diff 로직 (생략 - 동일)
                        const getDiffStatus = (el) => {
                          if (selectedNodes.length < 2) return null;
                          const otherScreen = nodeIdx === 0 ? screenB : screenA;
                          // 매칭 시도 (resource_id -> class+text)
                          // 만약 ID나 텍스트가 같다면 동일 요소로 간주하고 좌표 차이를 체크함
                          const matched = otherScreen.elements.find(o => 
                            (o.resource_id && o.resource_id !== "null" && o.resource_id === el.resource_id) ||
                            (o.class === el.class && o.text === el.text && o.text !== "")
                          ) || otherScreen.elements.find(o => 
                            (o.class === el.class && o.bbox.toString() === el.bbox.toString())
                          );

                          if (!matched) return nodeIdx === 0 ? 'removed' : 'added';
                          
                          // 텍스트, 클래스, 또는 좌표가 하나라도 다르면 'modified'
                          const isModified = 
                            matched.text !== el.text || 
                            matched.class !== el.class ||
                            matched.bbox.toString() !== el.bbox.toString();

                          if (isModified) return 'modified';
                          return 'unchanged';
                        };

                        const filteredElements = displayMode === 'trigger'
                          ? currentScreen.elements.filter(el => triggerElementIds.has(el.element_id))
                          : currentScreen.elements;

                        return (
                          <div 
                            className="bbox-overlay" 
                            onMouseMove={(e) => {
                              if (nodeIdx !== 0) return;
                              const rect = e.currentTarget.getBoundingClientRect();
                              const rx = e.clientX - rect.left;
                              const ry = e.clientY - rect.top;
                              const ox = Math.round((rx / currentImgSize.w) * currentImgSize.nw);
                              const oy = Math.round((ry / currentImgSize.h) * currentImgSize.nh);
                              setHoverPos({ x: rx, y: ry, ox, oy, visible: true });
                            }}
                            onMouseLeave={() => setHoverPos(prev => ({ ...prev, visible: false }))}
                          >
                            {filteredElements.map((el, i) => {
                              const [x1, y1, x2, y2] = el.bbox;
                              const w = x2 - x1;
                              const h = y2 - y1;
                              if (w <= 0 || h <= 0) return null;

                              const isTrigger = triggerElementIds.has(el.element_id);
                              const diffStatus = getDiffStatus(el);
                              const isDimmedByDiff = selectedNodes.length === 2 && (diffStatus === 'unchanged' || !diffStatus);

                              return (
                                <div
                                  key={el.element_id || i}
                                  className={`bbox-rect ${isTrigger ? 'is-trigger' : ''} diff-${diffStatus}`}
                                  style={{
                                    left: `${(x1 / sw) * 100}%`,
                                    top: `${(y1 / sh) * 100}%`,
                                    width: `${(w / sw) * 100}%`,
                                    height: `${(h / sh) * 100}%`,
                                    opacity: isDimmedByDiff ? 0.08 : 1, // 미세하게 더 투명하게
                                  }}
                                  title={`[${el.element_id}] ${diffStatus?.toUpperCase() || ''} | ${el.class} | ${el.text || ''}`}
                                >
                                  {(diffStatus && diffStatus !== 'unchanged') && (
                                    <span className="bbox-label">{diffStatus === 'added' ? '+' : diffStatus === 'removed' ? '-' : 'Δ'} {el.class}</span>
                                  )}
                                  {selectedNodes.length === 1 && (
                                    <span className="bbox-label">{el.element_id} · {el.class}</span>
                                  )}
                                </div>
                              );
                            })}

                            {nodeIdx === 0 && hoverPos.visible && (
                              <div className="coordinate-tooltip" style={{ left: hoverPos.x + 10, top: hoverPos.y + 10 }}>
                                {hoverPos.ox}, {hoverPos.oy}
                              </div>
                            )}
                          </div>
                        );
                      })()}
                    </div>
                  ) : (
                    <div className="node-no-image">📱<span>no image</span></div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {selectedNodes.length === 2 && (
            <div className="diff-legend">
              <span className="legend-item added">● 추가(Added)</span>
              <span className="legend-item removed">● 삭제(Removed)</span>
              <span className="legend-item modified">● 변경(Modified)</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Public 컴포넌트 (ReactFlowProvider 래퍼) ─────────────────────
export default function TransitionGraph({ data, jsonPath, blobUrlMap }) {
  return (
    <ReactFlowProvider>
      <GraphInner data={data} jsonPath={jsonPath} blobUrlMap={blobUrlMap} />
    </ReactFlowProvider>
  );
}