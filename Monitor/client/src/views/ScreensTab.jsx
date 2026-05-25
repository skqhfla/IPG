import { useMemo, useState } from 'react';

export default function ScreensTab({ run }) {
  const screens = run?.appMemory?.screens || {};
  const screenList = useMemo(
    () => Object.entries(screens).map(([key, data]) => ({ key, ...data })),
    [screens]
  );

  const [selectedKey, setSelectedKey] = useState(screenList[0]?.key || null);
  const selected = screenList.find(s => s.key === selectedKey) || screenList[0];

  if (!screenList.length) {
    return <div className="run-empty">app_memory.json에 화면이 없습니다.</div>;
  }

  return (
    <div className="run-tab-content screens-tab">
      <aside className="screen-list">
        <div className="screen-list-header">
          {screenList.length} screens
        </div>
        {screenList.map(s => (
          <button
            key={s.key}
            className={`screen-list-item ${selected?.key === s.key ? 'selected' : ''}`}
            onClick={() => setSelectedKey(s.key)}
          >
            <div className="sli-row1">
              <code className="sli-id">{s.key.slice(0, 10)}</code>
              <span className="sli-count">{s.snapshots?.length || 0} snaps</span>
            </div>
            <div className="sli-row2">
              {(s.activity || '?').split('.').pop()}
            </div>
            <div className="sli-row3">
              <ScrollChips dirs={s.scrolls?.directions_tried || []} exhausted={s.scrolls?.directions_exhausted || []} />
            </div>
          </button>
        ))}
      </aside>

      <section className="screen-detail">
        {selected && <ScreenDetailPanel screen={selected} run={run} />}
      </section>
    </div>
  );
}

function ScrollChips({ dirs, exhausted }) {
  const ex = new Set(exhausted);
  const all = Array.from(new Set([...dirs, ...exhausted]));
  if (!all.length) return <span className="run-muted">scroll 기록 없음</span>;
  return (
    <div className="chip-row">
      {all.map(d => (
        <span key={d} className={`chip ${ex.has(d) ? 'chip-exhausted' : 'chip-tried'}`}>
          {d}{ex.has(d) ? ' ✕' : ''}
        </span>
      ))}
    </div>
  );
}

function ScreenDetailPanel({ screen, run }) {
  const snaps = screen.snapshots || [];
  const blobMap = run?.blobMap || {};

  return (
    <div className="sd-root">
      <header className="sd-header">
        <h3>
          <code>{screen.key}</code>
        </h3>
        <div className="sd-subtitle">
          {screen.activity ? <span><strong>activity</strong>: <code>{screen.activity}</code></span> : null}
          {screen.window_id != null ? <span> · <strong>window</strong>: <code>{screen.window_id}</code></span> : null}
          <span> · <strong>snapshots</strong>: {snaps.length}</span>
        </div>
      </header>

      <section className="sd-section">
        <h4>스크롤 메모리 (화면 단위)</h4>
        <ScrollChips
          dirs={screen.scrolls?.directions_tried || []}
          exhausted={screen.scrolls?.directions_exhausted || []}
        />
      </section>

      <section className="sd-section">
        <h4>스냅샷 ({snaps.length})</h4>
        <div className="snap-gallery">
          {snaps.length === 0 && <div className="run-muted">없음</div>}
          {snaps.map(id => {
            const url = blobMap[id];
            return (
              <figure key={id} className="snap-card">
                {url
                  ? <img src={url} alt={id} />
                  : <div className="snap-missing">no image</div>}
                <figcaption>{id}</figcaption>
              </figure>
            );
          })}
        </div>
      </section>

      <section className="sd-section">
        <h4>Elements ({screen.elements?.length || 0})</h4>
        <ElementsTable elements={screen.elements || []} />
      </section>
    </div>
  );
}

function ElementsTable({ elements }) {
  if (!elements.length) return <div className="run-muted">없음</div>;
  return (
    <div className="el-table-wrap">
      <table className="el-table">
        <thead>
          <tr>
            <th>id</th>
            <th>class</th>
            <th>text / desc</th>
            <th>resource-id</th>
            <th>scroll dirs</th>
            <th>executed</th>
          </tr>
        </thead>
        <tbody>
          {elements.map(el => {
            const tried = el.swipe_directions_tried || [];
            const exhausted = new Set(el.swipe_directions_exhausted || []);
            const allDirs = Array.from(new Set([...tried, ...el.swipe_directions_exhausted || []]));
            return (
              <tr key={el.element_id} className={el.is_scrollable ? 'el-scrollable' : ''}>
                <td><code>{el.element_id}</code>{el.is_scrollable && <span className="el-badge">scroll</span>}</td>
                <td>{el.class}</td>
                <td className="el-text">{el.text || el.description || ''}</td>
                <td><code className="el-rid">{el.resource_id || ''}</code></td>
                <td>
                  {allDirs.length
                    ? allDirs.map(d => (
                      <span key={d} className={`chip chip-sm ${exhausted.has(d) ? 'chip-exhausted' : 'chip-tried'}`}>
                        {d}{exhausted.has(d) ? '✕' : ''}
                      </span>
                    ))
                    : ''}
                </td>
                <td className="el-events">
                  {(el.executed_events || []).map(ev => (
                    <code key={ev} className="ev-chip">{ev}</code>
                  ))}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
