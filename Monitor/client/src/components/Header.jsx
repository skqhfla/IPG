export default function Header({ graphData, sidebarCollapsed, onToggleSidebar, controlActive, onToggleControl, liveActive, onToggleLive, sidActive, onToggleSid }) {
  const nodeCount = graphData?.nodes?.length ?? 0;
  const edgeCount = graphData?.edges?.length ?? 0;

  return (
    <header className="header">
      <button className="sidebar-toggle" onClick={onToggleSidebar} title="사이드바 토글">
        {sidebarCollapsed ? '▶' : '◀'}
      </button>

      <div className="header-logo">
        <div className="header-logo-icon">📡</div>
        <div>
          <div className="header-title">IPG Monitor</div>
          <div className="header-subtitle">UI Transition Analyzer</div>
        </div>
      </div>

      <div className="header-divider" />
      <span className="header-badge">v1.0</span>

      <div className="header-spacer" />

      <button
        className={`header-control-btn ${liveActive ? 'active' : ''}`}
        onClick={onToggleLive}
        title="라이브 모니터 (화면/이벤트/패킷/XML)"
      >
        📺 라이브 모니터
      </button>

      <button
        className={`header-control-btn ${controlActive ? 'active' : ''}`}
        onClick={onToggleControl}
        title="기기 제어 패널 (adb)"
      >
        🎮 기기 제어
      </button>

      <button
        className={`header-control-btn ${sidActive ? 'active' : ''}`}
        onClick={onToggleSid}
        title="Screen ID 검사 (XML → screen_id + 매칭 trace)"
      >
        🔍 Screen ID
      </button>

      {graphData && (
        <div className="header-stats">
          <div className="stat-item">
            <span className="stat-value">{nodeCount}</span>
            <span className="stat-label">Screens</span>
          </div>
          <div className="header-divider" />
          <div className="stat-item">
            <span className="stat-value">{edgeCount}</span>
            <span className="stat-label">Transitions</span>
          </div>
        </div>
      )}
    </header>
  );
}
