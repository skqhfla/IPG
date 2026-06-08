const express = require('express');
const cors = require('cors');
const fs = require('fs');
const path = require('path');
const { execFile, spawn } = require('child_process');

const app = express();
const PORT = 3001;

app.use(cors());
// 스냅샷 저장에서 PNG 를 base64 로 보내므로 기본 100kb 한도로는 부족하다.
app.use(express.json({ limit: '32mb' }));

// adb 실행 파일 (PATH 또는 ADB_BIN 환경변수). 명령은 항상 execFile(배열 인자)로
// 실행해 shell 인젝션을 차단한다. 바이너리는 adb 로 고정 — 임의 실행파일 불가.
const ADB_BIN = process.env.ADB_BIN || 'adb';
const BUTTONS_FILE = path.join(__dirname, 'adb_buttons.json');
const DEFAULT_BUTTONS = [
  { id: 'home',   label: '🏠 홈',    args: ['shell', 'input', 'keyevent', 'KEYCODE_HOME'] },
  { id: 'back',   label: '◀ 뒤로',   args: ['shell', 'input', 'keyevent', 'KEYCODE_BACK'] },
  { id: 'recent', label: '▢ 최근앱', args: ['shell', 'input', 'keyevent', 'KEYCODE_APP_SWITCH'] },
  { id: 'wake',   label: '☀ 깨우기', args: ['shell', 'input', 'keyevent', 'KEYCODE_WAKEUP'] },
  { id: 'enter',  label: '⏎ Enter',  args: ['shell', 'input', 'keyevent', 'KEYCODE_ENTER'] },
];

function parseAdbArgs(input) {
  if (Array.isArray(input)) return input.map(String).filter(s => s.length > 0);
  if (typeof input === 'string') return input.trim().split(/\s+/).filter(Boolean);
  return [];
}

function adbArgs(serial, args) {
  return serial ? ['-s', String(serial), ...args] : args;
}

// device_listener instrumentation 상수 (a11y_event_listener.py와 동일)
const LISTENER_PKG = 'dev.ipg.listener';
const TEST_PKG = 'dev.ipg.listener.test';        // instrumentation 테스트가 실제로 도는 프로세스
const TEST_RUNNER = 'dev.ipg.listener.test/androidx.test.runner.AndroidJUnitRunner';
const TEST_CLASS = 'dev.ipg.listener.IpgInstrumentationTest#run';
const TRIGGER_FILE = '/storage/emulated/0/Android/data/dev.ipg.listener/files/dump_now.trigger';

// 좀비 instrumentation(host adb 자식만 죽고 디바이스 테스트는 살아남은 상태) 청소.
// am force-stop은 반드시 TEST_PKG(테스트 프로세스)에 걸어야 함. LISTENER_PKG(앱 본체)
// 만 죽이면 테스트의 UiAutomation 리스너는 살아 이벤트는 나오지만 trigger 폴링 루프가
// 끊겨 dump 가 안 됨.
function cleanupListener(serial, cb) {
  execFile(ADB_BIN, adbArgs(serial, ['shell', 'am', 'force-stop', TEST_PKG]),
    { timeout: 5000 }, () => {
      execFile(ADB_BIN, adbArgs(serial, ['shell', 'am', 'force-stop', LISTENER_PKG]),
        { timeout: 5000 }, () => cb && cb());
    });
}

// 디바이스에서 테스트 프로세스가 살아있는지 확인 (서버 in-memory state 보조).
function probeListenerAlive(serial, cb) {
  execFile(ADB_BIN, adbArgs(serial, ['shell', 'pidof', TEST_PKG]),
    { timeout: 5000 }, (e, out = '') => cb(!!(out && out.trim())));
}

// Monitor가 직접 관리하는 instrumentation 프로세스 (단일 소유 — Python observe와
// 동시 실행 금지: UiAutomation은 하나만 등록 가능).
let listenerProc = null;
let listenerSerial = null;

// netstats 파싱 (netstats.py _parse_uid_total 포팅)
function parseUidTotal(output, uid) {
  let txP = 0, rxP = 0, txB = 0, rxB = 0, inBlock = false;
  for (const line of output.split('\n')) {
    const mu = line.match(/\buid=(-?\d+)\b/);
    if (mu) {
      inBlock = parseInt(mu[1], 10) === uid && /\btag=0x0\b/.test(line);
      continue;
    }
    if (!inBlock) continue;
    const m = line.match(/\brb=(\d+)\s+rp=(\d+)\s+tb=(\d+)\s+tp=(\d+)\b/);
    if (m) { rxB += +m[1]; rxP += +m[2]; txB += +m[3]; txP += +m[4]; }
  }
  return { tx_packets: txP, rx_packets: rxP, tx_bytes: txB, rx_bytes: rxB };
}

function resolveUid(serial, pkg, cb) {
  execFile(ADB_BIN, adbArgs(serial, ['shell', 'pm', 'list', 'packages', '-U', pkg]),
    { timeout: 10000 }, (e, out = '') => {
      let uid = null;
      for (const l of (out || '').split('\n')) {
        if (l.includes('package:' + pkg + ' ') || l.includes('package:' + pkg + '\r') || l.trim() === 'package:' + pkg) {
          const m = l.match(/\buid:(\d+)\b/);
          if (m) { uid = parseInt(m[1], 10); break; }
        }
      }
      cb(uid);
    });
}

// ─── 디렉토리 내용 조회 ─────────────────────────────────────────
app.get('/api/browse', (req, res) => {
  const dirPath = req.query.path;
  if (!dirPath) return res.status(400).json({ error: 'path 파라미터가 필요합니다' });

  try {
    const stat = fs.statSync(dirPath);
    if (!stat.isDirectory()) {
      return res.status(400).json({ error: '디렉토리가 아닙니다' });
    }

    const items = fs.readdirSync(dirPath, { withFileTypes: true });
    const result = items
      .filter(item => !item.name.startsWith('.'))
      .map(item => ({
        name: item.name,
        isDirectory: item.isDirectory(),
        path: path.join(dirPath, item.name),
        ext: item.isDirectory() ? null : path.extname(item.name).toLowerCase(),
      }))
      .sort((a, b) => {
        if (a.isDirectory && !b.isDirectory) return -1;
        if (!a.isDirectory && b.isDirectory) return 1;
        return a.name.localeCompare(b.name);
      });

    res.json({ items: result, path: dirPath });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── JSON 파일 읽기 ─────────────────────────────────────────────
app.get('/api/read-json', (req, res) => {
  const filePath = req.query.path;
  if (!filePath) return res.status(400).json({ error: 'path 파라미터가 필요합니다' });

  try {
    const content = fs.readFileSync(filePath, 'utf8');
    const json = JSON.parse(content);
    res.json(json);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── 스냅샷 이미지 제공 ─────────────────────────────────────────
// jsonPath와 snapshotId를 기반으로 이미지를 자동 탐색합니다.
app.get('/api/snapshot', (req, res) => {
  const { jsonPath, id } = req.query;
  if (!jsonPath || !id) {
    return res.status(400).json({ error: 'jsonPath, id 파라미터가 필요합니다' });
  }

  const baseDir = path.dirname(jsonPath);
  const extensions = ['.png', '.jpg', '.jpeg', '.webp', '.bmp'];

  // 탐색할 디렉토리 목록 (우선순위 순)
  const searchDirs = [
    path.join(baseDir, 'snapshots'),
    path.join(baseDir, 'screenshots'),
    path.join(baseDir, 'images'),
    path.join(baseDir, 'screen'),
    baseDir,
    path.join(path.dirname(baseDir), 'snapshots'),
    path.join(path.dirname(baseDir), 'images'),
  ];

  for (const dir of searchDirs) {
    for (const ext of extensions) {
      const imgPath = path.join(dir, id + ext);
      if (fs.existsSync(imgPath)) {
        return res.sendFile(imgPath);
      }
    }
    // 하위 디렉토리가 있는 경우 (예: snapshots/000001/screen.png)
    for (const ext of extensions) {
      const imgPath = path.join(dir, id, 'screen' + ext);
      if (fs.existsSync(imgPath)) {
        return res.sendFile(imgPath);
      }
    }
  }

  res.status(404).json({ error: `스냅샷 이미지를 찾을 수 없습니다: ${id}` });
});

// ─── 임의 이미지 제공 (절대 경로) ───────────────────────────────
app.get('/api/image', (req, res) => {
  const filePath = req.query.path;
  if (!filePath) return res.status(400).json({ error: 'path 파라미터가 필요합니다' });

  try {
    if (!fs.existsSync(filePath)) {
      return res.status(404).json({ error: '파일을 찾을 수 없습니다' });
    }
    res.sendFile(filePath);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── 런 디렉토리 API: 한 번의 traversal 결과 폴더 단위로 노출 ─────
// 표준 레이아웃: <runDir>/run_meta.json, json/app_memory.json,
// json/screen_memory.json, logs/runtime.log, screen/<id>.png
function readJsonFile(absPath, res) {
  if (!fs.existsSync(absPath)) {
    return res.status(404).json({ error: `${path.basename(absPath)} 없음` });
  }
  try {
    res.json(JSON.parse(fs.readFileSync(absPath, 'utf8')));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}

app.get('/api/run/detect', (req, res) => {
  const dir = req.query.dir;
  if (!dir) return res.status(400).json({ error: 'dir 파라미터가 필요합니다' });
  try {
    const isRun =
      fs.existsSync(dir) &&
      fs.statSync(dir).isDirectory() &&
      fs.existsSync(path.join(dir, 'run_meta.json'));
    res.json({
      isRun,
      hasAppMemory: fs.existsSync(path.join(dir, 'json', 'app_memory.json')),
      hasScreenMemory: fs.existsSync(path.join(dir, 'json', 'screen_memory.json')),
      hasLog: fs.existsSync(path.join(dir, 'logs', 'runtime.log')),
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get('/api/run/meta', (req, res) => {
  const dir = req.query.dir;
  if (!dir) return res.status(400).json({ error: 'dir 파라미터가 필요합니다' });
  readJsonFile(path.join(dir, 'run_meta.json'), res);
});

app.get('/api/run/app-memory', (req, res) => {
  const dir = req.query.dir;
  if (!dir) return res.status(400).json({ error: 'dir 파라미터가 필요합니다' });
  readJsonFile(path.join(dir, 'json', 'app_memory.json'), res);
});

app.get('/api/run/screen-memory', (req, res) => {
  const dir = req.query.dir;
  if (!dir) return res.status(400).json({ error: 'dir 파라미터가 필요합니다' });
  readJsonFile(path.join(dir, 'json', 'screen_memory.json'), res);
});

app.get('/api/run/packet-memory', (req, res) => {
  const dir = req.query.dir;
  if (!dir) return res.status(400).json({ error: 'dir 파라미터가 필요합니다' });
  readJsonFile(path.join(dir, 'json', 'packet_memory.json'), res);
});

// log 필터: scroll/executor/a11y/warning/all. tail=마지막 N줄.
app.get('/api/run/log', (req, res) => {
  const dir = req.query.dir;
  const filter = (req.query.filter || 'all').toLowerCase();
  const tail = Math.max(1, parseInt(req.query.tail || '3000', 10) || 3000);
  if (!dir) return res.status(400).json({ error: 'dir 파라미터가 필요합니다' });

  const f = path.join(dir, 'logs', 'runtime.log');
  if (!fs.existsSync(f)) return res.status(404).json({ error: 'runtime.log 없음' });

  try {
    const text = fs.readFileSync(f, 'utf8');
    let lines = text.split(/\r?\n/);

    const patterns = {
      scroll: l =>
        l.includes('[SCROLL]') ||
        l.includes('[POLICY]') ||
        (l.includes('[A11Y]') && l.includes('VIEW_SCROLLED')) ||
        (l.includes('[EXECUTOR]') && l.includes(' swipe ')),
      executor: l => l.includes('[EXECUTOR]'),
      a11y: l => l.includes('[A11Y]'),
      warning: l => l.includes('[WARNING]') || l.includes('[ERROR]'),
    };
    if (filter !== 'all' && patterns[filter]) {
      lines = lines.filter(patterns[filter]);
    }
    const total = lines.length;
    if (lines.length > tail) lines = lines.slice(-tail);
    res.type('text/plain').set('X-Total-Lines', String(total)).send(lines.join('\n'));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get('/api/run/snapshot', (req, res) => {
  const { dir, id } = req.query;
  if (!dir || !id) {
    return res.status(400).json({ error: 'dir, id 파라미터가 필요합니다' });
  }
  const exts = ['.png', '.jpg', '.jpeg', '.webp'];
  for (const ext of exts) {
    const f = path.join(dir, 'screen', String(id) + ext);
    if (fs.existsSync(f)) return res.sendFile(f);
  }
  res.status(404).json({ error: `스냅샷 없음: ${id}` });
});

// ─── adb 제어판: 연결된 기기 목록 ───────────────────────────────
app.get('/api/adb/devices', (req, res) => {
  execFile(ADB_BIN, ['devices', '-l'], { timeout: 10000 }, (err, stdout = '', stderr = '') => {
    if (err && !stdout) {
      return res.status(500).json({
        error: err.code === 'ENOENT'
          ? `adb 실행 파일을 찾을 수 없음 (PATH 또는 ADB_BIN 확인)`
          : (stderr || err.message),
      });
    }
    const devices = stdout.split('\n').slice(1)
      .map(l => l.trim())
      .filter(l => l && !l.startsWith('*'))
      .map(l => {
        const parts = l.split(/\s+/);
        const model = (l.match(/model:(\S+)/) || [])[1] || '';
        return { serial: parts[0], state: parts[1] || '', model };
      })
      .filter(d => d.serial);
    res.json({ devices });
  });
});

// ─── adb 제어판: 버튼 설정 읽기 ─────────────────────────────────
app.get('/api/adb/buttons', (req, res) => {
  try {
    if (fs.existsSync(BUTTONS_FILE)) {
      const data = JSON.parse(fs.readFileSync(BUTTONS_FILE, 'utf8'));
      const buttons = Array.isArray(data) ? data : data.buttons;
      if (Array.isArray(buttons)) return res.json({ buttons });
    }
  } catch (e) {
    // 파일 손상 시 기본값으로 폴백
  }
  res.json({ buttons: DEFAULT_BUTTONS });
});

// ─── adb 제어판: 버튼 설정 저장 ─────────────────────────────────
app.post('/api/adb/buttons', (req, res) => {
  const buttons = req.body && req.body.buttons;
  if (!Array.isArray(buttons)) {
    return res.status(400).json({ error: 'buttons 배열이 필요합니다' });
  }
  try {
    fs.writeFileSync(BUTTONS_FILE, JSON.stringify({ buttons }, null, 2), 'utf8');
    res.json({ ok: true, count: buttons.length });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ─── adb 제어판: 명령 실행 ──────────────────────────────────────
app.post('/api/adb/run', (req, res) => {
  const args = parseAdbArgs(req.body && req.body.args);
  const serial = req.body && req.body.serial;
  if (args.length === 0) {
    return res.status(400).json({ error: 'args 가 비어 있습니다' });
  }
  const full = serial ? ['-s', String(serial), ...args] : args;
  const started = Date.now();
  execFile(
    ADB_BIN, full,
    { timeout: 30000, maxBuffer: 4 * 1024 * 1024 },
    (err, stdout = '', stderr = '') => {
      const elapsed = Date.now() - started;
      let code = 0;
      let errMsg = '';
      if (err) {
        code = typeof err.code === 'number' ? err.code : 1;
        if (err.code === 'ENOENT') errMsg = 'adb 실행 파일을 찾을 수 없음 (PATH 또는 ADB_BIN 확인)';
        else if (err.killed) errMsg = `타임아웃(${30000}ms) 초과`;
      }
      res.json({
        cmd: `${ADB_BIN} ${full.join(' ')}`,
        code,
        stdout,
        stderr: stderr || errMsg,
        elapsed_ms: elapsed,
      });
    },
  );
});

// ─── 라이브 화면: 현재 스크린샷 (exec-out screencap, CRLF 변환 없음) ──
app.get('/api/adb/screen', (req, res) => {
  const serial = req.query.serial;
  const child = spawn(ADB_BIN, adbArgs(serial, ['exec-out', 'screencap', '-p']));
  res.set('Content-Type', 'image/png');
  res.set('Cache-Control', 'no-store');
  let failed = false;
  child.on('error', (e) => {
    failed = true;
    if (!res.headersSent) res.status(500).json({ error: e.message });
  });
  child.stderr.on('data', () => {});
  child.stdout.pipe(res);
  child.on('close', () => { if (!failed && !res.writableEnded) res.end(); });
});

// ─── 리스너(instrumentation) 시작/중지/상태 ─────────────────────
app.post('/api/adb/listener/start', (req, res) => {
  const serial = (req.body && req.body.serial) || undefined;
  if (listenerProc) return res.json({ running: true, already: true });
  // 이전 세션의 좀비(서버 재시작 등으로 host에선 안 보이지만 디바이스엔 살아있는
  // 테스트 프로세스)를 먼저 청소. 이 단계 없이 spawn 하면 새 UiAutomation 등록이
  // 실패하거나 좀비 + 신규가 공존해 trigger 가 한쪽에만 먹는다.
  cleanupListener(serial, () => {
    const args = adbArgs(serial, ['shell', 'am', 'instrument', '-w', '-m', '-e', 'class', TEST_CLASS, TEST_RUNNER]);
    let proc;
    try {
      proc = spawn(ADB_BIN, args);
    } catch (e) {
      return res.status(500).json({ error: e.message });
    }
    listenerProc = proc;
    listenerSerial = serial || null;
    proc.stdout.on('data', () => {});
    proc.stderr.on('data', () => {});
    proc.on('exit', () => { if (listenerProc === proc) { listenerProc = null; listenerSerial = null; } });
    proc.on('error', () => { if (listenerProc === proc) { listenerProc = null; listenerSerial = null; } });
    res.json({ running: true });
  });
});

app.post('/api/adb/listener/stop', (req, res) => {
  const serial = (req.body && req.body.serial) || listenerSerial || undefined;
  if (listenerProc) {
    try { listenerProc.kill(); } catch (e) { /* noop */ }
    listenerProc = null;
    listenerSerial = null;
  }
  // TEST_PKG(테스트 프로세스)와 LISTENER_PKG(앱 본체) 둘 다 죽인다.
  cleanupListener(serial, () => res.json({ running: false }));
});

// 정확한 상태: in-memory 가 true 면 그대로, false 여도 디바이스에 살아있는 테스트가
// 있으면 좀비로 간주해 true 로 보고하고 serial 까지 복원해 알려준다. 클라이언트가
// 좀비를 인지하고 stop 으로 청소하도록 유도.
app.get('/api/adb/listener/status', (req, res) => {
  const serial = req.query.serial || listenerSerial || undefined;
  if (listenerProc) return res.json({ running: true, serial: listenerSerial, owned: true });
  probeListenerAlive(serial, (alive) => {
    if (alive) return res.json({ running: true, serial: serial || null, owned: false, zombie: true });
    res.json({ running: false, serial: null, owned: false });
  });
});

// ─── a11y 이벤트 실시간 스트림 (SSE, logcat IPG_EVT tail) ────────
app.get('/api/adb/events', (req, res) => {
  const serial = req.query.serial;
  res.set({
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
  });
  if (res.flushHeaders) res.flushHeaders();

  const lc = spawn(ADB_BIN, adbArgs(serial, ['logcat', '-s', 'IPG_EVT:I', '-v', 'raw', '-T', '1']));
  let buf = '';
  lc.stdout.on('data', (d) => {
    buf += d.toString('utf8');
    let idx;
    while ((idx = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 1);
      if (line.startsWith('{')) res.write(`data: ${line}\n\n`);
    }
  });
  lc.stderr.on('data', () => {});
  lc.on('error', (e) => { try { res.write(`event: error\ndata: ${JSON.stringify({ error: e.message })}\n\n`); } catch (_) {} });

  const ping = setInterval(() => { try { res.write(': ping\n\n'); } catch (_) {} }, 15000);
  req.on('close', () => { clearInterval(ping); try { lc.kill(); } catch (_) {} });
});

// ─── 현재 화면 dump: trigger → DUMP_WRITTEN 대기 → XML pull ──────
app.post('/api/adb/dump', (req, res) => {
  const serial = (req.body && req.body.serial) || undefined;
  const lc = spawn(ADB_BIN, adbArgs(serial, ['logcat', '-s', 'IPG_EVT:I', '-v', 'raw', '-T', '1']));
  let buf = '';
  let done = false;

  const finish = (errMsg, xmlPath) => {
    if (done) return;
    done = true;
    clearTimeout(timer);
    try { lc.kill(); } catch (_) {}
    if (errMsg) return res.status(500).json({ error: errMsg });
    execFile(ADB_BIN, adbArgs(serial, ['exec-out', 'cat', xmlPath]),
      { timeout: 15000, maxBuffer: 32 * 1024 * 1024 }, (e, xml = '') => {
        if (e) return res.status(500).json({ error: 'XML pull 실패: ' + e.message });
        execFile(ADB_BIN, adbArgs(serial, ['shell', 'wm', 'size']),
          { timeout: 5000 }, (e2, sz = '') => {
            const m = sz.match(/Override size:\s*(\d+)x(\d+)/) || sz.match(/Physical size:\s*(\d+)x(\d+)/);
            res.json({ xml, xmlPath, screenW: m ? +m[1] : 0, screenH: m ? +m[2] : 0 });
          });
      });
  };

  lc.stdout.on('data', (d) => {
    buf += d.toString('utf8');
    let idx;
    while ((idx = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 1);
      if (!line.startsWith('{')) continue;
      try {
        const j = JSON.parse(line);
        if (j.type === 'DUMP_WRITTEN' && j.xml) { finish(null, j.xml); return; }
      } catch (_) { /* skip */ }
    }
  });
  lc.on('error', (e) => finish('logcat 실패: ' + e.message));

  execFile(ADB_BIN, adbArgs(serial, ['shell', 'touch', TRIGGER_FILE]),
    { timeout: 5000 }, (e) => { if (e) finish('trigger touch 실패: ' + e.message); });

  const timer = setTimeout(
    () => finish('DUMP_WRITTEN 미수신 (리스너가 실행 중인지 확인하세요)'),
    8000,
  );
});

// ─── uiautomator dump (listener 불필요한 polyfill) ───────────────
// /api/adb/dump 는 our instrumentation listener 가 떠 있어야 동작한다 (빠름).
// 이 endpoint 는 listener 없이도 동작하는 fallback — Android 표준 uiautomator
// 바이너리에 의존. 표준 uiautomator 는 <hierarchy> 루트에 rotation 만 채워서
// package/activity/window-id 가 누락된다 (listener 는 다 채움). 동일 정보를
// 'dumpsys activity top' 결과에서 긁어 XML 본문에 inject 해 둘의 결과가 같은
// 모양이 되게 한다. 결과는 ({xml, xmlPath, screenW, screenH, injectedMeta?}).

// 'ACTIVITY com.foo.bar/.MyActivity ...' or 'ACTIVITY com.foo.bar/com.foo.bar.MyActivity ...'
function parseTopActivity(text) {
  const m = (text || '').match(/^\s*ACTIVITY\s+([\w.]+)\/(\S+)/m);
  if (!m) return null;
  const pkg = m[1];
  const cls = m[2];
  const activity = cls.startsWith('.') ? pkg + cls : cls;
  return { package: pkg, activity };
}

// <hierarchy ...> 의 누락된 속성만 채워 다시 직렬화. 기존 속성은 건드리지 않음.
function injectHierarchyAttrs(xml, fill) {
  return xml.replace(/<hierarchy\b([^>]*)>/, (full, attrs) => {
    let out = attrs;
    if (fill.package  && !/\bpackage=/.test(out))   out += ` package="${escapeXml(fill.package)}"`;
    if (fill.activity && !/\bactivity=/.test(out))  out += ` activity="${escapeXml(fill.activity)}"`;
    return `<hierarchy${out}>`;
  });
}

function escapeXml(s) {
  return String(s).replace(/[<>&"']/g, c => (
    { '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' }[c]
  ));
}

app.post('/api/adb/uia-dump', (req, res) => {
  const serial = (req.body && req.body.serial) || undefined;
  execFile(ADB_BIN, adbArgs(serial, ['shell', 'uiautomator', 'dump']),
    { timeout: 15000 }, (e, out = '', errOut = '') => {
      if (e) return res.status(500).json({ error: 'uiautomator dump 실패: ' + (errOut || e.message) });
      const m = (out || '').match(/dumped to:?\s*(\S+)/i);
      const xmlPath = (m && m[1]) || '/sdcard/window_dump.xml';
      execFile(ADB_BIN, adbArgs(serial, ['exec-out', 'cat', xmlPath]),
        { timeout: 15000, maxBuffer: 32 * 1024 * 1024 }, (e2, xml = '') => {
          if (e2) return res.status(500).json({ error: 'XML pull 실패: ' + e2.message });
          // 병렬: wm size + dumpsys activity top
          let pendingWm = true, pendingTop = true;
          let wmStr = '', topStr = '';
          const maybeRespond = () => {
            if (pendingWm || pendingTop) return;
            const sm = wmStr.match(/Override size:\s*(\d+)x(\d+)/) || wmStr.match(/Physical size:\s*(\d+)x(\d+)/);
            const top = parseTopActivity(topStr);
            const finalXml = top ? injectHierarchyAttrs(xml, top) : xml;
            res.json({
              xml: finalXml,
              xmlPath,
              screenW: sm ? +sm[1] : 0,
              screenH: sm ? +sm[2] : 0,
              injectedMeta: top || null,
            });
          };
          execFile(ADB_BIN, adbArgs(serial, ['shell', 'wm', 'size']),
            { timeout: 5000 }, (_e3, sz = '') => { wmStr = sz || ''; pendingWm = false; maybeRespond(); });
          execFile(ADB_BIN, adbArgs(serial, ['shell', 'dumpsys', 'activity', 'top']),
            { timeout: 5000, maxBuffer: 8 * 1024 * 1024 },
            (_e4, t = '') => { topStr = t || ''; pendingTop = false; maybeRespond(); });
        });
    });
});

// ─── 패킷 누적치 (타겟 앱 UID, netstats) ────────────────────────
app.get('/api/adb/packets', (req, res) => {
  const { pkg, serial } = req.query;
  if (!pkg) return res.status(400).json({ error: 'pkg 파라미터가 필요합니다' });
  resolveUid(serial, pkg, (uid) => {
    if (uid == null) return res.status(404).json({ error: `UID 해석 실패: ${pkg}` });
    execFile(ADB_BIN, adbArgs(serial, ['shell', 'dumpsys', 'netstats', 'detail', 'full']),
      { timeout: 20000, maxBuffer: 32 * 1024 * 1024 }, (e, out = '') => {
        if (e && !out) return res.status(500).json({ error: e.message });
        res.json({ uid, ...parseUidTotal(out, uid) });
      });
  });
});

// ─── 스냅샷 저장: 클라이언트가 보유한 XML + PNG 바이트를 디스크에 기록 ─
// 브라우저가 본 그대로의 페어를 저장하기 위해 서버는 재캡처하지 않고 본문의
// 바이트를 그대로 기록. 동일 timestamp 기준 .xml + .png 두 파일 한 쌍.
function pad2(n) { return n < 10 ? '0' + n : '' + n; }
function pad3(n) { return n < 10 ? '00' + n : n < 100 ? '0' + n : '' + n; }
function snapshotNames() {
  const d = new Date();
  const ymd = `${d.getFullYear()}${pad2(d.getMonth() + 1)}${pad2(d.getDate())}`;
  const hms = `${pad2(d.getHours())}${pad2(d.getMinutes())}${pad2(d.getSeconds())}_${pad3(d.getMilliseconds())}`;
  return { ymd, base: `snap_${hms}` };
}

app.post('/api/adb/snapshot', (req, res) => {
  const { xml, png_base64, dir } = req.body || {};
  if (typeof xml !== 'string' || !xml.length) {
    return res.status(400).json({ error: 'xml 문자열이 필요합니다' });
  }
  if (typeof png_base64 !== 'string' || !png_base64.length) {
    return res.status(400).json({ error: 'png_base64 가 필요합니다' });
  }
  // 경로 결정: dir 이 주어지면 그 아래로, 아니면 outputs_APK/_monitor_snapshots/.
  // 경로는 서버 cwd (보통 Monitor/) 기준이므로 명시적으로 repo root 까지 올라간다.
  const repoRoot = path.resolve(__dirname, '..', '..');
  const { ymd, base } = snapshotNames();
  const root = dir && String(dir).trim()
    ? path.resolve(repoRoot, String(dir).trim())
    : path.join(repoRoot, 'outputs_APK', '_monitor_snapshots', ymd);

  try {
    fs.mkdirSync(root, { recursive: true });
    const xmlPath = path.join(root, base + '.xml');
    const pngPath = path.join(root, base + '.png');
    fs.writeFileSync(xmlPath, xml, 'utf8');
    // png_base64 는 data URL prefix("data:image/png;base64,") 포함 가능 → 떼어냄.
    const b64 = png_base64.includes(',') ? png_base64.split(',').pop() : png_base64;
    fs.writeFileSync(pngPath, Buffer.from(b64, 'base64'));
    res.json({
      ok: true,
      dir: root,
      xmlPath,
      pngPath,
      xmlBytes: Buffer.byteLength(xml, 'utf8'),
      pngBytes: fs.statSync(pngPath).size,
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ─── screen_id 검사: XML → screen_id + 매칭 trace ────────────────
// src_apk/tools/inspect_screen_id.py 를 spawn해 결과 JSON을 그대로 forward.
// XML 입력은 항상 (run dir, snapshot_id) 페어로 받아 서버가 경로 조립한다 —
// 임의 절대 경로 노출을 피하고, 매칭에 쓸 app_memory.json도 같은 run dir에서
// 자동 해석한다.
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const PY_BIN = process.env.PYTHON_BIN || 'python';
const INSPECT_SCRIPT = path.join(REPO_ROOT, 'src_apk', 'tools', 'inspect_screen_id.py');
const COMPARE_SCRIPT = path.join(REPO_ROOT, 'src_apk', 'tools', 'compare_screen_ids.py');

// root 가 비어 있으면 repo 표준 위치(outputs_APK, outputs) 를 자동으로 본다.
// 둘 다 존재하면 합쳐 반환. 그 결과 어떤 root 들이 실제로 스캔됐는지도 응답에 담음.
const DEFAULT_RUN_ROOTS = [
  path.join(REPO_ROOT, 'outputs_APK'),
  path.join(REPO_ROOT, 'outputs'),
];

// root 디렉토리 아래 run_meta.json 또는 json/app_memory.json 이 있는 폴더를
// 깊이 제한으로 스캔. outputs_APK/<app>/<timestamp>/ 처럼 2단계가 흔해 maxDepth=4면 충분.
app.get('/api/list-runs', (req, res) => {
  const maxDepth = Math.max(1, Math.min(6, parseInt(req.query.maxDepth || '4', 10)));
  const rootsToScan = req.query.root
    ? [req.query.root]
    : DEFAULT_RUN_ROOTS.filter(p => fs.existsSync(p));
  if (rootsToScan.length === 0) {
    return res.status(404).json({
      error: 'root 가 비어 있고 디폴트 위치(outputs_APK, outputs) 둘 다 없음',
      defaults_checked: DEFAULT_RUN_ROOTS,
    });
  }
  for (const r of rootsToScan) {
    if (!fs.existsSync(r)) {
      return res.status(404).json({ error: `root 없음: ${r}` });
    }
  }
  const runs = [];
  function walk(dir, depth) {
    if (depth > maxDepth) return;
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    // run 인식 기준: run_meta.json 또는 json/app_memory.json + xml/ 가 있으면
    // 검사 가능한 run 으로 본다 (partial run = finalize 전에 죽은 케이스 포함).
    const hasRunMeta = entries.some(e => e.isFile() && e.name === 'run_meta.json');
    const hasXmlDir = entries.some(e => e.isDirectory() && e.name === 'xml');
    let hasAppMem = false;
    if (hasXmlDir) {
      try {
        hasAppMem = fs.existsSync(path.join(dir, 'json', 'app_memory.json'));
      } catch {}
    }
    if (hasRunMeta || hasAppMem) {
      let mtime = 0;
      try {
        const ref = hasRunMeta
          ? path.join(dir, 'run_meta.json')
          : path.join(dir, 'json', 'app_memory.json');
        mtime = fs.statSync(ref).mtimeMs;
      } catch {}
      runs.push({
        path: dir,
        name: path.basename(dir),
        parent: path.basename(path.dirname(dir)),
        modified: mtime,
        hasRunMeta,
        partial: !hasRunMeta,
      });
      return; // run 디렉토리 안은 더 안 들어감 (중첩 run 없음 가정)
    }
    for (const e of entries) {
      if (!e.isDirectory() || e.name.startsWith('.') || e.name === 'node_modules') continue;
      walk(path.join(dir, e.name), depth + 1);
    }
  }
  try {
    for (const r of rootsToScan) walk(r, 0);
    runs.sort((a, b) => b.modified - a.modified);
    res.json({ roots: rootsToScan, runs });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get('/api/run/snapshots', (req, res) => {
  // 검사 탭에서 snapshot 드롭다운을 채우기 위한 list. xml/ 디렉토리의 .xml
  // 파일명을 stem으로 추출해 정렬한다.
  const dir = req.query.dir;
  if (!dir) return res.status(400).json({ error: 'dir 파라미터가 필요합니다' });
  const xmlDir = path.join(dir, 'xml');
  if (!fs.existsSync(xmlDir)) {
    return res.status(404).json({ error: `xml 디렉토리 없음: ${xmlDir}` });
  }
  try {
    const ids = fs.readdirSync(xmlDir)
      .filter(f => f.endsWith('.xml'))
      .map(f => f.replace(/\.xml$/i, ''))
      .sort();
    res.json({ snapshots: ids });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// XML 본문을 그대로 stdin 으로 helper 에 흘리는 text-mode 변형.
// 기기 제어 탭에서 라이브 dump 한 XML 을 파일로 저장하지 않고도 바로 검사
// 가능. 선택적으로 dir 을 주면 그 run 의 app_memory.json 으로 매처 시뮬레이션도 같이.
app.post('/api/inspect-screen-id-text', (req, res) => {
  const { xml, label, threshold, dir } = req.body || {};
  if (typeof xml !== 'string' || !xml.length) {
    return res.status(400).json({ error: 'xml 본문이 필요합니다' });
  }
  const thr = threshold != null && !isNaN(parseFloat(threshold))
    ? String(parseFloat(threshold))
    : '0.6';
  const args = [
    INSPECT_SCRIPT,
    '--xml-text', '-',
    '--threshold', thr,
  ];
  if (dir && fs.existsSync(path.join(dir, 'json', 'app_memory.json'))) {
    args.push('--app-memory', path.join(dir, 'json', 'app_memory.json'));
  }
  const child = spawn(PY_BIN, args, {
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });
  let stdout = '';
  let stderr = '';
  child.stdout.on('data', d => { stdout += d.toString('utf8'); });
  child.stderr.on('data', d => { stderr += d.toString('utf8'); });
  child.on('error', (e) => {
    res.status(500).json({ error: 'python 실행 실패: ' + e.message });
  });
  child.on('close', (code) => {
    if (code !== 0 && !stdout) {
      return res.status(500).json({
        error: 'helper exit ' + code,
        stderr: stderr.slice(0, 4000),
      });
    }
    try {
      const out = JSON.parse(stdout);
      // label 은 결과에 input.xml 자리에 들어가도록 덮어쓴다.
      if (label && out.input) out.input.xml = label;
      res.json(out);
    } catch (e) {
      res.status(500).json({
        error: 'helper JSON 파싱 실패: ' + e.message,
        raw: stdout.slice(0, 4000),
      });
    }
  });
  child.stdin.write(xml, 'utf8');
  child.stdin.end();
});

app.get('/api/run/inspect-screen-id', (req, res) => {
  const { dir, snapshotId } = req.query;
  const threshold = req.query.threshold ? parseFloat(req.query.threshold) : 0.6;
  if (!dir || !snapshotId) {
    return res.status(400).json({ error: 'dir, snapshotId 파라미터가 필요합니다' });
  }
  const xmlPath = path.join(dir, 'xml', String(snapshotId) + '.xml');
  if (!fs.existsSync(xmlPath)) {
    return res.status(404).json({ error: `XML 없음: ${xmlPath}` });
  }
  const memPath = path.join(dir, 'json', 'app_memory.json');
  const args = [
    INSPECT_SCRIPT,
    '--xml', xmlPath,
    '--threshold', String(isNaN(threshold) ? 0.6 : threshold),
    '--snapshot-id', String(snapshotId),
  ];
  if (fs.existsSync(memPath)) {
    args.push('--app-memory', memPath);
  }
  execFile(PY_BIN, args, {
      maxBuffer: 32 * 1024 * 1024,
      timeout: 60000,
      // Windows 기본 stdout 인코딩(cp949)에서 XML 안 비-cp949 문자(•/…/emoji)가
      // 깨지지 않도록 강제 UTF-8. helper 내부에서도 reconfigure 하지만 보강.
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    },
    (err, stdout, stderr) => {
      if (err) {
        return res.status(500).json({
          error: err.code === 'ENOENT'
            ? `python 실행 파일을 찾을 수 없음 (PYTHON_BIN 환경변수 확인)`
            : (stderr || err.message),
          stderr: stderr ? String(stderr).slice(0, 4000) : undefined,
        });
      }
      try {
        res.json(JSON.parse(stdout));
      } catch (e) {
        res.status(500).json({
          error: `helper JSON 파싱 실패: ${e.message}`,
          raw: String(stdout).slice(0, 4000),
        });
      }
    }
  );
});

// POST 변형: mixed items 지원. body { items: [{type:'snapshot', dir, id} |
//                                                  {type:'inline', xml, label}] }
// 인라인 XML 항목(예: 기기 dump)을 핀된 snapshot 들과 같은 매트릭스에서 비교.
// inline 은 임시 파일로 내려 동일 helper 재사용 → 처리 후 즉시 정리.
app.post('/api/run/compare-screen-ids', (req, res) => {
  const items = Array.isArray(req.body?.items) ? req.body.items : [];
  if (items.length === 0) {
    return res.status(400).json({ error: 'items 가 비어 있음' });
  }
  if (items.length > 20) {
    return res.status(400).json({ error: 'items 는 최대 20개' });
  }
  const tmpFiles = [];
  const args = [COMPARE_SCRIPT];
  try {
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (!it || !it.type) throw new Error(`items[${i}] type 누락`);
      if (it.type === 'snapshot') {
        if (!it.dir || !it.id) throw new Error(`items[${i}] dir/id 필요`);
        const xml = path.join(it.dir, 'xml', it.id + '.xml');
        if (!fs.existsSync(xml)) throw new Error(`XML 없음: ${xml}`);
        args.push('--xml', xml, '--snapshot-id', String(it.id));
      } else if (it.type === 'inline') {
        if (typeof it.xml !== 'string' || !it.xml.length) {
          throw new Error(`items[${i}].xml 본문 필요`);
        }
        const tmp = path.join(
          require('os').tmpdir(),
          `ipg_cmp_${Date.now()}_${i}_${Math.random().toString(36).slice(2, 8)}.xml`,
        );
        fs.writeFileSync(tmp, it.xml, 'utf8');
        tmpFiles.push(tmp);
        args.push('--xml', tmp, '--snapshot-id', String(it.label || `inline_${i}`));
      } else {
        throw new Error(`알 수 없는 item type: ${it.type}`);
      }
    }
  } catch (e) {
    // 파싱 단계 실패: 이미 만든 temp 정리
    for (const t of tmpFiles) { try { fs.unlinkSync(t); } catch (_) {} }
    return res.status(400).json({ error: e.message });
  }

  execFile(PY_BIN, args, {
      maxBuffer: 64 * 1024 * 1024,
      timeout: 60000,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    },
    (err, stdout, stderr) => {
      for (const t of tmpFiles) { try { fs.unlinkSync(t); } catch (_) {} }
      if (err) {
        return res.status(500).json({
          error: err.code === 'ENOENT'
            ? 'python 실행 파일을 찾을 수 없음 (PYTHON_BIN 환경변수 확인)'
            : (stderr || err.message),
          stderr: stderr ? String(stderr).slice(0, 4000) : undefined,
        });
      }
      try {
        res.json(JSON.parse(stdout));
      } catch (e) {
        res.status(500).json({
          error: `compare helper JSON 파싱 실패: ${e.message}`,
          raw: String(stdout).slice(0, 4000),
        });
      }
    }
  );
});

// 여러 snapshot 의 screen_id 빌드 결과 + 페어와이즈 Jaccard matrix 한 번에.
// snapshotIds 는 콤마 구분 ('000001,000013,000014'). 같은 run dir 안에서만.
// (구버전 호환: 단순 케이스용 GET; mixed items 는 POST 사용)
app.get('/api/run/compare-screen-ids', (req, res) => {
  const { dir, snapshotIds } = req.query;
  if (!dir || !snapshotIds) {
    return res.status(400).json({ error: 'dir, snapshotIds 파라미터가 필요합니다' });
  }
  const ids = String(snapshotIds).split(',').map(s => s.trim()).filter(Boolean);
  if (ids.length === 0) return res.status(400).json({ error: 'snapshotIds 가 비어 있음' });
  if (ids.length > 20) return res.status(400).json({ error: 'snapshotIds 는 최대 20개' });

  const args = [COMPARE_SCRIPT];
  for (const sid of ids) {
    const xml = path.join(dir, 'xml', sid + '.xml');
    if (!fs.existsSync(xml)) {
      return res.status(404).json({ error: `XML 없음: ${xml}` });
    }
    args.push('--xml', xml, '--snapshot-id', sid);
  }
  execFile(PY_BIN, args, {
      maxBuffer: 64 * 1024 * 1024,
      timeout: 60000,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    },
    (err, stdout, stderr) => {
      if (err) {
        return res.status(500).json({
          error: err.code === 'ENOENT'
            ? 'python 실행 파일을 찾을 수 없음 (PYTHON_BIN 환경변수 확인)'
            : (stderr || err.message),
          stderr: stderr ? String(stderr).slice(0, 4000) : undefined,
        });
      }
      try {
        res.json(JSON.parse(stdout));
      } catch (e) {
        res.status(500).json({
          error: `compare helper JSON 파싱 실패: ${e.message}`,
          raw: String(stdout).slice(0, 4000),
        });
      }
    }
  );
});

// ─── 서버 시작 ───────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`\n🚀 IPG Monitor Server`);
  console.log(`   http://localhost:${PORT}\n`);
});
