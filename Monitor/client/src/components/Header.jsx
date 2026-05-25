export default function Header({ graphData, sidebarCollapsed, onToggleSidebar }) {
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
