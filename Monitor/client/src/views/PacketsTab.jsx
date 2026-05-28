import { useEffect, useMemo, useState } from 'react';

const SORT_KEYS = [
  { key: 'tx_bytes',   label: 'TX bytes' },
  { key: 'rx_bytes',   label: 'RX bytes' },
  { key: 'tx_packets', label: 'TX pkts' },
  { key: 'rx_packets', label: 'RX pkts' },
  { key: 'total_bytes', label: 'Total bytes' },
];

function fmtBytes(n) {
  if (n == null) return '-';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(2)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function fmtNum(n) {
  if (n == null) return '-';
  return n.toLocaleString();
}

function parseEventKey(eventKey) {
  // tap@el_0030  or  swipe@el_0027|dir=down
  const m = /^([a-z_]+)@(el_\w+)(?:\|(.+))?$/i.exec(eventKey);
  if (!m) return { type: eventKey, elementId: null, extra: null, dir: null };
  let dir = null;
  if (m[3]) {
    const d = /dir=([a-z]+)/i.exec(m[3]);
    if (d) dir = d[1].toLowerCase();
  }
  return { type: m[1], elementId: m[2], extra: m[3] || null, dir };
}

// 새 스키마: screen_data.snapshots = { snapshot_id: { events: { event_key: stat } } }
// 구 스키마: screen_data.events     = { event_key: stat }
// 두 형식을 모두 같은 평탄화된 이벤트 목록으로 변환한다.
//   각 이벤트는 snapshot_id 필드를 갖는다 (구 스키마는 null).
function flattenScreen(screenData) {
  const out = [];
  if (screenData?.snapshots && typeof screenData.snapshots === 'object') {
    for (const [snapId, snap] of Object.entries(screenData.snapshots)) {
      const events = snap?.events || {};
      for (const [key, v] of Object.entries(events)) {
        out.push({
          event_key: key,
          snapshot_id: snapId === '_unknown_' ? null : snapId,
          tx_packets: v.tx_packets || 0,
          rx_packets: v.rx_packets || 0,
          tx_bytes:   v.tx_bytes   || 0,
          rx_bytes:   v.rx_bytes   || 0,
          total_bytes: (v.tx_bytes || 0) + (v.rx_bytes || 0),
        });
      }
    }
  } else if (screenData?.events && typeof screenData.events === 'object') {
    for (const [key, v] of Object.entries(screenData.events)) {
      out.push({
        event_key: key,
        snapshot_id: null,
        tx_packets: v.tx_packets || 0,
        rx_packets: v.rx_packets || 0,
        tx_bytes:   v.tx_bytes   || 0,
        rx_bytes:   v.rx_bytes   || 0,
        total_bytes: (v.tx_bytes || 0) + (v.rx_bytes || 0),
      });
    }
  }
  return out;
}

function aggregateScreen(screenData) {
  const events = flattenScreen(screenData);
  const snapshotSet = new Set();
  let tx_packets = 0, rx_packets = 0, tx_bytes = 0, rx_bytes = 0;
  for (const e of events) {
    tx_packets += e.tx_packets;
    rx_packets += e.rx_packets;
    tx_bytes   += e.tx_bytes;
    rx_bytes   += e.rx_bytes;
    if (e.snapshot_id) snapshotSet.add(e.snapshot_id);
  }
  return {
    eventCount: events.length,
    snapshotCount: snapshotSet.size,
    tx_packets, rx_packets, tx_bytes, rx_bytes,
    total_bytes: tx_bytes + rx_bytes,
    events,
  };
}

export default function PacketsTab({ run }) {
  const packetMem = run?.packetMemory;
  const screensRaw = packetMem?.screens || {};

  const aggregated = useMemo(() => {
    const out = {};
    for (const [sid, data] of Object.entries(screensRaw)) {
      out[sid] = aggregateScreen(data);
    }
    return out;
  }, [screensRaw]);

  const totals = useMemo(() => {
    let tx_packets = 0, rx_packets = 0, tx_bytes = 0, rx_bytes = 0, eventCount = 0;
    for (const v of Object.values(aggregated)) {
      tx_packets += v.tx_packets;
      rx_packets += v.rx_packets;
      tx_bytes   += v.tx_bytes;
      rx_bytes   += v.rx_bytes;
      eventCount += v.eventCount;
    }
    return {
      screenCount: Object.keys(aggregated).length,
      eventCount, tx_packets, rx_packets, tx_bytes, rx_bytes,
    };
  }, [aggregated]);

  const [screenSort, setScreenSort] = useState('total_bytes');
  const screenList = useMemo(() => {
    const list = Object.entries(aggregated).map(([sid, agg]) => ({ sid, ...agg }));
    list.sort((a, b) => (b[screenSort] || 0) - (a[screenSort] || 0));
    return list;
  }, [aggregated, screenSort]);

  const [selectedSid, setSelectedSid] = useState(null);
  const effectiveSid = selectedSid || screenList[0]?.sid || null;
  const selected = effectiveSid ? aggregated[effectiveSid] : null;

  const [modalEvent, setModalEvent] = useState(null);

  useEffect(() => {
    if (!modalEvent) return;
    const onKey = (e) => { if (e.key === 'Escape') setModalEvent(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [modalEvent]);

  if (!packetMem) {
    return <div className="run-empty">packet_memory.json 없음</div>;
  }
  if (!Object.keys(aggregated).length) {
    return <div className="run-empty">packet 기록이 있는 화면이 없습니다.</div>;
  }

  return (
    <div className="run-tab-content packets-tab">
      <aside className="pkt-list">
        <div className="pkt-list-summary">
          <div className="pkt-summary-row">
            <span className="pkt-summary-label">screens</span>
            <span className="pkt-summary-value">{totals.screenCount}</span>
          </div>
          <div className="pkt-summary-row">
            <span className="pkt-summary-label">events</span>
            <span className="pkt-summary-value">{totals.eventCount}</span>
          </div>
          <div className="pkt-summary-row">
            <span className="pkt-summary-label">TX</span>
            <span className="pkt-summary-value">
              {fmtNum(totals.tx_packets)} pkt · {fmtBytes(totals.tx_bytes)}
            </span>
          </div>
          <div className="pkt-summary-row">
            <span className="pkt-summary-label">RX</span>
            <span className="pkt-summary-value">
              {fmtNum(totals.rx_packets)} pkt · {fmtBytes(totals.rx_bytes)}
            </span>
          </div>
        </div>

        <div className="pkt-sort-group">
          <span className="pkt-sort-label">정렬</span>
          {SORT_KEYS.map(s => (
            <button
              key={s.key}
              className={`pkt-sort-btn ${screenSort === s.key ? 'active' : ''}`}
              onClick={() => setScreenSort(s.key)}
            >
              {s.label}
            </button>
          ))}
        </div>

        <div className="pkt-screen-rows">
          {screenList.map(s => (
            <ScreenRow
              key={s.sid}
              screen={s}
              selected={s.sid === effectiveSid}
              maxBytes={screenList[0]?.total_bytes || 1}
              onClick={() => setSelectedSid(s.sid)}
            />
          ))}
        </div>
      </aside>

      <section className="pkt-detail">
        {selected && (
          <ScreenPacketDetail
            sid={effectiveSid}
            agg={selected}
            run={run}
            onShowBbox={setModalEvent}
          />
        )}
      </section>

      {modalEvent && (
        <BboxModal event={modalEvent} run={run} onClose={() => setModalEvent(null)} />
      )}
    </div>
  );
}

function ScreenRow({ screen, selected, maxBytes, onClick }) {
  const widthPct = Math.max(1, Math.round((screen.total_bytes / maxBytes) * 100));
  return (
    <button
      className={`pkt-screen-row ${selected ? 'selected' : ''}`}
      onClick={onClick}
    >
      <div className="pkt-screen-row-head">
        <code className="pkt-sid">{screen.sid.slice(0, 12)}</code>
        <span className="pkt-events-count">
          {screen.eventCount} ev
          {screen.snapshotCount > 0 && ` · ${screen.snapshotCount} snap`}
        </span>
      </div>
      <div className="pkt-screen-bar-track">
        <div className="pkt-screen-bar-fill" style={{ width: `${widthPct}%` }} />
      </div>
      <div className="pkt-screen-row-stats">
        <span>↑ {fmtBytes(screen.tx_bytes)}</span>
        <span>↓ {fmtBytes(screen.rx_bytes)}</span>
        <span className="pkt-screen-total">Σ {fmtBytes(screen.total_bytes)}</span>
      </div>
    </button>
  );
}

function ScreenPacketDetail({ sid, agg, run, onShowBbox }) {
  const [eventSort, setEventSort] = useState('total_bytes');
  const [eventTypeFilter, setEventTypeFilter] = useState('all');
  const [snapshotFilter, setSnapshotFilter] = useState('all');
  const [query, setQuery] = useState('');

  const appScreen = run?.appMemory?.screens?.[sid];
  const elementById = useMemo(() => {
    const m = {};
    for (const el of appScreen?.elements || []) m[el.element_id] = el;
    return m;
  }, [appScreen]);

  const eventTypes = useMemo(() => {
    const set = new Set();
    for (const e of agg.events) set.add(parseEventKey(e.event_key).type);
    return ['all', ...Array.from(set).sort()];
  }, [agg]);

  const snapshotIds = useMemo(() => {
    const set = new Set();
    for (const e of agg.events) if (e.snapshot_id) set.add(e.snapshot_id);
    return ['all', ...Array.from(set).sort()];
  }, [agg]);

  const events = useMemo(() => {
    let list = agg.events.map(e => {
      const parsed = parseEventKey(e.event_key);
      const el = parsed.elementId ? elementById[parsed.elementId] : null;
      return { ...e, parsed, element: el };
    });
    if (eventTypeFilter !== 'all') {
      list = list.filter(e => e.parsed.type === eventTypeFilter);
    }
    if (snapshotFilter !== 'all') {
      list = list.filter(e => e.snapshot_id === snapshotFilter);
    }
    if (query.trim()) {
      const q = query.toLowerCase();
      list = list.filter(e =>
        e.event_key.toLowerCase().includes(q) ||
        (e.element?.text || '').toLowerCase().includes(q) ||
        (e.element?.description || '').toLowerCase().includes(q) ||
        (e.element?.resource_id || '').toLowerCase().includes(q) ||
        (e.snapshot_id || '').toLowerCase().includes(q)
      );
    }
    list.sort((a, b) => (b[eventSort] || 0) - (a[eventSort] || 0));
    return list;
  }, [agg, eventSort, eventTypeFilter, snapshotFilter, query, elementById]);

  const maxBytes = events[0]?.total_bytes || 1;

  const headerSnapshot =
    appScreen?.snapshots?.[0] || null;
  const snapUrl = headerSnapshot ? run?.blobMap?.[headerSnapshot] : null;

  return (
    <div className="pkt-detail-root">
      <header className="pkt-detail-header">
        <div className="pkt-detail-head-text">
          <h3><code>{sid}</code></h3>
          <div className="pkt-detail-subtitle">
            {appScreen?.activity && <span><strong>activity</strong>: <code>{appScreen.activity}</code></span>}
            <span> · <strong>events</strong>: {agg.eventCount}</span>
            <span> · <strong>TX</strong>: {fmtNum(agg.tx_packets)} pkt / {fmtBytes(agg.tx_bytes)}</span>
            <span> · <strong>RX</strong>: {fmtNum(agg.rx_packets)} pkt / {fmtBytes(agg.rx_bytes)}</span>
          </div>
        </div>
        {snapUrl && (
          <figure className="pkt-detail-snap">
            <img src={snapUrl} alt={headerSnapshot} />
            <figcaption>{headerSnapshot}</figcaption>
          </figure>
        )}
      </header>

      <div className="pkt-detail-toolbar">
        <div className="pkt-sort-group">
          <span className="pkt-sort-label">정렬</span>
          {SORT_KEYS.map(s => (
            <button
              key={s.key}
              className={`pkt-sort-btn ${eventSort === s.key ? 'active' : ''}`}
              onClick={() => setEventSort(s.key)}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="pkt-filter-group">
          {eventTypes.map(t => (
            <button
              key={t}
              className={`pkt-filter-btn ${eventTypeFilter === t ? 'active' : ''}`}
              onClick={() => setEventTypeFilter(t)}
            >
              {t}
            </button>
          ))}
        </div>
        {snapshotIds.length > 1 && (
          <div className="pkt-filter-group">
            <span className="pkt-sort-label">snap</span>
            {snapshotIds.map(s => (
              <button
                key={s}
                className={`pkt-filter-btn ${snapshotFilter === s ? 'active' : ''}`}
                onClick={() => setSnapshotFilter(s)}
              >
                {s}
              </button>
            ))}
          </div>
        )}
        <input
          className="pkt-search"
          placeholder="event_key / element / snapshot 검색…"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
      </div>

      <div className="pkt-table-wrap">
        <table className="pkt-table">
          <thead>
            <tr>
              <th>event</th>
              <th>snapshot</th>
              <th>element</th>
              <th>TX pkt</th>
              <th>RX pkt</th>
              <th>TX bytes</th>
              <th>RX bytes</th>
              <th>volume</th>
            </tr>
          </thead>
          <tbody>
            {events.map(e => {
              const el = e.element;
              const widthPct = Math.max(1, Math.round((e.total_bytes / maxBytes) * 100));
              const hasBbox = Array.isArray(el?.bbox) && el.bbox.length === 4;
              const rowKey = `${e.event_key}::${e.snapshot_id || '_'}`;
              return (
                <tr
                  key={rowKey}
                  className={hasBbox ? 'pkt-row-clickable' : ''}
                  onClick={hasBbox ? () => onShowBbox({ ...e, sid, screen: appScreen }) : undefined}
                  title={hasBbox ? '클릭해서 element bbox 보기' : ''}
                >
                  <td>
                    <code className="pkt-ev-key">{e.event_key}</code>
                    <div className="pkt-ev-meta">
                      <span className={`pkt-ev-type pkt-ev-type-${e.parsed.type}`}>{e.parsed.type}</span>
                      {e.parsed.extra && <span className="pkt-ev-extra">{e.parsed.extra}</span>}
                      {hasBbox && <span className="pkt-ev-bbox-hint">🔍 bbox</span>}
                    </div>
                  </td>
                  <td className="pkt-snap-cell">
                    {e.snapshot_id
                      ? <code className="pkt-snap-id">{e.snapshot_id}</code>
                      : <span className="run-muted">—</span>}
                  </td>
                  <td className="pkt-el-cell">
                    {el ? (
                      <>
                        <div className="pkt-el-text">{el.text || el.description || <em className="run-muted">(no text)</em>}</div>
                        <div className="pkt-el-meta">
                          <span>{el.class?.split('.').pop()}</span>
                          {el.resource_id && <code className="pkt-el-rid">{el.resource_id}</code>}
                        </div>
                      </>
                    ) : (
                      <span className="run-muted">{e.parsed.elementId || '—'}</span>
                    )}
                  </td>
                  <td className="pkt-num">{fmtNum(e.tx_packets)}</td>
                  <td className="pkt-num">{fmtNum(e.rx_packets)}</td>
                  <td className="pkt-num">{fmtBytes(e.tx_bytes)}</td>
                  <td className="pkt-num">{fmtBytes(e.rx_bytes)}</td>
                  <td className="pkt-vol-cell">
                    <div className="pkt-vol-bar-track">
                      <div className="pkt-vol-bar-fill" style={{ width: `${widthPct}%` }} />
                    </div>
                    <span className="pkt-vol-text">{fmtBytes(e.total_bytes)}</span>
                  </td>
                </tr>
              );
            })}
            {events.length === 0 && (
              <tr><td colSpan={8}><div className="run-muted">조건에 맞는 이벤트 없음</div></td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BboxModal({ event, run, onClose }) {
  const el = event.element;
  const bbox = el?.bbox;
  const screen = event.screen;
  const blobMap = run?.blobMap || {};

  // 스냅샷 선택: (1) 이벤트가 실제 측정된 snapshot_id가 있으면 그걸 우선,
  // (2) 없으면 화면의 첫 snapshot, (3) 그것도 없으면 마지막 snapshot.
  const snapshotId =
    event.snapshot_id ||
    screen?.snapshots?.[0] ||
    screen?.snapshots?.[screen?.snapshots?.length - 1] ||
    null;
  const imgUrl = snapshotId ? blobMap[snapshotId] : null;

  const [natural, setNatural] = useState({ w: 0, h: 0 });

  if (!bbox || bbox.length !== 4) return null;

  const [left, top, right, bottom] = bbox;
  const w = right - left;
  const h = bottom - top;

  // 자연 이미지 크기가 잡히기 전엔 device meta로 대체
  const refW = natural.w || run?.meta?.device?.screen_width || 1080;
  const refH = natural.h || run?.meta?.device?.screen_height || 2400;

  const style = {
    left:   `${(left   / refW) * 100}%`,
    top:    `${(top    / refH) * 100}%`,
    width:  `${(w      / refW) * 100}%`,
    height: `${(h      / refH) * 100}%`,
  };

  return (
    <div className="bbox-modal-backdrop" onClick={onClose}>
      <div className="bbox-modal" onClick={(e) => e.stopPropagation()}>
        <header className="bbox-modal-head">
          <div className="bbox-modal-head-text">
            <code className="bbox-modal-key">{event.event_key}</code>
            <div className="bbox-modal-sub">
              <span><strong>screen</strong>: <code>{event.sid?.slice(0, 12)}</code></span>
              {snapshotId && <span> · <strong>snap</strong>: <code>{snapshotId}</code></span>}
              <span> · <strong>bbox</strong>: <code>[{left}, {top}, {right}, {bottom}]</code></span>
              <span> · <strong>size</strong>: <code>{w} × {h}</code> px</span>
            </div>
          </div>
          <button className="bbox-modal-close" onClick={onClose} aria-label="close">✕</button>
        </header>

        <div className="bbox-modal-body">
          <div className="bbox-image-wrap">
            {imgUrl ? (
              <div
                className="bbox-image-frame"
                style={{ aspectRatio: `${refW} / ${refH}` }}
              >
                <img
                  src={imgUrl}
                  alt={snapshotId || ''}
                  className="bbox-image"
                  onLoad={(e) => setNatural({ w: e.target.naturalWidth, h: e.target.naturalHeight })}
                />
                <div className="bbox-overlay" style={style}>
                  {event.parsed?.type === 'swipe' && event.parsed?.dir && (
                    <span className={`bbox-swipe-arrow bbox-swipe-${event.parsed.dir}`}>
                      {arrowFor(event.parsed.dir)}
                    </span>
                  )}
                </div>
              </div>
            ) : (
              <div className="run-muted bbox-no-image">스냅샷 이미지를 찾을 수 없습니다.</div>
            )}
          </div>

          <aside className="bbox-info">
            <h4>Element</h4>
            <dl className="bbox-info-dl">
              <dt>id</dt><dd><code>{el?.element_id}</code></dd>
              <dt>class</dt><dd><code>{el?.class}</code></dd>
              <dt>resource-id</dt><dd><code>{el?.resource_id || '—'}</code></dd>
              <dt>text</dt><dd>{el?.text || <span className="run-muted">—</span>}</dd>
              <dt>desc</dt><dd>{el?.description || <span className="run-muted">—</span>}</dd>
              <dt>scrollable</dt><dd>{el?.is_scrollable ? 'yes' : 'no'}</dd>
            </dl>

            <h4>Packets</h4>
            <dl className="bbox-info-dl">
              <dt>TX</dt><dd>{fmtNum(event.tx_packets)} pkt · {fmtBytes(event.tx_bytes)}</dd>
              <dt>RX</dt><dd>{fmtNum(event.rx_packets)} pkt · {fmtBytes(event.rx_bytes)}</dd>
              <dt>총합</dt><dd>{fmtBytes(event.total_bytes)}</dd>
            </dl>
          </aside>
        </div>
      </div>
    </div>
  );
}

function arrowFor(dir) {
  switch (dir) {
    case 'up':    return '↑';
    case 'down':  return '↓';
    case 'left':  return '←';
    case 'right': return '→';
    default:      return '·';
  }
}
