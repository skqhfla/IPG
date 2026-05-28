const express = require('express');
const cors = require('cors');
const fs = require('fs');
const path = require('path');

const app = express();
const PORT = 3001;

app.use(cors());
app.use(express.json());

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

// ─── 서버 시작 ───────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`\n🚀 IPG Monitor Server`);
  console.log(`   http://localhost:${PORT}\n`);
});
