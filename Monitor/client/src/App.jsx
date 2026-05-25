import { useState, useCallback } from 'react';
import Header from './components/Header.jsx';
import Sidebar from './components/Sidebar.jsx';
import TransitionGraph from './components/TransitionGraph.jsx';
import RunDashboard from './views/RunDashboard.jsx';
import './App.css';

export default function App() {
  const [graphData, setGraphData] = useState(null);
  const [currentJsonPath, setCurrentJsonPath] = useState('');
  const [blobUrlMap, setBlobUrlMap] = useState({});
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [runData, setRunData] = useState(null);

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
      />
      <div className="app-body">
        <Sidebar
          onFileSelect={handleFileSelect}
          onRunLoad={handleRunLoad}
          collapsed={sidebarCollapsed}
        />
        <main className="main-content">
          {runData ? (
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
