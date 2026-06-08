import { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import './live-monitor.css';

const EVENT_CAP = 300;
const PACKET_INTERVAL_MS = 3000;

function parseBounds(b) {
  const m = /\[(\d+),(\d+)\]\[(\d+),(\d+)\]/.exec(b || '');
  if (!m) return null;
  return { x1: +m[1], y1: +m[2], x2: +m[3], y2: +m[4] };
}

function shortClass(c) {
  if (!c) return '';
  const parts = c.split('.');
  return parts[parts.length - 1];
}

// uiautomator XML → 트리 노드
function buildTree(xmlText) {
  const doc = new DOMParser().parseFromString(xmlText, 'application/xml');
  if (doc.querySelector('parsererror')) return null;
  const root = doc.querySelector('hierarchy');
  if (!root) return null;
  let idc = 0;
  const walk = (el, depth) => {
    const attrs = {};
    for (const a of el.attributes) attrs[a.name] = a.value;
    const node = {
      uid: idc++,
      tag: el.tagName,
      attrs,
      bounds: parseBounds(attrs.bounds),
      depth,
      children: [],
    };
    for (const child of el.children) {
      if (child.tagName === 'node') node.children.push(walk(child, depth + 1));
    }
    return node;
  };
  const top = { uid: idc++, tag: 'hierarchy', attrs: {}, bounds: null, depth: 0, children: [] };
  for (const child of root.children) {
    if (child.tagName === 'node') top.children.push(walk(child, 1));
  }
  return top;
}

function TreeNode({ node, selected, onSelect, defaultDepth }) {
  const [open, setOpen] = useState(node.depth < defaultDepth);
  // 부모에서 defaultDepth가 바뀌면 (전체 펼치기/접기) 동기화. 수동 토글로 둔 노드도
  // 일괄 리셋되는 게 의도다.
  useEffect(() => { setOpen(node.depth < defaultDepth); }, [defaultDepth, node.depth]);
  if (node.tag === 'hierarchy') {
    return <div>{node.children.map(c => <TreeNode key={c.uid} node={c} selected={selected} onSelect={onSelect} defaultDepth={defaultDepth} />)}</div>;
  }
  const a = node.attrs;
  const label = shortClass(a.class) || a.tag;
  const text = a.text || a['content-desc'] || '';
  const rid = a['resource-id'] ? a['resource-id'].split('/').pop() : '';
  const hasKids = node.children.length > 0;
  return (
    <div className="lm-tree-node">
      <div
        className={`lm-tree-row ${selected === node.uid ? 'sel' : ''}`}
        style={{ paddingLeft: 4 + node.depth * 12 }}
        onClick={() => onSelect(node)}
      >
        <span
          className="lm-tree-caret"
          onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}
        >
          {hasKids ? (open ? '▾' : '▸') : '·'}
        </span>
        <span className="lm-tree-class">{label}</span>
        {rid && <span className="lm-tree-rid">#{rid}</span>}
        {text && <span className="lm-tree-text">"{text.slice(0, 24)}"</span>}
      </div>
      {open && hasKids && node.children.map(c => (
        <TreeNode key={c.uid} node={c} selected={selected} onSelect={onSelect} defaultDepth={defaultDepth} />
      ))}
    </div>
  );
}

export default function LiveMonitor() {
  const [devices, setDevices] = useState([]);
  const [serial, setSerial] = useState('');
  const [pkg, setPkg] = useState('com.xiaomi.smarthome');

  const [listenerRunning, setListenerRunning] = useState(false);
  const [eventsOn, setEventsOn] = useState(false);
  const [screenSrc, setScreenSrc] = useState(null);  // XML 가져올 때만 갱신
  const [imgNatural, setImgNatural] = useState({ w: 0, h: 0 });

  const [events, setEvents] = useState([]);
  const [packet, setPacket] = useState({ cur: null, delta: null });
  const [tree, setTree] = useState(null);
  const [rawXml, setRawXml] = useState('');         // 저장 시 그대로 전송
  const [screenBlob, setScreenBlob] = useState(null);// 브라우저가 본 PNG 바이트
  const [selNode, setSelNode] = useState(null);
  const [treeDepth, setTreeDepth] = useState(3);    // 기본 3단계, 펼치기/접기로 토글
  const [saveDir, setSaveDir] = useState('');       // 빈 값 = 서버 기본(outputs_APK/_monitor_snapshots/<YYYYMMDD>)
  const [saveStatus, setSaveStatus] = useState('');
  const [tab, setTab] = useState('events');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const imgRef = useRef(null);
  const esRef = useRef(null);
  const prevPacket = useRef(null);

  const sd = serial ? `&serial=${serial}` : '';

  // 기기 + 리스너 상태 로드
  const loadDevices = useCallback(async () => {
    try {
      const res = await axios.get('/api/adb/devices');
      const list = res.data.devices || [];
      setDevices(list);
      setSerial(prev => (prev && list.some(d => d.serial === prev)) ? prev : (list[0]?.serial || ''));
    } catch (e) { setMsg('기기 목록 실패: ' + e.message); }
  }, []);
  const refreshStatus = useCallback(async () => {
    try {
      const res = await axios.get('/api/adb/listener/status');
      setListenerRunning(!!res.data.running);
    } catch (e) { /* noop */ }
  }, []);
  useEffect(() => { loadDevices(); refreshStatus(); }, [loadDevices, refreshStatus]);

  // a11y 이벤트 SSE
  useEffect(() => {
    if (!eventsOn) {
      if (esRef.current) { esRef.current.close(); esRef.current = null; }
      return;
    }
    const es = new EventSource(`/api/adb/events?serial=${serial}`);
    esRef.current = es;
    es.onmessage = (ev) => {
      try {
        const j = JSON.parse(ev.data);
        setEvents(prev => [j, ...prev].slice(0, EVENT_CAP));
      } catch (_) { /* skip */ }
    };
    es.onerror = () => { /* keep retrying; EventSource auto-reconnects */ };
    return () => { es.close(); if (esRef.current === es) esRef.current = null; };
  }, [eventsOn, serial]);

  // 패킷 폴링
  useEffect(() => {
    if (!pkg || !serial) return;
    let stop = false;
    prevPacket.current = null;  // 패키지/기기 전환 시 델타 기준 리셋
    setPacket({ cur: null, delta: null });
    const poll = async () => {
      try {
        const res = await axios.get(`/api/adb/packets?pkg=${encodeURIComponent(pkg)}${sd}`);
        if (stop) return;
        const cur = res.data;
        const before = prevPacket.current;
        const delta = before ? {
          tx_packets: Math.max(0, cur.tx_packets - before.tx_packets),
          rx_packets: Math.max(0, cur.rx_packets - before.rx_packets),
          tx_bytes: Math.max(0, cur.tx_bytes - before.tx_bytes),
          rx_bytes: Math.max(0, cur.rx_bytes - before.rx_bytes),
        } : null;
        prevPacket.current = cur;
        setPacket({ cur, delta });
      } catch (e) { /* idle/idle */ }
    };
    poll();
    const id = setInterval(poll, PACKET_INTERVAL_MS);
    return () => { stop = true; clearInterval(id); };
  }, [pkg, serial, sd]);

  // ── 액션 ──────────────────────────────────────────────────────
  const startListener = async () => {
    setBusy(true); setMsg('리스너 시작 중…');
    try {
      await axios.post('/api/adb/listener/start', { serial: serial || undefined });
      setListenerRunning(true);
      setEventsOn(true);
      setMsg('리스너 실행 중 (Python observe와 동시 실행 금지)');
    } catch (e) { setMsg('시작 실패: ' + (e.response?.data?.error || e.message)); }
    finally { setBusy(false); }
  };
  const stopListener = async () => {
    setBusy(true); setMsg('리스너 중지 중…');
    try {
      await axios.post('/api/adb/listener/stop', { serial: serial || undefined });
      setListenerRunning(false);
      setMsg('리스너 중지됨');
    } catch (e) { setMsg('중지 실패: ' + (e.response?.data?.error || e.message)); }
    finally { setBusy(false); }
  };
  const fetchXml = async () => {
    setBusy(true); setMsg('현재 화면 + XML 가져오는 중…');
    setSaveStatus('');
    // 1) 화면 PNG 를 blob 으로 받아 메모리에 보유 — 표시용 URL + 저장용 바이트.
    //    저장 시 재캡처하지 않고 이 바이트를 그대로 디스크에 기록하여 XML 과
    //    실제 사용자가 본 화면의 짝이 어긋나지 않게 한다.
    try {
      const scr = await axios.get(`/api/adb/screen?t=${Date.now()}${sd}`, { responseType: 'blob' });
      if (screenSrc && screenSrc.startsWith('blob:')) URL.revokeObjectURL(screenSrc);
      setScreenBlob(scr.data);
      setScreenSrc(URL.createObjectURL(scr.data));
    } catch (e) {
      setMsg('화면 캡처 실패: ' + (e.response?.data?.error || e.message));
      setBusy(false);
      return;
    }
    // 2) XML dump (trigger → DUMP_WRITTEN → pull). 이 단계는 리스너 실행 필요.
    try {
      const res = await axios.post('/api/adb/dump', { serial: serial || undefined });
      const t = buildTree(res.data.xml);
      setRawXml(res.data.xml || '');
      setTree(t);
      setSelNode(null);
      setTab('xml');
      setMsg(t ? `XML 로드됨 (${res.data.screenW}x${res.data.screenH})` : 'XML 파싱 실패');
    } catch (e) { setMsg('dump 실패: ' + (e.response?.data?.error || e.message)); }
    finally { setBusy(false); }
  };

  // blob → base64 (FileReader 비동기)
  const blobToBase64 = (blob) => new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',').pop());
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });

  const saveSnapshot = async () => {
    if (!rawXml || !screenBlob) {
      setSaveStatus('저장할 스냅샷이 없습니다. 먼저 ‘현재 화면 XML 가져오기’를 누르세요.');
      return;
    }
    setBusy(true); setSaveStatus('저장 중…');
    try {
      const png_base64 = await blobToBase64(screenBlob);
      const res = await axios.post('/api/adb/snapshot', {
        xml: rawXml,
        png_base64,
        dir: saveDir || undefined,
      });
      const kb = (n) => (n / 1024).toFixed(1) + 'KB';
      setSaveStatus(`저장됨 · ${res.data.xmlPath} (${kb(res.data.xmlBytes)}) · ${res.data.pngPath} (${kb(res.data.pngBytes)})`);
    } catch (e) {
      setSaveStatus('저장 실패: ' + (e.response?.data?.error || e.message));
    } finally { setBusy(false); }
  };

  // 선택 노드 bbox (이미지 natural 기준 % 좌표)
  const overlay = (() => {
    if (!selNode?.bounds || !imgNatural.w) return null;
    const b = selNode.bounds;
    return {
      left: `${(b.x1 / imgNatural.w) * 100}%`,
      top: `${(b.y1 / imgNatural.h) * 100}%`,
      width: `${((b.x2 - b.x1) / imgNatural.w) * 100}%`,
      height: `${((b.y2 - b.y1) / imgNatural.h) * 100}%`,
    };
  })();

  return (
    <div className="lm">
      <div className="lm-toolbar">
        <span className="lm-title">📺 라이브 모니터</span>
        <label className="lm-field">기기:
          <select value={serial} onChange={e => setSerial(e.target.value)}>
            {devices.length === 0 && <option value="">(없음)</option>}
            {devices.map(d => <option key={d.serial} value={d.serial}>{d.model || d.serial}</option>)}
          </select>
        </label>
        <button className="lm-mini" onClick={() => { loadDevices(); refreshStatus(); }}>🔄</button>
        <span className={`lm-status ${listenerRunning ? 'on' : 'off'}`}>
          ● 리스너 {listenerRunning ? 'ON' : 'OFF'}
        </span>
        {listenerRunning
          ? <button className="lm-mini danger" onClick={stopListener} disabled={busy}>리스너 중지</button>
          : <button className="lm-mini accent" onClick={startListener} disabled={busy}>리스너 시작</button>}
        <div className="lm-spacer" />
        <label className="lm-check"><input type="checkbox" checked={eventsOn} onChange={e => setEventsOn(e.target.checked)} /> 이벤트 수신</label>
      </div>
      {msg && <div className="lm-msg">{msg}</div>}

      <div className="lm-body">
        {/* 좌: 스냅샷 화면 (XML 가져올 때만 갱신) + bbox 오버레이 */}
        <div className="lm-screen-col">
          <div className="lm-screen-wrap">
            {screenSrc ? (
              <img
                ref={imgRef}
                className="lm-screen"
                src={screenSrc}
                alt="screen snapshot"
                onLoad={e => setImgNatural({ w: e.target.naturalWidth, h: e.target.naturalHeight })}
              />
            ) : (
              <div className="lm-screen-off">‘현재 화면 XML 가져오기’ 누르면<br />여기에 스냅샷이 표시됩니다</div>
            )}
            {overlay && <div className="lm-bbox" style={overlay} />}
          </div>
          <div className="lm-screen-hint">
            XML 가져올 때만 갱신
            {imgNatural.w ? ` · ${imgNatural.w}×${imgNatural.h}` : ''}
          </div>
        </div>

        {/* 우: 탭 (이벤트 / 패킷 / XML) */}
        <div className="lm-side">
          <div className="lm-tabs">
            <button className={tab === 'events' ? 'active' : ''} onClick={() => setTab('events')}>a11y 이벤트 ({events.length})</button>
            <button className={tab === 'packets' ? 'active' : ''} onClick={() => setTab('packets')}>패킷</button>
            <button className={tab === 'xml' ? 'active' : ''} onClick={() => setTab('xml')}>XML</button>
          </div>

          {tab === 'events' && (
            <div className="lm-events">
              {!eventsOn && <div className="lm-empty">‘이벤트 수신’을 켜세요 (리스너 실행 필요).</div>}
              {events.map((e, i) => (
                <div key={i} className={`lm-evt t-${e.type}`}>
                  <span className="lm-evt-type">{e.type}</span>
                  {e.change && <span className="lm-evt-tag">{e.change}</span>}
                  {e.class && <span className="lm-evt-cls">{shortClass(e.class)}</span>}
                  {e.text && <span className="lm-evt-text">"{String(e.text).slice(0, 30)}"</span>}
                  {e.props && <span className="lm-evt-props">{e.props}</span>}
                </div>
              ))}
            </div>
          )}

          {tab === 'packets' && (
            <div className="lm-packets">
              <label className="lm-field">패키지:
                <input value={pkg} onChange={e => setPkg(e.target.value)} placeholder="com.xiaomi.smarthome" />
              </label>
              {packet.cur ? (
                <>
                  <div className="lm-pkt-row"><span>UID</span><b>{packet.cur.uid}</b></div>
                  <div className="lm-pkt-grid">
                    <div className="lm-pkt-cell"><span>TX pkts</span><b>{packet.cur.tx_packets}</b><em>+{packet.delta?.tx_packets ?? 0}</em></div>
                    <div className="lm-pkt-cell"><span>RX pkts</span><b>{packet.cur.rx_packets}</b><em>+{packet.delta?.rx_packets ?? 0}</em></div>
                    <div className="lm-pkt-cell"><span>TX bytes</span><b>{packet.cur.tx_bytes}</b><em>+{packet.delta?.tx_bytes ?? 0}</em></div>
                    <div className="lm-pkt-cell"><span>RX bytes</span><b>{packet.cur.rx_bytes}</b><em>+{packet.delta?.rx_bytes ?? 0}</em></div>
                  </div>
                  <div className="lm-pkt-note">{Math.round(PACKET_INTERVAL_MS / 1000)}초마다 갱신 · +값은 직전 대비 증가분</div>
                </>
              ) : <div className="lm-empty">패키지 UID 해석 중이거나 트래픽 없음.</div>}
            </div>
          )}

          {tab === 'xml' && (
            <div className="lm-xml">
              <div className="lm-xml-bar">
                <button className="lm-mini accent" onClick={fetchXml} disabled={busy}>현재 화면 XML 가져오기</button>
                {tree && <>
                  <button className="lm-mini" onClick={() => setTreeDepth(99)}>▼ 전체 펼치기</button>
                  <button className="lm-mini" onClick={() => setTreeDepth(1)}>▲ 전체 접기</button>
                  <span className="lm-xml-sel">깊이: {treeDepth === 99 ? 'all' : treeDepth}</span>
                </>}
              </div>
              <div className="lm-xml-bar">
                <button className="lm-mini accent" onClick={saveSnapshot} disabled={busy || !rawXml || !screenBlob}>
                  💾 저장 (xml + png)
                </button>
                <label className="lm-field">폴더:
                  <input
                    value={saveDir}
                    onChange={e => setSaveDir(e.target.value)}
                    placeholder="(기본: outputs_APK/_monitor_snapshots/<날짜>)"
                    style={{ minWidth: '300px' }}
                  />
                </label>
                {saveStatus && <span className="lm-xml-sel">{saveStatus}</span>}
              </div>
              <div className="lm-tree">
                {tree ? <TreeNode node={tree} selected={selNode?.uid} onSelect={setSelNode} defaultDepth={treeDepth} />
                  : <div className="lm-empty">XML을 가져오면 트리가 표시됩니다. 노드 클릭 시 좌측 화면에 bbox 표시.</div>}
              </div>
              {selNode && (
                <div className="lm-node-detail">
                  <div className="lm-node-detail-head">선택 노드 상세</div>
                  <table className="lm-attr-table">
                    <tbody>
                      {Object.entries(selNode.attrs).map(([k, v]) => (
                        <tr key={k}><td>{k}</td><td>{String(v) || <em>(빈값)</em>}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
