import { useMemo } from 'react';
import TransitionGraph from '../components/TransitionGraph.jsx';

// app_memory + screen_memory → TransitionGraph가 기대하는 {nodes, edges} 변환.
function buildGraphData(run) {
  const screens = run?.appMemory?.screens || {};
  const screenMemoryScreens = run?.screenMemory?.screens || {};

  const screenKeys = Object.keys(screens);
  const nodes = screenKeys.map((key, idx) => {
    const s = screens[key];
    const snaps = s.snapshots || [];
    return {
      screen_id: key,
      index: idx,
      snapshots: snaps,
      first_snapshot_id: snaps[0] || null,
      last_snapshot_id: snaps[snaps.length - 1] || null,
      activity: s.activity || null,
      window_id: s.window_id ?? null,
    };
  });

  // screen_memory 형식: { screens: { <dst>: [{src_screen_key, event_key}, ...] } }
  const edges = [];
  for (const [dst, transitions] of Object.entries(screenMemoryScreens)) {
    for (const t of transitions || []) {
      edges.push({
        src: t.src_screen_key,
        dst,
        event_type:
          (t.event_key || '').startsWith('tap')   ? 'tap'   :
          (t.event_key || '').startsWith('swipe') ? 'swipe' :
          (t.event_key || '').startsWith('back')  ? 'back'  :
          (t.event_key || '').startsWith('input') ? 'input' : 'other',
        event_key: t.event_key,
        description: null,
        src_snapshot_id: null,
        dst_snapshot_id: null,
      });
    }
  }

  return { nodes, edges };
}

export default function GraphTab({ run }) {
  const data = useMemo(() => buildGraphData(run), [run]);
  if (!data.nodes.length) {
    return <div className="run-empty">화면 데이터가 없습니다.</div>;
  }
  return (
    <div className="run-tab-content graph-tab">
      <TransitionGraph
        data={data}
        jsonPath={null}
        blobUrlMap={run?.blobMap || {}}
      />
    </div>
  );
}
