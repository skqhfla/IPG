import { useEffect, useState, useMemo } from 'react';
import axios from 'axios';
import { parseHierarchyMeta, shortActivity } from '../utils/xmlMeta.js';
import './screen-id-inspector.css';

// Screen ID 검사 탭.
// 흐름:
//   1) 마운트 시 서버가 디폴트 위치(outputs_APK, outputs)를 자동 스캔.
//      run override 가 필요하면 [고급] 토글로 루트를 직접 입력.
//   2) 드롭다운에서 run 선택 → snapshot 드롭다운
//   3) 검사 → 좌측에 screen 이미지, 우측에 빌드 trace + 매칭 시뮬레이션
// 선택값은 localStorage 에 캐시.

const LS = {
  root: 'sid_inspect_root',
  runDir: 'sid_inspect_run_dir',
  snapshot: 'sid_inspect_snapshot',
  pinned: 'sid_inspect_pinned',
};

// 비교 핀: { dir: [snapshotId, ...] } 형태로 run 별로 분리 보관.
// 같은 run 안에서만 비교가 의미 있으므로(매처 버킷·signature 비교가 run 종속이 아닌
// XML 만으로도 가능하지만, screen/{id}.png 같은 부가 자원이 dir 에 매여 있음) run 을
// 바꾸면 이전 run 의 핀은 그대로 두되 보이지 않게 된다.
function loadPinned() {
  try {
    return JSON.parse(localStorage.getItem(LS.pinned) || '{}');
  } catch {
    return {};
  }
}
function savePinned(state) {
  localStorage.setItem(LS.pinned, JSON.stringify(state));
}

export default function ScreenIdInspector({ externalDir, externalDump, onClearExternalDump } = {}) {
  const [root, setRoot] = useState(localStorage.getItem(LS.root) || '');
  const [scannedRoots, setScannedRoots] = useState([]);
  const [runs, setRuns] = useState([]);
  const [dir, setDir] = useState(localStorage.getItem(LS.runDir) || '');
  const [snapshots, setSnapshots] = useState([]);
  const [snapshotId, setSnapshotId] = useState(localStorage.getItem(LS.snapshot) || '');
  const [threshold, setThreshold] = useState(0.6);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  // 비교 핀: run dir 별 snapshotId 배열
  const [pinned, setPinned] = useState(loadPinned);
  const pinnedForDir = pinned[dir] || [];
  const [compareData, setCompareData] = useState(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState('');

  const togglePin = (sid) => {
    setPinned(prev => {
      const cur = prev[dir] || [];
      const next = cur.includes(sid) ? cur.filter(x => x !== sid) : [...cur, sid];
      const map = { ...prev, [dir]: next };
      savePinned(map);
      return map;
    });
  };
  const clearPins = () => {
    setPinned(prev => {
      const map = { ...prev };
      delete map[dir];
      savePinned(map);
      return map;
    });
  };

  const persistRoot = (v) => { setRoot(v); localStorage.setItem(LS.root, v); };
  const persistDir = (v) => { setDir(v); localStorage.setItem(LS.runDir, v); };
  const persistSnap = (v) => { setSnapshotId(v); localStorage.setItem(LS.snapshot, v); };

  const loadRuns = async (rootArg) => {
    // rootArg === undefined → state 의 root 사용. 그게 빈 문자열이면 서버가
    // 디폴트(outputs_APK, outputs) 자동 스캔. rootArg === '' 도 명시적 디폴트로 처리.
    const target = rootArg ?? root;
    setError('');
    setRuns([]);
    setLoading(true);
    try {
      const params = target ? { root: target } : {};
      const res = await axios.get('/api/list-runs', { params });
      const arr = res.data?.runs || [];
      setRuns(arr);
      setScannedRoots(res.data?.roots || []);
      if (arr.length && !arr.find(r => r.path === dir)) {
        persistDir(arr[0].path);
      }
    } catch (e) {
      setError(e.response?.data?.error || e.message);
    } finally {
      setLoading(false);
    }
  };

  const loadSnapshots = async (dirArg) => {
    const target = dirArg ?? dir;
    setError('');
    setSnapshots([]);
    if (!target) return;
    setLoading(true);
    try {
      const res = await axios.get('/api/run/snapshots', { params: { dir: target } });
      const ids = res.data?.snapshots || [];
      setSnapshots(ids);
      if (ids.length && !ids.includes(snapshotId)) {
        persistSnap(ids[0]);
      }
    } catch (e) {
      setError(e.response?.data?.error || e.message);
    } finally {
      setLoading(false);
    }
  };

  const inspect = async () => {
    if (!dir || !snapshotId) {
      setError('run 과 snapshot 을 모두 지정하세요.');
      return;
    }
    setError('');
    setLoading(true);
    setResult(null);
    try {
      const res = await axios.get('/api/run/inspect-screen-id', {
        params: { dir, snapshotId, threshold },
      });
      setResult(res.data);
    } catch (e) {
      setError(e.response?.data?.error || e.message);
    } finally {
      setLoading(false);
    }
  };

  // 마운트 시 항상 list-runs 자동 호출. root 비어 있으면 서버 디폴트 사용.
  useEffect(() => {
    (async () => {
      await loadRuns();
      if (dir) await loadSnapshots(dir);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 외부(Sidebar → App)에서 dir 이 push 되면 내부 state 와 sync. 새 경로면
  // run 리스트에 강제로 추가하고 snapshot 도 자동 로드. 같은 dir 이면 noop.
  useEffect(() => {
    if (!externalDir || externalDir === dir) return;
    persistDir(externalDir);
    setRuns(prev => {
      if (prev.some(r => r.path === externalDir)) return prev;
      const parts = externalDir.split(/[\\/]/).filter(Boolean);
      return [
        {
          path: externalDir,
          name: parts[parts.length - 1] || externalDir,
          parent: parts[parts.length - 2] || '',
          modified: Date.now(),
          partial: false,
          external: true,
        },
        ...prev,
      ];
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalDir]);

  // dir 이 바뀌면 snapshots 갱신
  useEffect(() => {
    if (dir) loadSnapshots(dir);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dir]);

  // snapshot 이 바뀌면(=드롭다운 선택) 자동으로 검사. threshold 변경은 입력 중
  // 매 키 입력마다 fetch 되면 깜빡이므로 명시적 🔍 버튼으로만 재실행한다.
  useEffect(() => {
    if (dir && snapshotId && snapshots.includes(snapshotId)) {
      inspect();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dir, snapshotId, snapshots]);

  // 외부 dump (기기 제어에서 push) — XML 본문을 그대로 inspect-screen-id-text
  // 로 흘려 분석. dir 이 지정돼 있으면 그 run 의 app_memory 와 매치도 같이.
  // dump 객체는 ts 가 있으므로 같은 ts 면 중복 호출 안 함.
  const [dumpResult, setDumpResult] = useState(null);
  const [dumpLoading, setDumpLoading] = useState(false);
  const [dumpError, setDumpError] = useState('');
  const [dumpCompareDir, setDumpCompareDir] = useState('');
  const lastDumpTsRef = useState({ ts: 0 })[0];

  const inspectDump = async (dumpObj, compareDir) => {
    if (!dumpObj?.xml) return;
    setDumpError('');
    setDumpLoading(true);
    setDumpResult(null);
    try {
      const res = await axios.post('/api/inspect-screen-id-text', {
        xml: dumpObj.xml,
        label: dumpObj.label,
        threshold,
        dir: compareDir || undefined,
      });
      setDumpResult(res.data);
    } catch (e) {
      setDumpError(e.response?.data?.error || e.message);
    } finally {
      setDumpLoading(false);
    }
  };

  useEffect(() => {
    if (!externalDump) return;
    if (externalDump.ts === lastDumpTsRef.ts) return; // 이미 분석함
    lastDumpTsRef.ts = externalDump.ts;
    inspectDump(externalDump, dumpCompareDir);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalDump]);

  // compareDir 변경 시 마지막 dump 를 재분석
  useEffect(() => {
    if (externalDump?.xml && dumpResult !== null) {
      inspectDump(externalDump, dumpCompareDir);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dumpCompareDir]);

  // 비교 자동 실행: 항목 = (externalDump 가상 컬럼) + (핀된 run snapshots).
  // 2개 이상이어야 매트릭스가 의미 있음. dump 라벨 prefix 'dump#' 로 client 가 구분.
  const compareItems = useMemo(() => {
    const items = [];
    if (externalDump?.xml) {
      items.push({
        type: 'inline',
        xml: externalDump.xml,
        label: `dump#${externalDump.ts || 'live'}`,
        // client-only metadata: image source 결정용. 서버엔 보내지 않음.
        _pngDataUrl: externalDump.pngDataUrl || null,
        _displayLabel: externalDump.label || 'device dump',
      });
    }
    for (const id of pinnedForDir) {
      items.push({ type: 'snapshot', dir, id });
    }
    return items;
  }, [externalDump, pinnedForDir, dir]);

  const compare = async (items) => {
    if (!items || items.length < 2) {
      setCompareData(null);
      return;
    }
    setCompareError('');
    setCompareLoading(true);
    try {
      // 서버 전송용은 _ 시작 필드 제거
      const payload = items.map(({ _pngDataUrl, _displayLabel, ...rest }) => rest);
      const res = await axios.post('/api/run/compare-screen-ids', { items: payload });
      setCompareData(res.data);
    } catch (e) {
      setCompareError(e.response?.data?.error || e.message);
      setCompareData(null);
    } finally {
      setCompareLoading(false);
    }
  };
  useEffect(() => {
    if (compareItems.length >= 2) {
      compare(compareItems);
    } else {
      setCompareData(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(compareItems.map(i => i.type === 'inline' ? `inline:${i.label}` : `${i.dir}/${i.id}`))]);

  const runOptions = useMemo(() => runs.map(r => ({
    value: r.path,
    label: `${r.parent}/${r.name}${r.partial ? '  (partial)' : ''}`,
  })), [runs]);

  return (
    <div className="sid-inspector">
      <h2>🔍 Screen ID 검사</h2>
      <div style={{ color: '#7d8b97', fontSize: 12 }}>
        Run 폴더 → snapshot 을 선택하면 그 XML 한 장이 어떻게 screen_id 가
        만들어지고, 같은 run 의 app_memory.json 안 기존 화면들과 어떻게 매칭되는지
        step-by-step 으로 보여줍니다.
      </div>

      <div className="sid-toolbar two-col">
        <div>
          <label htmlFor="sid-run">Run 폴더</label>
          <select
            id="sid-run"
            value={dir}
            onChange={e => persistDir(e.target.value)}
            disabled={!runOptions.length}
          >
            {runOptions.length === 0 && <option value="">(스캔 결과 없음)</option>}
            {runOptions.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <div className="hint" title={dir}>
            {runs.length ? `${runs.length}개 발견` : ''}
            {dir ? ` · ${shortPath(dir)}` : ''}
          </div>
        </div>

        <div>
          <label htmlFor="sid-snap">Snapshot</label>
          <select
            id="sid-snap"
            value={snapshotId}
            onChange={e => persistSnap(e.target.value)}
            disabled={!snapshots.length}
          >
            {snapshots.length === 0 && <option value="">(run 선택 먼저)</option>}
            {snapshots.map(id => <option key={id} value={id}>{id}</option>)}
          </select>
          <div className="hint">{snapshots.length ? `${snapshots.length}개` : ''}</div>
        </div>

        <button className="secondary" onClick={() => loadRuns()} disabled={loading}
                title="run 목록 다시 스캔">
          🔄
        </button>
        <button onClick={inspect} disabled={loading || !snapshotId}>
          {loading ? '⏳' : '🔍 검사'}
        </button>
      </div>

      <div className="sid-advanced">
        <button
          className="sid-advanced-toggle"
          onClick={() => setShowAdvanced(v => !v)}
        >
          {showAdvanced ? '▾' : '▸'} 고급 — 스캔 루트 override
        </button>
        {showAdvanced && (
          <div className="sid-advanced-body">
            <div style={{ fontSize: 11, color: '#7d8b97', marginBottom: 6 }}>
              현재 자동 스캔 중인 루트:{' '}
              {scannedRoots.length === 0
                ? '(없음)'
                : scannedRoots.map((r, i) => (
                    <span key={i} style={{ fontFamily: 'monospace' }}>
                      {i > 0 && ', '}{r}
                    </span>
                  ))}
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'stretch' }}>
              <input
                value={root}
                onChange={e => persistRoot(e.target.value)}
                placeholder="비우면 outputs_APK/, outputs/ 자동 스캔"
                onKeyDown={e => { if (e.key === 'Enter') loadRuns(); }}
                style={{ flex: 1 }}
              />
              <button onClick={() => loadRuns()} disabled={loading}>적용</button>
              <button
                className="secondary"
                onClick={() => { persistRoot(''); loadRuns(''); }}
                disabled={loading}
                title="override 해제하고 디폴트로 복귀"
              >
                초기화
              </button>
            </div>
          </div>
        )}
      </div>

      {error && <div className="sid-error">⚠ {error}</div>}

      {externalDump && (
        <DumpPane
          dump={externalDump}
          data={dumpResult}
          loading={dumpLoading}
          error={dumpError}
          runs={runs}
          compareDir={dumpCompareDir}
          onChangeCompareDir={setDumpCompareDir}
          onClear={() => { setDumpResult(null); lastDumpTsRef.ts = 0; onClearExternalDump && onClearExternalDump(); }}
          threshold={threshold}
          setThreshold={setThreshold}
        />
      )}

      {!result && !error && (
        <div className="sid-empty">
          {runs.length === 0
            ? '스캔된 run 이 없습니다. 고급에서 루트를 지정해보세요.'
            : loading
              ? '⏳ 분석 중…'
              : '위에서 run 과 snapshot 을 선택하면 자동으로 검사합니다. dump 와 동시에 비교 패널에 들어갑니다.'}
        </div>
      )}

      {result && (
        <div className="sid-split">
          <ImagePane
            dir={dir}
            snapshotId={snapshotId}
            pinned={pinnedForDir.includes(snapshotId)}
            onTogglePin={() => togglePin(snapshotId)}
          />
          <div className="sid-trace">
            <Result data={result} threshold={threshold} setThreshold={setThreshold} />
          </div>
        </div>
      )}

      {(externalDump?.xml || pinnedForDir.length > 0) && (
        <ComparePanel
          dir={dir}
          pinned={pinnedForDir}
          dump={externalDump}
          data={compareData}
          loading={compareLoading}
          error={compareError}
          onRemove={togglePin}
          onClear={clearPins}
          onClearDump={() => onClearExternalDump && onClearExternalDump()}
        />
      )}
    </div>
  );
}

function DumpPane({
  dump, data, loading, error,
  runs, compareDir, onChangeCompareDir,
  onClear, threshold, setThreshold,
}) {
  const [errored, setErrored] = useState(false);
  // dump 객체에 meta 가 동봉돼 있으면 그걸 쓰고, 없으면 XML 본문에서 재추출.
  // 둘 다 동일 결과지만 AdbControlPanel 이 이미 파싱해 보낸 경우 1회 절약.
  const meta = useMemo(
    () => dump.meta || parseHierarchyMeta(dump.xml),
    [dump.meta, dump.xml]
  );

  return (
    <div className="sid-dump-wrap">
      <div className="sid-dump-banner">
        <div className="sid-dump-banner-main">
          <span className="sid-dump-pill">🔬 기기 dump 분석</span>
          <span className="sid-dump-label">{dump.label}</span>
          {dump.source && <span className="sid-dump-source">· {dump.source}</span>}
          {meta && (
            <div className="sid-dump-hierarchy">
              {meta.package  && <span><b>pkg</b> {meta.package}</span>}
              {meta.activity && <span title={meta.activity}><b>act</b> {shortActivity(meta.activity)}</span>}
              {meta.window_id != null && <span><b>wid</b> {meta.window_id}</span>}
              <span><b>rot</b> r{meta.rotation}</span>
            </div>
          )}
        </div>
        <button className="sid-dump-close" onClick={onClear} title="dump 모드 종료">
          ✕ 일반 모드로
        </button>
      </div>

      <div className="sid-split">
        <div className="sid-image-pane">
          <div className="pane-title">기기 화면 (dump 시점)</div>
          <div className="img-wrap">
            {dump.pngDataUrl && !errored
              ? <img src={dump.pngDataUrl} alt="device dump" onError={() => setErrored(true)} />
              : <div className="img-missing">PNG 없음 (XML 만 dump 됨)</div>}
          </div>
          <div className="img-meta">
            <span className="k">label</span><span className="v">{dump.label}</span>
            <span className="k">xml.len</span><span className="v">{dump.xml.length.toLocaleString()} chars</span>
            {dump.source && <><span className="k">source</span><span className="v">{dump.source}</span></>}
            {meta?.package  && <><span className="k">package</span><span className="v">{meta.package}</span></>}
            {meta?.activity && <><span className="k">activity</span><span className="v" title={meta.activity}>{shortActivity(meta.activity)}</span></>}
            {meta?.window_id != null && <><span className="k">window_id</span><span className="v">{meta.window_id}</span></>}
            {meta != null && <><span className="k">rotation</span><span className="v">r{meta.rotation}</span></>}
          </div>
        </div>

        <div className="sid-trace">
          <div className="sid-card">
            <div className="sid-card-title">매처 비교 대상 (선택)</div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <select
                value={compareDir}
                onChange={e => onChangeCompareDir(e.target.value)}
                style={{
                  flex: 1,
                  padding: '7px 10px',
                  background: '#0c141a',
                  color: '#d8dee4',
                  border: '1px solid #2c3a48',
                  borderRadius: 4,
                  minWidth: 250,
                }}
              >
                <option value="">(매처 비교 없이 fresh build 만)</option>
                {runs.map(r => (
                  <option key={r.path} value={r.path}>
                    {r.parent}/{r.name}{r.partial ? ' (partial)' : ''}
                  </option>
                ))}
              </select>
              <label style={{ fontSize: 11, color: '#7d8b97' }}>
                threshold{' '}
                <input
                  type="number" step="0.05" min="0" max="1"
                  value={threshold}
                  onChange={e => setThreshold(parseFloat(e.target.value) || 0)}
                  style={{
                    width: 70, padding: '4px 6px',
                    background: '#0c141a', color: '#d8dee4',
                    border: '1px solid #2c3a48', borderRadius: 4,
                  }}
                />
              </label>
            </div>
            <div style={{ marginTop: 6, fontSize: 11, color: '#7d8b97' }}>
              run 을 고르면 그 app_memory.json 의 기존 화면들과 Jaccard 매칭까지 보여줍니다.
            </div>
          </div>

          {loading && <div className="sid-empty">⏳ 분석 중…</div>}
          {error && <div className="sid-error">⚠ {error}</div>}
          {data && <Result data={data} threshold={threshold} setThreshold={setThreshold} />}
        </div>
      </div>
    </div>
  );
}

function ImagePane({ dir, snapshotId, pinned, onTogglePin }) {
  // /api/run/snapshot?dir=...&id=... 가 PNG 를 그대로 반환. 캐시 깨려고 ?t=
  const url = useMemo(() => {
    if (!dir || !snapshotId) return null;
    const qs = new URLSearchParams({ dir, id: snapshotId, t: String(Date.now()) });
    return `/api/run/snapshot?${qs.toString()}`;
  }, [dir, snapshotId]);

  const [errored, setErrored] = useState(false);
  useEffect(() => { setErrored(false); }, [url]);

  return (
    <div className="sid-image-pane">
      <div className="pane-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>화면 캡처</span>
        <button
          className={`sid-pin-btn ${pinned ? 'active' : ''}`}
          onClick={onTogglePin}
          title={pinned ? '비교에서 제거' : '비교에 스냅'}
        >
          {pinned ? '📌 핀 해제' : '📌 비교에 스냅'}
        </button>
      </div>
      <div className="img-wrap">
        {url && !errored ? (
          <img src={url} alt={snapshotId} onError={() => setErrored(true)} />
        ) : (
          <div className="img-missing">
            screen/{snapshotId}.png 없음
          </div>
        )}
      </div>
      <div className="img-meta">
        <span className="k">snapshot</span><span className="v">{snapshotId}</span>
        <span className="k">run</span><span className="v">{shortPath(dir)}</span>
      </div>
    </div>
  );
}

function ComparePanel({ dir, pinned, dump, data, loading, error, onRemove, onClear, onClearDump }) {
  // 핀 1개일 땐 안내만, 2개 이상이면 행렬+columns.
  const colors = (j) => {
    if (j == null) return '#1f2a35';
    if (j >= 0.85) return '#1e4a32';
    if (j >= 0.6)  return '#2c4a3a';
    if (j >= 0.3)  return '#4a3a2c';
    return '#4a2c2c';
  };

  return (
    <div className="sid-compare">
      <div className="sid-compare-header">
        <span className="title">
          📊 비교 ({(dump?.xml ? 1 : 0) + pinned.length}개{dump?.xml ? ' · dump 포함' : ''})
        </span>
        <button className="link" onClick={onClear}>핀 전체 해제</button>
      </div>

      {((dump?.xml ? 1 : 0) + pinned.length) < 2 && (
        <div className="sid-compare-hint">
          항목이 1개 — {dump?.xml
            ? '다른 snapshot 을 골라 📌 비교에 스냅 으로 추가하면 device dump 와 한 매트릭스에서 비교됩니다.'
            : '다른 snapshot 을 골라 📌 비교에 스냅 으로 추가하세요.'}
        </div>
      )}

      {loading && <div className="sid-compare-hint">⏳ 비교 계산 중…</div>}
      {error && <div className="sid-error">⚠ {error}</div>}

      {data && ((dump?.xml ? 1 : 0) + pinned.length) >= 2 && (
        <>
          {/* 페어와이즈 Jaccard 매트릭스 */}
          <div className="sid-compare-section">
            <div className="section-title">페어와이즈 tree_signature Jaccard</div>
            <table className="sid-matrix">
              <thead>
                <tr>
                  <th></th>
                  {data.snapshots.map((s, i) => {
                    const isDumpItem = typeof s.snapshot_id === 'string'
                      && s.snapshot_id.startsWith('dump#');
                    return (
                      <th key={i} title={s.screen_id}>
                        {isDumpItem ? '🔬 dump' : s.snapshot_id}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {data.pairwise_jaccard.map((row, i) => {
                  const sLabel = data.snapshots[i].snapshot_id;
                  const isDumpItem = typeof sLabel === 'string' && sLabel.startsWith('dump#');
                  return (
                  <tr key={i}>
                    <th>{isDumpItem ? '🔬 dump' : sLabel}</th>
                    {row.map((cell, j) => {
                      const j_val = cell.jaccard;
                      return (
                        <td
                          key={j}
                          style={{ background: colors(j_val) }}
                          title={`∩ ${cell.intersection} / ∪ ${cell.union}`}
                        >
                          {j_val.toFixed(3)}
                        </td>
                      );
                    })}
                  </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="sid-matrix-legend">
              <span style={{ background: '#1e4a32' }}>≥0.85</span>
              <span style={{ background: '#2c4a3a' }}>≥0.6 (매처 임계)</span>
              <span style={{ background: '#4a3a2c' }}>≥0.3</span>
              <span style={{ background: '#4a2c2c' }}>&lt;0.3</span>
              <span style={{ marginLeft: 'auto', color: '#7d8b97' }}>
                모든 항목 공통 sub-hash: <b>{data.common_sub_hashes}</b>개
              </span>
            </div>
          </div>

          {/* per-snapshot 컬럼 */}
          <div className="sid-compare-section">
            <div className="section-title">항목별 빌드 결과</div>
            <div className="sid-compare-columns">
              {data.snapshots.map((s, i) => {
                const isDumpItem = typeof s.snapshot_id === 'string'
                  && s.snapshot_id.startsWith('dump#');
                return (
                  <CompareColumn
                    key={i}
                    dir={dir}
                    snap={s}
                    isDumpItem={isDumpItem}
                    dumpPngDataUrl={isDumpItem ? dump?.pngDataUrl : null}
                    dumpDisplayLabel={isDumpItem ? (dump?.label || 'device dump') : null}
                    onRemove={() => {
                      if (isDumpItem) onClearDump && onClearDump();
                      else onRemove(s.snapshot_id);
                    }}
                  />
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function CompareColumn({ dir, snap, isDumpItem, dumpPngDataUrl, dumpDisplayLabel, onRemove }) {
  const url = useMemo(() => {
    if (isDumpItem) return dumpPngDataUrl || null;
    if (!dir || !snap?.snapshot_id) return null;
    const qs = new URLSearchParams({ dir, id: snap.snapshot_id, t: String(Date.now()) });
    return `/api/run/snapshot?${qs.toString()}`;
  }, [isDumpItem, dumpPngDataUrl, dir, snap?.snapshot_id]);
  const [errored, setErrored] = useState(false);

  if (snap.error) {
    return (
      <div className="sid-compare-col error">
        <div className="col-head">
          <b>{isDumpItem ? '🔬 dump' : snap.snapshot_id}</b>
          <button onClick={onRemove} title="비교에서 제거">✕</button>
        </div>
        <div style={{ color: '#f0a0a0' }}>⚠ {snap.error}</div>
      </div>
    );
  }

  return (
    <div className={`sid-compare-col ${isDumpItem ? 'is-dump' : ''}`}>
      <div className="col-head">
        <b title={isDumpItem ? dumpDisplayLabel : snap.snapshot_id}>
          {isDumpItem ? '🔬 dump' : snap.snapshot_id}
        </b>
        <button onClick={onRemove} title={isDumpItem ? 'dump 제거' : '비교에서 제거'}>✕</button>
      </div>
      <div className="col-img">
        {url && !errored
          ? <img src={url} alt={snap.snapshot_id} onError={() => setErrored(true)} />
          : <div className="img-missing">no image</div>}
      </div>
      <div className="col-id" title={snap.screen_id}>
        {snap.screen_id}
      </div>
      <div className="col-meta">
        <div><span className="k">activity</span><span className="v">{shortAct(snap.meta?.activity)}</span></div>
        <div><span className="k">wid</span><span className="v">{snap.meta?.window_id ?? '-'}</span></div>
        <div><span className="k">rotation</span><span className="v">r{(snap.meta?.rotation ?? 0) % 4}</span></div>
        <div><span className="k">sig.total</span><span className="v">{snap.tree_signature?.total}</span></div>
        <div><span className="k">sig.unique</span><span className="v">{snap.tree_signature?.unique}</span></div>
      </div>
    </div>
  );
}

function Result({ data, threshold, setThreshold }) {
  const meta = data.meta || {};
  const sig = data.tree_signature || {};
  const idb = data.id_build || {};
  const els = data.elements || {};
  const cls = data.existing_classification;
  const match = data.match || {};

  const freshId = idb.screen_id;
  const currentId = cls?.screen_id || null;
  const mismatch = freshId && currentId && freshId !== currentId;

  return (
    <>
      {/* (A) ID 헤더 */}
      <div className="sid-card">
        <div className="sid-card-title">결과 요약</div>
        <div className="sid-id-banner">
          <div className="id-block">
            <span className="id-label">이 XML 의 빌드 screen_id</span>
            <span className="id-value fresh">{freshId || '(빌드 실패)'}</span>
            <span style={{ fontSize: 11, color: '#7d8b97' }}>
              builder: {idb.builder || '-'}{idb.fallback ? ' · fallback' : ''}
            </span>
          </div>
          {cls && (
            <div className="id-block">
              <span className="id-label">현재 app_memory 분류</span>
              <span className="id-value current">{currentId || '(미등록)'}</span>
              {currentId && (
                <span style={{ fontSize: 11, color: '#7d8b97' }}>
                  같은 screen 내 {cls.total_snapshots_in_screen}개 snapshot, 대표 xml:{' '}
                  <span style={{ fontFamily: 'monospace' }}>{cls.representative_xml}</span>
                </span>
              )}
              {mismatch && (
                <span className="id-mismatch">
                  ⚠ 빌드 ID 와 현재 분류 ID 가 다름 — run 도중 게이트/매처가
                  representative 와 비교한 결과가 합쳐졌거나, 같은 화면이 viewport
                  변화로 fresh 빌드와 어긋났을 가능성.
                </span>
              )}
              {!mismatch && currentId && (
                <span className="id-match">✓ 빌드 ID 와 현재 분류 일치</span>
              )}
            </div>
          )}
          <div>
            <label style={{ fontSize: 11, color: '#7d8b97', display: 'block' }}>
              match_threshold
            </label>
            <input
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={threshold}
              onChange={e => setThreshold(parseFloat(e.target.value) || 0)}
              style={{
                width: 80,
                padding: '5px 8px',
                background: '#0c141a',
                color: '#d8dee4',
                border: '1px solid #2c3a48',
                borderRadius: 4,
              }}
            />
          </div>
        </div>
      </div>

      {/* (B) hierarchy 메타 */}
      <div className="sid-card">
        <div className="sid-card-title">XML hierarchy 메타</div>
        <div className="sid-meta-grid">
          <div><span className="k">package</span><span className="v">{meta.package || '-'}</span></div>
          <div><span className="k">activity</span><span className="v">{meta.activity || '-'}</span></div>
          <div><span className="k">window_id</span><span className="v">{meta.window_id ?? '-'}</span></div>
          <div><span className="k">rotation</span><span className="v">r{(meta.rotation ?? 0) % 4}</span></div>
        </div>
      </div>

      {/* (C) screen_id 빌드 과정 */}
      <div className="sid-card">
        <div className="sid-card-title">screen_id 빌드 과정 (LayoutTree)</div>
        <div className="sid-build-steps">
          <BuildStep n={1} label="visible 노드">
            <code>compute_tree_signature(root)</code> 로 각 visible{' '}
            <code>&lt;node&gt;</code> 의 subtree 를{' '}
            <code>{'class[d:desc](sorted_child_hashes)'}</code> 형태로 sha1 →{' '}
            sorted multiset.
            <br />
            <span style={{ color: '#98a4af' }}>
              total = <b>{sig.total}</b> · unique = <b>{sig.unique}</b>
            </span>
          </BuildStep>

          <BuildStep n={2} label="preview (앞 20개)">
            <div className="sid-sig-preview">
              {(sig.preview || []).map((h, i) => (
                <span key={i} className="sid-sig-chip">{h}</span>
              ))}
            </div>
          </BuildStep>

          <BuildStep n={3} label="raw 직렬화">
            {idb.fallback
              ? <span style={{ color: '#ffb547' }}>{idb.note}</span>
              : (
                <>
                  <code>{`"r${(idb.rotation_prefix || '').slice(1)}|" + "|".join(tree_signature)`}</code>
                  <div style={{ marginTop: 6, color: '#98a4af', fontSize: 11 }}>
                    raw 길이 = {idb.raw_length} chars
                  </div>
                  <div style={{ marginTop: 6 }}>{idb.raw_preview}</div>
                </>
              )
            }
          </BuildStep>

          {!idb.fallback && (
            <>
              <BuildStep n={4} label="sha256 (full)">
                <span style={{ color: '#98a4af' }}>{idb.sha256_full}</span>
              </BuildStep>
              <BuildStep n={5} label="screen_id (앞 16)">
                <span className="step-value highlight">{idb.screen_id}</span>
              </BuildStep>
            </>
          )}
        </div>
      </div>

      {/* (D) 매처 trace */}
      <div className="sid-card">
        <div className="sid-card-title">매처 시뮬레이션 (현재 app_memory 기준)</div>
        {!match.enabled
          ? <div style={{ color: '#ffb547' }}>{match.reason || 'app_memory 정보 없음'}</div>
          : (
            <>
              <div style={{ marginBottom: 8, fontSize: 12, color: '#98a4af' }}>
                <b>버킷:</b> <span style={{ fontFamily: 'monospace' }}>{match.bucket}</span>
                {' · '}<b>임계:</b> {match.threshold}
                {' · '}<b>총 등록 화면:</b> {match.total_existing_screens}
              </div>
              <table className="sid-table">
                <thead>
                  <tr>
                    <th>screen_id</th>
                    <th>activity</th>
                    <th>wid</th>
                    <th>r</th>
                    <th>snaps</th>
                    <th>버킷</th>
                    <th>Jaccard</th>
                    <th>∩</th>
                    <th>∪</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {(match.candidates || []).map((c, i) => {
                    const isBest = match.decision?.matched
                      && c.screen_id === match.decision.screen_id;
                    return (
                      <tr
                        key={i}
                        className={`${c.in_bucket ? '' : 'out-of-bucket'} ${isBest ? 'is-match' : ''}`}
                      >
                        <td className="mono">{c.screen_id}</td>
                        <td>{shortAct(c.activity)}</td>
                        <td className="mono">{c.window_id ?? '-'}</td>
                        <td>r{(c.rotation ?? 0) % 4}</td>
                        <td>{c.snapshot_count ?? 0}</td>
                        <td>{c.in_bucket ? '✓' : '—'}</td>
                        <td className="jaccard-cell">
                          {c.jaccard != null ? c.jaccard.toFixed(3) : '-'}
                        </td>
                        <td className="mono">{c.intersection ?? '-'}</td>
                        <td className="mono">{c.union ?? '-'}</td>
                        <td>
                          {c.skip_reason
                            ? <span style={{ fontSize: 11, color: '#6b7785' }}>{c.skip_reason}</span>
                            : c.passes_threshold
                              ? <span className="pass-badge">≥ thr</span>
                              : <span className="fail-badge">&lt; thr</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              {match.decision && (
                <div className={`sid-decision ${match.decision.matched ? 'matched' : 'not-matched'}`}>
                  {match.decision.matched ? (
                    <>
                      <b>✓ 매칭</b> · screen_id ={' '}
                      <span style={{ fontFamily: 'monospace' }}>{match.decision.screen_id}</span>
                      {' · '}J = <b>{match.decision.jaccard.toFixed(3)}</b>
                      {' '}(∩ {match.decision.intersection} / ∪ {match.decision.union})
                      <div style={{ marginTop: 4, fontSize: 12, color: '#98a4af' }}>
                        {match.decision.note}
                      </div>
                    </>
                  ) : (
                    <>
                      <b>✗ 매칭 실패</b>
                      {match.decision.best_jaccard != null && (
                        <> · 최선 후보 J = <b>{match.decision.best_jaccard.toFixed(3)}</b>{' '}
                          {'<'} {match.decision.threshold}</>
                      )}
                      <div style={{ marginTop: 4, fontSize: 12, color: '#98a4af' }}>
                        {match.decision.note}
                      </div>
                    </>
                  )}
                </div>
              )}
            </>
          )
        }
      </div>

      {/* (E) parsed elements */}
      <div className="sid-card">
        <div className="sid-card-title">
          파싱된 element ({els.count ?? 0}개 · 앞 50개 표시)
        </div>
        <table className="sid-table">
          <thead>
            <tr>
              <th>class</th>
              <th>resource-id</th>
              <th>text</th>
              <th>desc</th>
              <th>bbox</th>
              <th>flags</th>
            </tr>
          </thead>
          <tbody>
            {(els.preview || []).map((e, i) => (
              <tr key={i}>
                <td className="mono">{e.cls}</td>
                <td className="mono">{shortRid(e.resource_id)}</td>
                <td>{e.text}</td>
                <td>{e.description}</td>
                <td className="mono">[{e.bbox.join(',')}]</td>
                <td>
                  {e.is_scrollable && <span title="scrollable">↕</span>}
                  {!e.is_visible_to_user && <span title="hidden" style={{ color: '#6b7785' }}>👁‍🗨</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function BuildStep({ n, label, children }) {
  return (
    <div className="sid-build-step">
      <div className="step-num">{n}</div>
      <div className="step-label">{label}</div>
      <div className="step-value">{children}</div>
    </div>
  );
}

function shortAct(a) {
  if (!a) return '-';
  return a.length > 40 ? '…' + a.slice(-37) : a;
}

function shortRid(r) {
  if (!r) return '';
  return r.includes(':id/') ? r.split(':id/').pop() : r;
}

function shortPath(p) {
  if (!p) return '';
  // 마지막 두 단계만 표시: ".../Xiaomi/20260603_125329"
  const parts = p.split(/[\\/]/).filter(Boolean);
  if (parts.length <= 2) return p;
  return '…/' + parts.slice(-2).join('/');
}
