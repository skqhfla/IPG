import { useMemo, useState } from 'react';

const FILTERS = [
  { key: 'all', label: '전체' },
  { key: 'scroll', label: 'SCROLL' },
  { key: 'executor', label: 'EXECUTOR' },
  { key: 'a11y', label: 'A11Y' },
  { key: 'warning', label: 'WARN/ERROR' },
];

function matches(line, key) {
  switch (key) {
    case 'scroll':
      return (
        line.includes('[SCROLL]') ||
        line.includes('[POLICY]') ||
        (line.includes('[A11Y]') && line.includes('VIEW_SCROLLED')) ||
        (line.includes('[EXECUTOR]') && line.includes(' swipe '))
      );
    case 'executor': return line.includes('[EXECUTOR]');
    case 'a11y':     return line.includes('[A11Y]');
    case 'warning':  return line.includes('[WARNING]') || line.includes('[ERROR]');
    case 'all':
    default:         return true;
  }
}

function classify(line) {
  if (line.includes('[ERROR]'))    return 'log-error';
  if (line.includes('[WARNING]'))  return 'log-warning';
  if (line.includes('[SCROLL]'))   return 'log-scroll';
  if (line.includes('[POLICY]'))   return 'log-policy';
  if (line.includes('[EXECUTOR]')) return 'log-exec';
  if (line.includes('[A11Y]'))     return 'log-a11y';
  return '';
}

export default function LogsTab({ run }) {
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');

  const allLines = useMemo(
    () => (run?.logText || '').split(/\r?\n/),
    [run?.logText]
  );

  const filtered = useMemo(() => {
    let out = allLines.filter(l => matches(l, filter));
    if (query.trim()) {
      const q = query.toLowerCase();
      out = out.filter(l => l.toLowerCase().includes(q));
    }
    return out;
  }, [allLines, filter, query]);

  if (!run?.logText) {
    return <div className="run-empty">runtime.log 없음</div>;
  }

  return (
    <div className="run-tab-content logs-tab">
      <div className="log-toolbar">
        <div className="log-filter-group">
          {FILTERS.map(f => (
            <button
              key={f.key}
              className={`log-filter-btn ${filter === f.key ? 'active' : ''}`}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          className="log-search"
          placeholder="검색…"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        <div className="log-count">
          {filtered.length.toLocaleString()} / {allLines.length.toLocaleString()} lines
        </div>
      </div>

      <div className="log-view">
        {filtered.map((line, i) => (
          <div key={i} className={`log-line ${classify(line)}`}>
            {line}
          </div>
        ))}
        {filtered.length === 0 && <div className="run-muted">표시할 라인 없음</div>}
      </div>
    </div>
  );
}
