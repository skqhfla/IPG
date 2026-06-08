// XML dump 의 <hierarchy ...> 루트 속성을 client-side 에서 즉시 추출.
// 서버 inspect 응답을 기다리지 않고도 batter / 메타 행에 표시할 수 있게 한다.
// 정식 XML 파서 대신 정규식만 쓰는 이유: 결과가 큰 XML 일 수 있고 root 한 줄만
// 보면 되므로 cost 가 낮다.
export function parseHierarchyMeta(xmlText) {
  if (!xmlText || typeof xmlText !== 'string') return null;
  const m = xmlText.match(/<hierarchy\b([^>]*)>/);
  if (!m) return null;
  const attrs = m[1];
  const get = (src, name) => {
    const a = src.match(new RegExp(`\\b${name}\\s*=\\s*"([^"]*)"`));
    return a ? a[1] : null;
  };
  const rotRaw = get(attrs, 'rotation');
  const widRaw = get(attrs, 'window-id');
  let pkg = get(attrs, 'package');
  // 표준 uiautomator dump 는 <hierarchy> 에 package 가 없는 ROM 이 많다.
  // 서버가 dumpsys 로 inject 못 했으면 client 가 root <node ... package="..."> 폴백.
  if (!pkg) {
    const rootNode = xmlText.match(/<node\b([^>]*)>/);
    if (rootNode) pkg = get(rootNode[1], 'package');
  }
  return {
    package: pkg,
    activity: get(attrs, 'activity'),
    window_id: widRaw != null && /^\d+$/.test(widRaw) ? parseInt(widRaw, 10) : null,
    rotation: rotRaw != null && /^\d+$/.test(rotRaw) ? parseInt(rotRaw, 10) % 4 : 0,
  };
}

// activity 풀네임이 너무 길 때 끝부분만 표시.
export function shortActivity(act) {
  if (!act) return '-';
  return act.length > 40 ? '…' + act.slice(-37) : act;
}
