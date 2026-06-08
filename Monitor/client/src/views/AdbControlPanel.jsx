import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import axios from 'axios';
import { parseHierarchyMeta, shortActivity } from '../utils/xmlMeta.js';
import './adb-control.css';

function makeId() {
  return 'btn_' + Math.random().toString(36).slice(2, 8);
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

export default function AdbControlPanel({ onSendToInspector } = {}) {
  const [devices, setDevices] = useState([]);
  const [serial, setSerial] = useState('');
  const [buttons, setButtons] = useState([]);
  const [output, setOutput] = useState([]); // {cmd, code, stdout, stderr, elapsed_ms, ts}
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [manual, setManual] = useState('');
  const [saveMsg, setSaveMsg] = useState('');

  // ── 추출(캡처/덤프) 상태 ─────────────────────────────────
  // png 는 blob URL 로 보관 — img.src 와 저장용 dataURL 만들 때 둘 다 쓰임.
  // xml 은 text 그대로. extractMsg 는 마지막 동작 결과/에러.
  const [pngUrl, setPngUrl] = useState(null);
  const [pngBlob, setPngBlob] = useState(null);
  const [xmlText, setXmlText] = useState('');
  const [xmlMeta, setXmlMeta] = useState(null); // {xmlPath, screenW, screenH}
  const [extractBusy, setExtractBusy] = useState(false);
  const [extractMsg, setExtractMsg] = useState('');
  const pngUrlRef = useRef(null);

  // blob URL leak 방지: 새로 받으면 이전 것 revoke.
  const setPng = (blob) => {
    if (pngUrlRef.current) URL.revokeObjectURL(pngUrlRef.current);
    if (!blob) {
      pngUrlRef.current = null;
      setPngBlob(null);
      setPngUrl(null);
      return;
    }
    const url = URL.createObjectURL(blob);
    pngUrlRef.current = url;
    setPngBlob(blob);
    setPngUrl(url);
  };
  useEffect(() => () => {
    if (pngUrlRef.current) URL.revokeObjectURL(pngUrlRef.current);
  }, []);

  const loadDevices = useCallback(async () => {
    try {
      const res = await axios.get('/api/adb/devices');
      const list = res.data.devices || [];
      setDevices(list);
      setSerial(prev => (prev && list.some(d => d.serial === prev)) ? prev : (list[0]?.serial || ''));
    } catch (e) {
      pushOutput({ cmd: 'adb devices', code: -1, stdout: '', stderr: e.message, elapsed_ms: 0 });
    }
  }, []);

  const loadButtons = useCallback(async () => {
    try {
      const res = await axios.get('/api/adb/buttons');
      setButtons(res.data.buttons || []);
    } catch (e) {
      setSaveMsg('버튼 설정 로드 실패: ' + e.message);
    }
  }, []);

  useEffect(() => {
    loadDevices();
    loadButtons();
  }, [loadDevices, loadButtons]);

  function pushOutput(entry) {
    setOutput(prev => [{ ...entry, ts: Date.now() }, ...prev].slice(0, 50));
  }

  const run = useCallback(async (args) => {
    const parsed = Array.isArray(args) ? args : String(args).trim().split(/\s+/).filter(Boolean);
    if (parsed.length === 0) return;
    setBusy(true);
    try {
      const res = await axios.post('/api/adb/run', { args: parsed, serial: serial || undefined });
      pushOutput(res.data);
    } catch (e) {
      pushOutput({
        cmd: 'adb ' + parsed.join(' '),
        code: -1,
        stdout: '',
        stderr: e.response?.data?.error || e.message,
        elapsed_ms: 0,
      });
    } finally {
      setBusy(false);
    }
  }, [serial]);

  // ── 추출 액션 ────────────────────────────────────────────────
  const captureScreen = useCallback(async () => {
    setExtractBusy(true);
    setExtractMsg('📸 캡처 중…');
    try {
      const res = await axios.get(`/api/adb/screen?t=${Date.now()}${serial ? `&serial=${serial}` : ''}`,
        { responseType: 'blob' });
      setPng(res.data);
      setExtractMsg(`📸 캡처 OK · ${(res.data.size / 1024).toFixed(1)} KB`);
    } catch (e) {
      setExtractMsg('캡처 실패: ' + (e.response?.data?.error || e.message));
    } finally {
      setExtractBusy(false);
    }
  }, [serial]);

  const dumpXml = useCallback(async () => {
    setExtractBusy(true);
    setExtractMsg('📄 XML 덤프 중…');
    // 1차: listener 기반 (빠름) — 켜져 있어야 동작.
    // 2차: uiautomator dump 폴백 — listener 없이도 됨.
    try {
      let res;
      try {
        res = await axios.post('/api/adb/dump', { serial: serial || undefined });
      } catch (e) {
        // listener 가 죽었거나 timeout → 폴백.
        const isTimeout = /DUMP_WRITTEN|listener|trigger/.test(e.response?.data?.error || '');
        if (!isTimeout) throw e;
        setExtractMsg('listener 미동작 — uiautomator dump 폴백');
        res = await axios.post('/api/adb/uia-dump', { serial: serial || undefined });
      }
      const { xml, xmlPath, screenW, screenH } = res.data;
      setXmlText(xml || '');
      setXmlMeta({ xmlPath, screenW, screenH });
      setExtractMsg(`📄 XML OK · ${xml.length.toLocaleString()} chars · ${screenW}×${screenH}`);
    } catch (e) {
      setExtractMsg('XML 덤프 실패: ' + (e.response?.data?.error || e.message));
    } finally {
      setExtractBusy(false);
    }
  }, [serial]);

  const captureAndDump = useCallback(async () => {
    await captureScreen();
    await dumpXml();
  }, [captureScreen, dumpXml]);

  const saveSnapshot = useCallback(async () => {
    if (!pngBlob || !xmlText) {
      setExtractMsg('PNG + XML 둘 다 있어야 저장됩니다.');
      return;
    }
    setExtractBusy(true);
    setExtractMsg('💾 저장 중…');
    try {
      const dataUrl = await blobToDataUrl(pngBlob);
      const res = await axios.post('/api/adb/snapshot', {
        xml: xmlText,
        png_base64: dataUrl,
      });
      const d = res.data;
      setExtractMsg(`💾 저장 OK · ${d.dir} · ${(d.pngBytes / 1024).toFixed(1)}KB / ${d.xmlBytes}B`);
    } catch (e) {
      setExtractMsg('저장 실패: ' + (e.response?.data?.error || e.message));
    } finally {
      setExtractBusy(false);
    }
  }, [pngBlob, xmlText]);

  const clearExtract = () => {
    setPng(null);
    setXmlText('');
    setXmlMeta(null);
    setExtractMsg('');
  };

  // XML 본문에서 <hierarchy> 루트 속성을 즉시 추출 (서버 inspect 안 거치고).
  // dump 와 동시에 분석 — package/activity/window-id/rotation 을 추출 패널과
  // Inspector dump 배너에서 같이 보여주기 위함.
  const hierarchyMeta = useMemo(() => parseHierarchyMeta(xmlText), [xmlText]);

  // 현재 추출 결과를 Screen ID 검사 탭으로 push. XML 만 필수 — PNG 는 있으면
  // dataURL 로 같이 보내 Inspector 좌측 이미지 패널에 표시.
  const inspectExtract = useCallback(async () => {
    if (!xmlText) {
      setExtractMsg('XML 이 없습니다. 먼저 📄 XML 덤프 를 눌러주세요.');
      return;
    }
    let pngDataUrl = null;
    if (pngBlob) {
      try { pngDataUrl = await blobToDataUrl(pngBlob); } catch (_) { /* noop */ }
    }
    const ts = new Date();
    const label = `device dump · ${ts.toLocaleTimeString()}`;
    if (onSendToInspector) {
      onSendToInspector({
        xml: xmlText,
        pngDataUrl,
        label,
        source: serial || 'device',
        meta: hierarchyMeta,
      });
    }
  }, [xmlText, pngBlob, serial, hierarchyMeta, onSendToInspector]);

  // ── 버튼 편집 ────────────────────────────────────────────────
  function updateBtn(id, patch) {
    setButtons(prev => prev.map(b => (b.id === id ? { ...b, ...patch } : b)));
  }
  function addBtn() {
    setButtons(prev => [...prev, { id: makeId(), label: '새 버튼', args: ['shell', 'input', 'keyevent', 'KEYCODE_HOME'] }]);
  }
  function removeBtn(id) {
    setButtons(prev => prev.filter(b => b.id !== id));
  }
  async function saveButtons() {
    setSaveMsg('저장 중…');
    try {
      const clean = buttons
        .map(b => ({
          id: b.id || makeId(),
          label: (b.label || '').trim() || '(이름없음)',
          args: Array.isArray(b.args) ? b.args : String(b.args).trim().split(/\s+/).filter(Boolean),
        }))
        .filter(b => b.args.length > 0);
      const res = await axios.post('/api/adb/buttons', { buttons: clean });
      setSaveMsg(`저장됨 (${res.data.count}개)`);
      setButtons(clean);
    } catch (e) {
      setSaveMsg('저장 실패: ' + (e.response?.data?.error || e.message));
    }
  }

  return (
    <div className="adb-panel">
      <div className="adb-toolbar">
        <span className="adb-title">🎮 기기 제어 (adb)</span>
        <label className="adb-device">
          기기:
          <select value={serial} onChange={e => setSerial(e.target.value)}>
            {devices.length === 0 && <option value="">(연결된 기기 없음)</option>}
            {devices.map(d => (
              <option key={d.serial} value={d.serial}>
                {d.model || d.serial} · {d.serial} {d.state !== 'device' ? `[${d.state}]` : ''}
              </option>
            ))}
          </select>
        </label>
        <button className="adb-btn-mini" onClick={loadDevices} title="기기 목록 새로고침">🔄</button>
        <div className="adb-spacer" />
        <button
          className={`adb-btn-mini ${editing ? 'active' : ''}`}
          onClick={() => { setEditing(v => !v); setSaveMsg(''); }}
        >
          {editing ? '✓ 편집 완료' : '✎ 버튼 편집'}
        </button>
      </div>

      {!editing && (
        <div className="adb-grid">
          {buttons.map(b => (
            <button
              key={b.id}
              className="adb-cmd-btn"
              disabled={busy}
              title={'adb ' + (Array.isArray(b.args) ? b.args.join(' ') : b.args)}
              onClick={() => run(b.args)}
            >
              {b.label}
            </button>
          ))}
          {buttons.length === 0 && <div className="adb-empty">버튼이 없습니다. ‘버튼 편집’에서 추가하세요.</div>}
        </div>
      )}

      {editing && (
        <div className="adb-editor">
          {buttons.map(b => (
            <div key={b.id} className="adb-edit-row">
              <input
                className="adb-edit-label"
                value={b.label}
                placeholder="라벨"
                onChange={e => updateBtn(b.id, { label: e.target.value })}
              />
              <span className="adb-prefix">adb</span>
              <input
                className="adb-edit-args"
                value={Array.isArray(b.args) ? b.args.join(' ') : b.args}
                placeholder="shell input keyevent KEYCODE_HOME"
                onChange={e => updateBtn(b.id, { args: e.target.value.split(/\s+/).filter(Boolean) })}
              />
              <button className="adb-btn-mini danger" onClick={() => removeBtn(b.id)}>✕</button>
            </div>
          ))}
          <div className="adb-edit-actions">
            <button className="adb-btn-mini" onClick={addBtn}>+ 버튼 추가</button>
            <button className="adb-btn-save" onClick={saveButtons}>💾 설정 저장</button>
            {saveMsg && <span className="adb-save-msg">{saveMsg}</span>}
          </div>
          <p className="adb-hint">
            인자는 공백으로 구분됩니다 (따옴표 미지원). 예: <code>shell am start -n pkg/.Activity</code>
          </p>
        </div>
      )}

      <div className="adb-manual">
        <span className="adb-prefix">adb</span>
        <input
          value={manual}
          placeholder="직접 입력: shell input tap 500 1000"
          onKeyDown={e => { if (e.key === 'Enter') { run(manual); } }}
          onChange={e => setManual(e.target.value)}
        />
        <button className="adb-btn-run" disabled={busy || !manual.trim()} onClick={() => run(manual)}>실행</button>
      </div>

      <div className="adb-extract">
        <div className="adb-extract-head">
          <span className="adb-extract-title">📦 화면 추출</span>
          <div className="adb-extract-actions">
            <button onClick={captureScreen} disabled={extractBusy || !serial}>📸 화면 캡처</button>
            <button onClick={dumpXml} disabled={extractBusy || !serial}>📄 XML 덤프</button>
            <button onClick={captureAndDump} disabled={extractBusy || !serial}>🔍 둘 다</button>
            <button
              className="adb-btn-save"
              onClick={saveSnapshot}
              disabled={extractBusy || !pngBlob || !xmlText}
              title="PNG + XML 한 쌍으로 디스크에 저장"
            >
              💾 저장
            </button>
            <button
              className="adb-btn-inspect"
              onClick={inspectExtract}
              disabled={extractBusy || !xmlText}
              title="이 XML 을 Screen ID 검사 탭으로 보내 분석"
            >
              🔍 Screen ID 검사
            </button>
            <button onClick={clearExtract} disabled={extractBusy}>🗑 비우기</button>
          </div>
        </div>
        {extractMsg && <div className="adb-extract-msg">{extractMsg}</div>}

        {(pngUrl || xmlText) && (
          <div className="adb-extract-body">
            <div className="adb-extract-pane">
              <div className="pane-title">📸 PNG</div>
              {pngUrl ? (
                <img src={pngUrl} alt="screenshot" />
              ) : (
                <div className="pane-empty">없음 — “📸 화면 캡처” 를 눌러주세요</div>
              )}
            </div>
            <div className="adb-extract-pane">
              <div className="pane-title">
                📄 XML
                {xmlMeta && (
                  <span className="pane-meta">
                    · {xmlMeta.xmlPath} · {xmlMeta.screenW}×{xmlMeta.screenH}
                  </span>
                )}
              </div>
              {hierarchyMeta && (
                <div className="adb-xml-hierarchy">
                  <div><span className="k">package</span><span className="v">{hierarchyMeta.package || '-'}</span></div>
                  <div><span className="k">activity</span><span className="v" title={hierarchyMeta.activity || ''}>{shortActivity(hierarchyMeta.activity)}</span></div>
                  <div><span className="k">wid</span><span className="v">{hierarchyMeta.window_id ?? '-'}</span></div>
                  <div><span className="k">rotation</span><span className="v">r{hierarchyMeta.rotation}</span></div>
                </div>
              )}
              {xmlText ? (
                <textarea className="adb-xml-text" value={xmlText} readOnly />
              ) : (
                <div className="pane-empty">없음 — “📄 XML 덤프” 를 눌러주세요</div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="adb-output">
        <div className="adb-output-head">
          <span>출력</span>
          <button className="adb-btn-mini" onClick={() => setOutput([])}>지우기</button>
        </div>
        <div className="adb-output-body">
          {output.length === 0 && <div className="adb-empty">명령을 실행하면 결과가 여기에 표시됩니다.</div>}
          {output.map((o, i) => (
            <div key={o.ts + '_' + i} className={`adb-out-entry ${o.code === 0 ? 'ok' : 'err'}`}>
              <div className="adb-out-cmd">
                <span className={`adb-code ${o.code === 0 ? 'ok' : 'err'}`}>{o.code}</span>
                <code>{o.cmd}</code>
                <span className="adb-elapsed">{o.elapsed_ms}ms</span>
              </div>
              {o.stdout && <pre className="adb-out-text">{o.stdout}</pre>}
              {o.stderr && <pre className="adb-out-text err">{o.stderr}</pre>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
