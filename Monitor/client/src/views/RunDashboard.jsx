import { useState } from 'react';
import './run-dashboard.css';
import SummaryTab from './SummaryTab.jsx';
import ScreensTab from './ScreensTab.jsx';
import LogsTab from './LogsTab.jsx';
import GraphTab from './GraphTab.jsx';
import PacketsTab from './PacketsTab.jsx';

const TABS = [
  { key: 'summary', label: '요약' },
  { key: 'screens', label: '화면' },
  { key: 'graph',   label: '그래프' },
  { key: 'packets', label: '패킷' },
  { key: 'logs',    label: '로그' },
];

export default function RunDashboard({ run }) {
  const [tab, setTab] = useState('summary');

  if (!run) return null;

  return (
    <div className="run-dashboard">
      <nav className="run-tabs">
        <span className="run-title">📁 {run.runName}</span>
        <div className="run-tab-bar">
          {TABS.map(t => (
            <button
              key={t.key}
              className={`run-tab-btn ${tab === t.key ? 'active' : ''}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </nav>

      <div className="run-tab-body">
        {tab === 'summary' && <SummaryTab run={run} />}
        {tab === 'screens' && <ScreensTab run={run} />}
        {tab === 'graph'   && <GraphTab   run={run} />}
        {tab === 'packets' && <PacketsTab run={run} />}
        {tab === 'logs'    && <LogsTab    run={run} />}
      </div>
    </div>
  );
}
