export default function SummaryTab({ run }) {
  const meta = run?.meta;
  if (!meta) {
    return <div className="run-empty">run_meta.json을 읽지 못했습니다.</div>;
  }

  const s = meta.summary || {};
  const d = meta.device || {};
  const a = meta.app || {};
  const e = meta.experiment || {};

  const fmtDuration = (sec) => {
    if (sec == null) return '-';
    const m = Math.floor(sec / 60);
    const r = Math.round(sec - m * 60);
    return m > 0 ? `${m}m ${r}s` : `${r}s`;
  };

  const tile = (label, value, accent) => (
    <div className={`stat-tile ${accent ? `stat-tile-${accent}` : ''}`}>
      <div className="stat-tile-label">{label}</div>
      <div className="stat-tile-value">{value ?? '-'}</div>
    </div>
  );

  return (
    <div className="run-tab-content summary-tab">
      <section className="summary-section">
        <h3>실행 요약</h3>
        <div className="stat-grid">
          {tile('unique screens', s.unique_screen_count, 'accent')}
          {tile('total detections', s.total_screen_count)}
          {tile('node loops', s.node_loop_count, s.node_loop_count ? 'warning' : 'success')}
          {tile('packet events', s.packet_event_count)}
          {tile('app restarts', s.app_restart_count)}
          {tile('foreground recovers', s.foreground_recover_count)}
          {tile('excluded escapes', s.excluded_escape_count)}
          {tile('duration', fmtDuration(meta.duration_sec))}
        </div>
        <div className="terminal-reason">
          종료 사유: <code>{s.terminal_reason ?? '-'}</code>
        </div>
      </section>

      <section className="summary-section">
        <h3>대상</h3>
        <div className="kv-grid">
          <div><span className="k">앱</span> {a.app_name} <code>{a.package}</code></div>
          <div><span className="k">버전</span> {a.version} ({a.version_code})</div>
          <div><span className="k">기기</span> {d.manufacturer} {d.model} · Android {d.version} (SDK {d.sdk})</div>
          <div><span className="k">화면</span> {d.screen_width} × {d.screen_height}</div>
          <div><span className="k">시리얼</span> <code>{d.serial}</code></div>
          <div><span className="k">시작</span> <code>{meta.start_ts}</code></div>
          <div><span className="k">종료</span> <code>{meta.end_ts}</code></div>
        </div>
      </section>

      <section className="summary-section">
        <h3>화면 방문 분포</h3>
        <VisitDistribution visitCount={s.screen_visit_count} />
      </section>

      <section className="summary-section">
        <h3>주요 설정</h3>
        <div className="kv-grid">
          <div><span className="k">detection mode</span> <code>{e?.detection?.ui_detection_mode}</code></div>
          <div><span className="k">screen_id kind</span> <code>{e?.screen_id?.kind}</code> · threshold <code>{e?.screen_id?.threshold ?? '-'}</code> · match_threshold <code>{e?.screen_id?.match_threshold ?? '-'}</code></div>
          <div><span className="k">scroll</span> overlap <code>{e?.traversal?.scroll_overlap_ratio ?? '-'}</code> · duration <code>{e?.traversal?.scroll_swipe_duration_ms ?? '-'}ms</code> · settle <code>{e?.traversal?.swipe_settle_ms ?? '-'}ms</code></div>
          <div><span className="k">limits</span> loop <code>{e?.traversal?.loop_threshold}</code> · same-screen <code>{e?.traversal?.same_screen_threshold}</code> · back <code>{e?.traversal?.back_threshold}</code> · max-consec-scrolls <code>{e?.traversal?.max_consecutive_scrolls ?? '-'}</code></div>
        </div>
      </section>
    </div>
  );
}

function VisitDistribution({ visitCount }) {
  if (!visitCount) return <div className="run-muted">데이터 없음</div>;
  const entries = Object.entries(visitCount).sort((a, b) => b[1] - a[1]);
  const max = entries[0]?.[1] || 1;
  return (
    <div className="visit-bars">
      {entries.map(([sid, n]) => (
        <div key={sid} className="visit-row">
          <code className="visit-sid">{sid.slice(0, 12)}</code>
          <div className="visit-bar-track">
            <div className="visit-bar-fill" style={{ width: `${(n / max) * 100}%` }} />
          </div>
          <span className="visit-n">{n}</span>
        </div>
      ))}
    </div>
  );
}
