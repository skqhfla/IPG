import { useState, useRef } from 'react';
import axios from 'axios';
import { detectRunInTree, loadRunFromTree } from '../utils/loadRun.js';

// ── 이미지 확장자 목록 ──────────────────────────────────────────────
const IMG_EXTS = ['.png', '.jpg', '.jpeg', '.webp'];

// ── 공통 유틸: 확장자 추출 ─────────────────────────────────────────
function getExt(name) {
  return name.includes('.') ? name.slice(name.lastIndexOf('.')).toLowerCase() : '';
}

// ── 공통 유틸: 트리 정렬 (폴더 먼저, 이름순) ───────────────────────
function sortItems(items) {
  return [...items].sort((a, b) => {
    if (a.isDirectory && !b.isDirectory) return -1;
    if (!a.isDirectory && b.isDirectory) return 1;
    return a.name.localeCompare(b.name, 'ko');
  });
}

// ── 로컬 모드: File System Access API용 트리 생성 ─────────────────
async function buildTreeFromDirectoryHandle(dirHandle, currentPath = '') {
  const items = [];

  for await (const [name, handle] of dirHandle.entries()) {
    const ext = getExt(name);
    const path = currentPath ? `${currentPath}/${name}` : name;

    if (handle.kind === 'directory') {
      const children = await buildTreeFromDirectoryHandle(handle, path);
      items.push({
        name,
        path,
        ext: '',
        isDirectory: true,
        children,
        handle,
      });
    } else {
      items.push({
        name,
        path,
        ext,
        isDirectory: false,
        children: [],
        handle,
      });
    }
  }

  return sortItems(items);
}

// ── 로컬 모드: 트리에서 이미지 blob URL 수집 ──────────────────────
async function collectBlobUrlsFromTree(items, blobMap = {}) {
  for (const item of items) {
    if (item.isDirectory) {
      await collectBlobUrlsFromTree(item.children, blobMap);
    } else if (IMG_EXTS.includes(item.ext)) {
      try {
        const f = await item.handle.getFile();
        const id = item.name.slice(0, item.name.lastIndexOf('.'));
        blobMap[id] = URL.createObjectURL(f);
      } catch {
        // ignore
      }
    }
  }
  return blobMap;
}

// ── 로컬 모드 폴백: webkitdirectory 결과를 트리로 변환 ─────────────
function buildTreeFromFileList(fileList) {
  const root = [];

  function insertNode(parts, file, basePath = '') {
    const [current, ...rest] = parts;
    const currentPath = basePath ? `${basePath}/${current}` : current;

    if (rest.length === 0) {
      rootPushOrInsert(root, {
        name: current,
        path: currentPath,
        ext: getExt(current),
        isDirectory: false,
        children: [],
        file,
      });
      return;
    }

    let dir = findNode(root, currentPath);
    if (!dir) {
      dir = {
        name: current,
        path: currentPath,
        ext: '',
        isDirectory: true,
        children: [],
      };
      root.push(dir);
    }

    insertNodeIntoChildren(dir.children, rest, file, currentPath);
  }

  function insertNodeIntoChildren(children, parts, file, basePath = '') {
    const [current, ...rest] = parts;
    const currentPath = basePath ? `${basePath}/${current}` : current;

    if (rest.length === 0) {
      rootPushOrInsert(children, {
        name: current,
        path: currentPath,
        ext: getExt(current),
        isDirectory: false,
        children: [],
        file,
      });
      return;
    }

    let dir = findNode(children, currentPath);
    if (!dir) {
      dir = {
        name: current,
        path: currentPath,
        ext: '',
        isDirectory: true,
        children: [],
      };
      children.push(dir);
    }

    insertNodeIntoChildren(dir.children, rest, file, currentPath);
  }

  function findNode(nodes, path) {
    return nodes.find(node => node.path === path && node.isDirectory);
  }

  function rootPushOrInsert(nodes, node) {
    const exists = nodes.some(n => n.path === node.path);
    if (!exists) nodes.push(node);
  }

  const blobMap = {};

  for (const file of fileList) {
    const relPath = file.webkitRelativePath;
    if (!relPath) continue;

    const parts = relPath.split('/');
    const [, ...innerParts] = parts; // 첫 폴더명 제거
    if (innerParts.length === 0) continue;

    insertNode(innerParts, file);

    const ext = getExt(file.name);
    if (IMG_EXTS.includes(ext)) {
      const id = file.name.slice(0, file.name.lastIndexOf('.'));
      blobMap[id] = URL.createObjectURL(file);
    }
  }

  function deepSort(items) {
    const sorted = sortItems(items);
    for (const item of sorted) {
      if (item.isDirectory) item.children = deepSort(item.children);
    }
    return sorted;
  }

  return { tree: deepSort(root), blobMap };
}

// ── 파일 아이템 (서버/로컬 공용 재귀 트리) ─────────────────────────
function FileItem({
  item,
  depth = 0,
  onSelect,
  selectedFile,
  mode,
}) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState(item.children || []);
  const [loading, setLoading] = useState(false);

  const isJson = item.ext === '.json';
  const isDir = item.isDirectory;

  let icon = '📄';
  if (isDir) icon = expanded ? '📂' : '📁';
  else if (isJson) icon = '📋';
  else if (IMG_EXTS.includes(item.ext)) icon = '🖼️';

  const handleClick = async () => {
    if (isDir) {
      if (mode === 'server') {
        if (!expanded && children.length === 0) {
          setLoading(true);
          try {
            const res = await axios.get(`/api/browse?path=${encodeURIComponent(item.path)}`);
            setChildren(res.data.items || []);
          } catch {
            // ignore
          } finally {
            setLoading(false);
          }
        }
      }
      setExpanded(v => !v);
      return;
    }

    if (isJson) {
      onSelect(item);
    }
  };

  return (
    <>
      <div
        className={`file-item ${isDir ? 'is-dir' : ''} ${selectedFile === item.path ? 'selected' : ''}`}
        style={{ paddingLeft: `${14 + depth * 14}px` }}
        onClick={handleClick}
        title={item.path}
      >
        <span className="file-icon">{loading ? '⏳' : icon}</span>
        <span className="file-name">{item.name}</span>
      </div>

      {isDir && expanded && children.map(child => (
        <FileItem
          key={child.path}
          item={child}
          depth={depth + 1}
          onSelect={onSelect}
          selectedFile={selectedFile}
          mode={mode}
        />
      ))}
    </>
  );
}

// ── Sidebar 메인 ──────────────────────────────────────────────────
export default function Sidebar({ onFileSelect, onRunLoad, collapsed }) {
  const [path, setPath] = useState('');
  const [mode, setMode] = useState('idle');   // 'idle' | 'local'
  const [items, setItems] = useState([]);     // 트리
  const [blobUrlMap, setBlobUrlMap] = useState({});
  const [selectedFile, setSelectedFile] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const fileInputRef = useRef(null);

  // ── 열기 버튼 ─────────────────────────────────────────────────
  // ── 폴더 선택 다이얼로그 ──────────────────────────────────────
  const handleBrowse = async () => {
    if (typeof window.showDirectoryPicker === 'function') {
      try {
        const dirHandle = await window.showDirectoryPicker({ mode: 'read' });
        setLoading(true);
        setError('');

        const tree = await buildTreeFromDirectoryHandle(dirHandle, dirHandle.name);
        const blobs = await collectBlobUrlsFromTree(tree, {});

        setPath(dirHandle.name);
        setItems(tree);
        setBlobUrlMap(blobs);
        setMode('local');
        setSelectedFile('');
      } catch (err) {
        if (err.name !== 'AbortError') {
          setError('폴더를 열 수 없습니다: ' + err.message);
        }
      } finally {
        setLoading(false);
      }
    } else {
      // 폴백: input[webkitdirectory]
      fileInputRef.current?.click();
    }
  };

  // ── webkitdirectory 폴백 처리 ─────────────────────────────────
  const handleFileInput = async (e) => {
    const files = Array.from(e.target.files);
    if (!files.length) return;

    setLoading(true);
    setError('');

    const { tree, blobMap } = buildTreeFromFileList(files);
    const folderName = files[0].webkitRelativePath.split('/')[0];

    setPath(folderName);
    setItems(tree);
    setBlobUrlMap(blobMap);
    setMode('local');
    setSelectedFile('');
    setLoading(false);

    e.target.value = '';
  };

  // ── 로컬 JSON 파일 클릭 ──────────────────────────────────────
  const handleLocalFileSelect = async (item) => {
    setSelectedFile(item.path);
    setError('');

    try {
      let text = '';
      if (item.handle) {
        const f = await item.handle.getFile();
        text = await f.text();
      } else if (item.file) {
        text = await item.file.text();
      } else {
        throw new Error('파일 핸들을 찾을 수 없습니다.');
      }

      const mainData = JSON.parse(text);

      // 스마트 로딩: utg.json인 경우 app_memory.json 자동 탐색
      if (item.name === 'utg.json' && !mainData.screens && !mainData.app_memory) {
        try {
          // 1. sibling 'json' 폴더 찾기
          const parentPath = item.path.substring(0, item.path.lastIndexOf('/'));
          const grandParentPath = parentPath.substring(0, parentPath.lastIndexOf('/'));
          
          // 트리에서 검색 (items는 최상위 트리)
          const findFileInTree = (nodes, targetPath) => {
            for (const node of nodes) {
              if (node.path === targetPath) return node;
              if (node.isDirectory && node.children) {
                const found = findFileInTree(node.children, targetPath);
                if (found) return found;
              }
            }
            return null;
          };

          const memoryPath = grandParentPath ? `${grandParentPath}/json/app_memory.json` : 'json/app_memory.json';
          const memoryNode = findFileInTree(items, memoryPath);

          if (memoryNode) {
            let memoryText = '';
            if (memoryNode.handle) {
              const f = await memoryNode.handle.getFile();
              memoryText = await f.text();
            } else if (memoryNode.file) {
              memoryText = await memoryNode.file.text();
            }
            const memoryData = JSON.parse(memoryText);
            mainData.app_memory = memoryData;
          }
        } catch (e) {
          console.warn('app_memory.json 로드 실패:', e);
        }
      }

      onFileSelect(mainData, null, blobUrlMap);
    } catch (err) {
      setError('JSON 파싱 실패: ' + err.message);
    }
  };

  // ── 서버 JSON 파일 클릭 ──────────────────────────────────────
  const handleServerFileSelect = async (item) => {
    setSelectedFile(item.path);
    setError('');

    try {
      const res = await axios.get(`/api/read-json?path=${encodeURIComponent(item.path)}`);
      const mainData = res.data;

      // 스마트 로딩: utg.json인 경우 app_memory.json 자동 탐색
      if (item.name === 'utg.json' && !mainData.screens && !mainData.app_memory) {
        try {
          // 경로 계산: .../utg/utg.json -> .../json/app_memory.json
          // Windows/Unix 경로 구분자 모두 고려 (서버 모드는 \도 올 수 있음)
          const sep = item.path.includes('\\') ? '\\' : '/';
          const parts = item.path.split(sep);
          if (parts.length >= 2) {
            parts.splice(-2, 2, 'json', 'app_memory.json');
            const memoryPath = parts.join(sep);
            
            const mRes = await axios.get(`/api/read-json?path=${encodeURIComponent(memoryPath)}`);
            mainData.app_memory = mRes.data;
          }
        } catch (e) {
          console.warn('app_memory.json 로드 실패:', e);
        }
      }

      onFileSelect(mainData, item.path, null);
    } catch (err) {
      setError('JSON 파일을 읽을 수 없습니다: ' + (err.response?.data?.error ?? err.message));
    }
  };

  const handleSelect = handleLocalFileSelect;

  // ── 런 디렉토리 감지 + 로드 ──────────────────────────────────
  const isRunDir = items.length > 0 && detectRunInTree(items);

  const handleOpenAsRun = async () => {
    setError('');
    setLoading(true);
    try {
      const run = await loadRunFromTree(items, blobUrlMap, path);
      onRunLoad?.(run);
    } catch (err) {
      setError('런 로드 실패: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  // ── 렌더 ─────────────────────────────────────────────────────
  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-header">
        <span className="sidebar-title">파일 브라우저</span>
        {mode === 'local' && (
          <span className="sidebar-mode-badge">로컬</span>
        )}
      </div>

      <div className="path-input-group">
        <button className="path-btn-large" onClick={handleBrowse} disabled={loading}>
          {loading ? '데이터 로딩 중…' : '📂 분석 폴더 선택'}
        </button>

        {path && (
          <div className="current-path-info">
            <span className="path-label">현재 위치:</span>
            <span className="path-text">{path}</span>
          </div>
        )}

        {isRunDir && (
          <button
            className="path-btn-large run-open-btn"
            onClick={handleOpenAsRun}
            disabled={loading}
            title="run_meta.json이 감지됨. 런 대시보드로 엽니다."
          >
            🚀 이 런 열기 (Run Dashboard)
          </button>
        )}

        {error && <div className="path-error">⚠ {error}</div>}
      </div>

      <input
        ref={fileInputRef}
        type="file"
        // eslint-disable-next-line react/no-unknown-property
        webkitdirectory=""
        multiple
        style={{ display: 'none' }}
        onChange={handleFileInput}
      />

      <div className="file-tree">
        {items.length > 0 ? (
          items.map(item => (
            <FileItem
              key={item.path}
              item={item}
              depth={0}
              onSelect={handleSelect}
              selectedFile={selectedFile}
              mode={mode}
            />
          ))
        ) : (
          !loading && (
            <div className="file-tree-empty">
              분석할 폴더를 선택해주세요
            </div>
          )
        )}
      </div>
    </aside>
  );
}