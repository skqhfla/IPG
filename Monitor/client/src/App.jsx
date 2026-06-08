import { useState, useCallback } from 'react';
import Header from './components/Header.jsx';
import Sidebar from './components/Sidebar.jsx';
import TransitionGraph from './components/TransitionGraph.jsx';
import RunDashboard from './views/RunDashboard.jsx';
import AdbControlPanel from './views/AdbControlPanel.jsx';
import LiveMonitor from './views/LiveMonitor.jsx';
import ScreenIdInspector from './views/ScreenIdInspector.jsx';
import './App.css';

export default function App() {
  const [graphData, setGraphData] = useState(null);
  const [currentJsonPath, setCurrentJsonPath] = useState('');
  const [blobUrlMap, setBlobUrlMap] = useState({});
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [runData, setRunData] = useState(null);
  const [showControl, setShowControl] = useState(false);
  const [showLive, setShowLive] = useState(false);
  const [showSid, setShowSid] = useState(false);
  // Sidebar 가 서버 모드에서 run 폴더를 골랐을 때 Inspector 가 그 절대경로를
  // 받아 쓰도록 공유 state. Inspector 내부 dropdown 과 동기화.
  const [inspectorDir, setInspectorDir] = useState(
    () => localStorage.getItem('sid_inspect_run_dir') || ''
  );

  const handleSendToInspector = useCallback((absPath) => {
    if (!absPath) return;
    setInspectorDir(absPath);
    localStorage.setItem('sid_inspect_run_dir', absPath);
    setShowSid(true);
    setShowControl(false);
    setShowLive(false);
  }, []);

  // 기기 제어에서 dump 한 XML(+ png) 을 Inspector 에 한 번만 전달.
  // 매번 새 dump 마다 객체가 새로 생성되므로 useEffect 의 deps 로 1회만 발동.
  // {xml, pngDataUrl, label, source, ts}
  const [inspectorDump, setInspectorDump] = useState(null);
  const handleSendDumpToInspector = useCallback((dump) => {
    if (!dump || !dump.xml) return;
    setInspectorDump({ ...dump, ts: Date.now() });
    setShowSid(true);
    setShowControl(false);
    setShowLive(false);
  }, []);

  const handleFileSelect = useCallback((data, filePath, blobUrls) => {
    setGraphData(data);
    setCurrentJsonPath(filePath ?? '');
    setBlobUrlMap(blobUrls ?? {});
    setRunData(null);  // 그래프 모드 진입 시 런 대시보드는 해제
  }, []);

  const handleRunLoad = useCallback((run) => {
    setRunData(run);
    setGraphData(null);
    setCurrentJsonPath('');
  }, []);

  return (
    <div className="app">
      <Header
        graphData={graphData}
        sidebarCollapsed={sidebarCollapsed}
        onToggleSidebar={() => setSidebarCollapsed(v => !v)}
        controlActive={showControl}
        onToggleControl={() => { setShowControl(v => !v); setShowLive(false); setShowSid(false); }}
        liveActive={showLive}
        onToggleLive={() => { setShowLive(v => !v); setShowControl(false); setShowSid(false); }}
        sidActive={showSid}
        onToggleSid={() => { setShowSid(v => !v); setShowControl(false); setShowLive(false); }}
      />
      <div className="app-body">
        <Sidebar
          onFileSelect={handleFileSelect}
          onRunLoad={handleRunLoad}
          onSendToInspector={handleSendToInspector}
          collapsed={sidebarCollapsed}
        />
        <main className="main-content">
          {showSid ? (
            <ScreenIdInspector
              externalDir={inspectorDir}
              externalDump={inspectorDump}
              onClearExternalDump={() => setInspectorDump(null)}
            />
          ) : showLive ? (
            <LiveMonitor />
          ) : showControl ? (
            <AdbControlPanel onSendToInspector={handleSendDumpToInspector} />
          ) : runData ? (
            <RunDashboard run={runData} />
          ) : graphData ? (
            <TransitionGraph data={graphData} jsonPath={currentJsonPath} blobUrlMap={blobUrlMap} />
          ) : (
            <div className="empty-state">
              <div className="empty-icon">🗂️</div>
              <h2>UI Transition Graph</h2>
              <p>
                사이드바에서 <b>분석 폴더 선택</b>으로 폴더를 연 뒤,<br />
                JSON 파일을 클릭하거나 <b>런 디렉토리</b>면 <b>🚀 이 런 열기</b>를 누르세요.
              </p>
              <div className="empty-hint">
                💡 run_meta.json이 있으면 Summary / Screens / Graph / Logs 탭이 있는 Run Dashboard로 열립니다.
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
