// 트리(File System Access API로 만든)에서 한 run 출력 디렉토리의
// 표준 파일들을 찾아 텍스트/JSON으로 읽어 들인 다음 RunData 객체를 만든다.
//
// 표준 레이아웃:
//   <runDir>/run_meta.json
//   <runDir>/json/app_memory.json
//   <runDir>/json/screen_memory.json   (선택)
//   <runDir>/logs/runtime.log          (선택)
//   <runDir>/screen/*.png              (blobMap에 이미 들어옴)

function findChild(items, name) {
  return items.find(it => it.name === name);
}

async function readText(node) {
  if (!node) return null;
  if (node.handle) {
    const f = await node.handle.getFile();
    return await f.text();
  }
  if (node.file) return await node.file.text();
  return null;
}

async function readJson(node) {
  const t = await readText(node);
  if (t == null) return null;
  try { return JSON.parse(t); }
  catch { return null; }
}

// 트리가 run dir인지 빠르게 판정 (root에 run_meta.json이 있는가)
export function detectRunInTree(items) {
  return Boolean(findChild(items, 'run_meta.json'));
}

export async function loadRunFromTree(items, blobMap, dirName) {
  const metaNode = findChild(items, 'run_meta.json');
  if (!metaNode) {
    throw new Error('run_meta.json을 찾을 수 없습니다 (run 디렉토리가 아닙니다).');
  }

  const jsonDir = findChild(items, 'json');
  const logsDir = findChild(items, 'logs');

  const appMemoryNode = jsonDir?.children
    ? findChild(jsonDir.children, 'app_memory.json')
    : null;
  const screenMemoryNode = jsonDir?.children
    ? findChild(jsonDir.children, 'screen_memory.json')
    : null;
  const logNode = logsDir?.children
    ? findChild(logsDir.children, 'runtime.log')
    : null;

  const [meta, appMemory, screenMemory, logText] = await Promise.all([
    readJson(metaNode),
    readJson(appMemoryNode),
    readJson(screenMemoryNode),
    readText(logNode),
  ]);

  return {
    runName: dirName || meta?.app?.app_name || 'run',
    meta,
    appMemory,
    screenMemory,
    logText: logText ?? '',
    blobMap: blobMap || {},
  };
}
