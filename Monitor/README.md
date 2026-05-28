# IPG Monitor - 사용 설명서

## 개요

**IPG Monitor**는 IoT Packet Generator의 UI Transition 데이터를 시각화하는 모니터링 웹사이트입니다.  
JSON 파일을 선택하면 화면(Screen) 간의 전환(Transition)을 인터랙티브 그래프로 확인할 수 있습니다.

---

## 1. 실행 방법

터미널 두 개를 열어 각각 실행하세요.

**터미널 1 — 백엔드 서버**
```bash
cd d:\IoTPacketGenerator\IPG\Monitor\server
npm run dev
```
> 서버가 `http://localhost:3001` 에서 시작됩니다.

**터미널 2 — 프론트엔드**
```bash
cd d:\IoTPacketGenerator\IPG\Monitor\client
npm run dev
```
> 브라우저에서 **http://localhost:5173** 을 여세요.

---

## 2. JSON 파일 불러오기

1. 왼쪽 **사이드바**의 경로 입력창에 JSON 파일이 있는 **디렉토리 경로**를 입력합니다.
   - 예: `D:\MyApp\output`
2. **열기** 버튼을 클릭하거나 `Enter` 를 누릅니다.
3. 파일 목록에서 **`.json` 파일**을 클릭하면 그래프가 바로 로드됩니다.

> 하위 폴더는 클릭하면 펼쳐집니다.

---

## 3. JSON 데이터 형식

아래 구조의 JSON 파일을 지원합니다.

```json
{
  "nodes": [
    {
      "screen_id": "37017f3b56f7f925",
      "index": 0,
      "snapshots": ["000001"],
      "first_snapshot_id": "000001",
      "last_snapshot_id": "000001"
    }
  ],
  "edges": [
    {
      "src": "37017f3b56f7f925",
      "dst": "0c09d2b81a71cf9c",
      "event_type": "tap",
      "event_key": "tap@el_0047",
      "description": null,
      "src_snapshot_id": "000001",
      "dst_snapshot_id": "000002"
    }
  ]
}
```

| 필드 | 설명 |
|------|------|
| `nodes[].screen_id` | 화면 고유 ID |
| `nodes[].index` | 화면 순번 (#0, #1 …) |
| `nodes[].snapshots` | 이 화면에 해당하는 스냅샷 ID 목록 |
| `nodes[].first_snapshot_id` | 노드 카드에 표시할 대표 스냅샷 ID |
| `edges[].src` / `.dst` | 출발 / 도착 화면의 screen_id |
| `edges[].event_type` | 이벤트 종류 (`tap`, `swipe` 등) |
| `edges[].event_key` | 이벤트 상세 키 (엣지 레이블로 표시) |

---

## 4. 스냅샷 이미지 표시

JSON 파일과 같은 위치에 이미지 파일이 있으면 노드 카드 상단에 자동으로 표시됩니다.  
서버가 아래 경로를 순서대로 탐색합니다.

```
<JSON 파일 위치>/snapshots/<id>.png   ← 권장
<JSON 파일 위치>/screenshots/<id>.png
<JSON 파일 위치>/images/<id>.png
<JSON 파일 위치>/<id>.png
```

지원 확장자: `.png` `.jpg` `.jpeg` `.webp` `.bmp`

---

## 5. 그래프 조작

| 동작 | 방법 |
|------|------|
| 이동(Pan) | 빈 공간 드래그 |
| 줌 인/아웃 | 마우스 휠 / 좌하단 `+` `-` 버튼 |
| 화면 맞춤 | 좌하단 ⊡ 버튼 |
| 노드 이동 | 노드 드래그 |
| 레이아웃 변경 | 우상단 **좌→우 / 위→아래** 버튼 |
| 전체 보기 | 우하단 미니맵에서 위치 확인 |

---

## 6. 화면 구성

```
┌──────────────────────────────────────────────┐
│  ◀  IPG Monitor  v1.0          Screens  5    │  ← 헤더
│                                Transitions 5 │
├─────────────┬────────────────────────────────┤
│ 파일 브라우저│                                │
│             │   #0 ──tap──▶ #1 ──tap──▶ #2  │
│ [경로 입력] │              ↕                  │  ← 그래프 영역
│ [열기]      │          #3 ◀──── #2 ────▶ #4  │
│             │                                │
│ 📋 data.json│  [레이아웃] [통계]  [미니맵]   │
└─────────────┴────────────────────────────────┘
```

---

## 6.5. Run Dashboard (런 디렉토리 뷰어)

`run_meta.json`이 있는 **런 출력 디렉토리**(예: `outputs_APK/<App>/<timestamp>/`)를 폴더로 선택하면 사이드바에 **🚀 이 런 열기** 버튼이 활성화됩니다. 클릭하면 5개 탭이 있는 Run Dashboard가 열립니다.

| 탭 | 내용 |
|---|---|
| **요약** | `run_meta.json` 기반 통계 타일(unique/total screens, node_loop, packet events, duration 등), 종료 사유, 기기/앱 정보, 화면 방문 분포 바, 주요 설정(detection mode, scroll overlap, screen match threshold) |
| **화면** | 좌측: 화면 목록(id·activity·snap 수·scroll chips). 우측: 선택된 화면의 detail — window_id/activity, 화면-단위 스크롤 메모리, **스냅샷 갤러리(전체 스냅샷)**, elements 테이블(executed_events·element별 swipe_directions_tried/exhausted) |
| **그래프** | `app_memory` + `screen_memory`로 구성한 transition graph (기존 TransitionGraph 재사용) |
| **패킷** | `packet_memory.json` 기반 분석 뷰. 좌측: screen별 TX/RX 집계 (events 수, snapshot 수, tx/rx packets·bytes, 총 bytes 막대). 우측: 선택된 screen에서 **어떤 event 트리거(tap/swipe@element)가 어느 snapshot(파일명)에서 패킷을 발생시켰는지** 표로 drill-down. 같은 (screen_id, event_key)가 여러 snapshot에서 발생했어도 각각 별도 행으로 보존되어, 통합된 screen_id 내에서도 snapshot 단위 측정값이 사라지지 않습니다. `app_memory`와 매칭해 element의 text/class/resource_id를 함께 표시하고 event_type · snapshot 필터, 검색, 정렬(TX/RX pkt·bytes·총합) 지원. **행을 클릭하면 그 행의 `snapshot_id`에 해당하는 스냅샷 위에 element `bbox`가 강조되어** 표시되고, swipe 이벤트는 방향 화살표(↑↓←→)가 함께 그려집니다 (ESC 또는 배경 클릭으로 닫기) |
| **로그** | `runtime.log` 인라인 뷰어. 필터: 전체 / SCROLL / EXECUTOR / A11Y / WARN·ERROR. 자유 검색 박스, 색상별 분류, 라인 카운트 표시 |

기존 단일 JSON 그래프 뷰는 그대로 유지됩니다 (런 디렉토리가 아닌 폴더를 열거나, JSON 파일을 직접 클릭).

서버 측에는 다음 엔드포인트도 함께 추가되어 있어 절대 경로 기반 자동화에서도 활용할 수 있습니다:
`/api/run/detect`, `/api/run/meta`, `/api/run/app-memory`, `/api/run/screen-memory`, `/api/run/packet-memory`, `/api/run/log?filter=<scroll|executor|a11y|warning|all>`, `/api/run/snapshot?id=<snapshotId>`.

---

## 7. 샘플 데이터

테스트용 샘플 파일이 제공됩니다.

```
d:\IoTPacketGenerator\IPG\Monitor\sample_data\transitions.json
```

사이드바 경로 입력창에 `D:\IoTPacketGenerator\IPG\Monitor\sample_data` 를 입력 후 열기를 클릭하면 바로 확인할 수 있습니다.
