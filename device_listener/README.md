# IPG Device Listener (APK)

`AccessibilityService` 한 개만 들어 있는 작은 안드로이드 앱. 디바이스에서 발생하는 accessibility 이벤트를 **logcat 태그 `IPG_EVT`** 로 JSON 한 줄씩 흘려보낸다. IPG 본체(`src/`)는 손대지 않고, 필요할 때 `adb logcat -s IPG_EVT:I` 만 추가로 tail해서 소비한다.

## 무엇을 emit하나

| 이벤트 타입 | 키 필드 |
|---|---|
| `WINDOW_STATE_CHANGED` | `pkg`, `class`, `text` |
| `WINDOW_CONTENT_CHANGED` | `pkg`, `class`, `change` (SUBTREE\|TEXT\|DESC\|PANE_*\|STATE) — 같은 패키지 300ms 디바운스 |
| `VIEW_SCROLLED` | `scrollX/Y`, `fromIndex`, `toIndex`, `itemCount`, `scrollDeltaX/Y` (API 28+), `maxScrollX/Y` (API 28+) |
| `NOTIFICATION_STATE_CHANGED` | `class`, `text`, `isToast` |
| `VIEW_CLICKED` | `pkg`, `class`, `text` |

logcat 라인 예시:
```
01-01 12:00:00.000 12345 12345 I IPG_EVT: {"ts":1715000000000,"type":"VIEW_SCROLLED","pkg":"com.hejhome.app","class":"androidx.recyclerview.widget.RecyclerView","scrollY":420,"fromIndex":3,"toIndex":8,"itemCount":42,"maxScrollY":2100}
```

## 빌드

### Android Studio
`device_listener/` 디렉토리를 열고 `app` 모듈을 Run/Build. 출력: `app/build/outputs/apk/debug/app-debug.apk`.

### CLI (Gradle 설치돼 있을 때)
```
cd device_listener
gradle wrapper
./gradlew :app:assembleDebug
```

## 설치 + 활성화

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk

# accessibility service 활성화 (모든 dev 디바이스/에뮬레이터에서 동작)
adb shell settings put secure enabled_accessibility_services \
  dev.ipg.listener/dev.ipg.listener.IpgAccessibilityService
adb shell settings put secure accessibility_enabled 1
```

일부 OEM 펌웨어는 `enabled_accessibility_services` 를 secure settings로 못 쓰게 막아둔다. 그 경우 폰에서 **설정 → 접근성 → 설치된 앱 → IPG Accessibility Listener** 를 토글하면 된다. 앱 실행 후 `Open Accessibility Settings` 버튼이 같은 화면을 띄워준다.

## 동작 확인

```bash
adb logcat -c
adb logcat -s IPG_EVT:I
```

서비스가 살아있으면 첫 줄로 `{"type":"SERVICE_CONNECTED",...,"session":"yyyyMMdd_HHmmss","dumpsDir":"..."}` 가 보인다. 폰에서 아무 앱이나 켜고 스크롤하면 `VIEW_SCROLLED` 가 흘러나온다.

## UI 계층 자동 덤프 + 호스트 다운로드

서비스가 모든 a11y 이벤트마다 `rootInActiveWindow` 트리를 walk해서 **uiautomator 호환 XML** 로 디바이스에 저장한다 (`/sdcard/Android/data/dev.ipg.listener/files/dumps/<session>/`). XML 옆에 같은 이름의 `.json` 사이드카가 함께 떨어지며, 이 파일에는 트리거 이벤트 메타(type, ts, pkg, scrollX/Y, change flags 등)와 `seq`/`session` 이 들어 있다. CONTENT_CHANGED 는 `(pkg, class, contentChangeTypes)` 가 같으면 300ms 디바운스 — 다른 module/flag 면 즉시 덤프.

**변경 위치 추적**: 가능한 모든 이벤트에서 `event.source` 메타(bounds, resource-id, class, 현재 text/contentDesc)를 사이드카 JSON 의 `source` 필드에 함께 저장한다. CONTENT_CHANGED 의 경우 어느 노드가 어떻게 바뀌었는지 직접 식별 가능. "이전 값" 은 직전 seq 의 XML 덤프에서 같은 노드를 찾아 비교하면 된다 (별도 캐시 없음).

**스크린샷**: API 30+ 디바이스에선 `AccessibilityService.takeScreenshot()` 으로 APK가 직접 캡처(50ms 이내, 단 ~1Hz rate-limit). API 30 미만에선 호스트 스크립트가 `adb shell screencap` 으로 캡처(200~500ms 지연). 어느 쪽이든 PNG는 XML/JSON 과 같은 baseName 으로 저장.

## 패키지 필터 + IPG 포맷 출력

디바이스에 `config.json` 을 올려두면 그 안의 `packages` 리스트에 든 패키지의 이벤트만 처리하고, 저장 형식이 IPG 의 `outputs/<app>/<session>/{xml,screen,json}/<seq>.{xml,png,json}` 와 같아진다. config 가 없으면 기존 flat 동작 유지.

```bash
adb push device_listener/config.example.json /sdcard/Android/data/dev.ipg.listener/files/config.json
```

`config.example.json`:
```json
{
  "appLabel": "Hejhome",
  "packages": ["com.goqual"]
}
```

서비스는 매 이벤트마다 modtime 캐시로 config 를 lazy-reload — `adb push` 로 갱신하면 다음 이벤트부터 즉시 반영. 빈 packages 리스트 또는 파일 삭제 시 필터 해제.

호스트 측 출력 위치 (collector 가 자동 분기):
- IPG 모드: `outputs_APK/<appLabel>/<session>/{xml,screen,json}/<seq>.{xml,png,json}`
- flat 모드: `device_listener/captures/<session>/<basename>.{xml,json,png}`

## Monitor 연동 (UTG 자동 생성)

collector 를 **Ctrl+C 로 종료** 하면, IPG 모드로 받은 모든 세션 디렉토리에 대해 [device_listener/host/build_utg.py](device_listener/host/build_utg.py) 가 자동으로 호출되어 두 파일을 만든다:
- `<session>/screen/utg.json` — Monitor 가 처음 여는 그래프 데이터
- `<session>/json/app_memory.json` — Monitor Sidebar 가 자동 로드하는 element 데이터

Monitor (`Monitor/server` + `Monitor/client`) 를 띄운 뒤 사이드바 경로 입력창에 `outputs_APK/<appLabel>/<session>/screen` 을 넣고 `utg.json` 클릭하면:
- **노드 카드**: 각 화면의 snapshot PNG (같은 디렉토리에서 자동 매칭)
- **bbox 오버레이**: app_memory.json 의 element 들이 화면 위에 박스로 표시
- **Trigger mode**: edge `event_key` 가 가리키는 element 만 강조 (어떤 element가 화면 전환을 일으켰는지)
- **Diff mode** (노드 2개 선택): 두 화면의 element 를 resource_id → class+text → class+bbox 순으로 매칭해서 added/removed/modified/unchanged 표시

수동으로 다시 빌드하려면:
```bash
python device_listener/host/build_utg.py outputs_APK/Hejhome/<session>
```

알고리즘:
- screen_id = SHA1(정규화 XML)[:16] — `focused`/`selected`/`checked` 같은 휘발성 attr 제거
- 같은 screen_id 가 연속이면 한 노드의 snapshots 에 누적
- screen_id 가 바뀌는 순간이 edge — 직전 5개 이벤트 안의 가장 최근 `VIEW_CLICKED`/`VIEW_SCROLLED` 가 edge label
- element_id 는 XML 깊이 우선 순회 순서대로 `el_0000`, `el_0001` ... 같은 화면(같은 XML 해시) 내에서 안정적
- edge 의 `event_key` 는 trigger event 의 `source.resourceId` 또는 `source.bounds` 를 source 화면의 element 와 매칭하여 `tap@el_0023` 형태로 기록 — 매칭 실패 시 `auto@<TYPE>`
- **주의**: `adb shell input tap` 은 raw touch 라 `VIEW_CLICKED` 안 발생 → trigger mode 가 빈다. 손가락 탭이나 `monkey` 로 진짜 클릭 이벤트를 만들어야 element 매칭이 동작.

각 덤프 직후 logcat 출력:
- `DUMP_WRITTEN` — XML/JSON 작성 완료. `screenshotMode`(`apk`|`host`), `outputMode`(`ipg`|`flat`), `appLabel`, `xml`, `meta` 필드 포함.
- `DUMP_SCREENSHOT` — APK가 PNG 작성 완료 (API 30+ 만)
- `DUMP_SCREENSHOT_FAILED` — rate-limit 등 실패 시

## 호스트 collector

호스트는 logcat tail해서 위 라인이 보일 때마다 `adb pull` + 디바이스 원본 삭제. Ctrl+C 종료 시 IPG 모드 세션 마다 UTG 자동 빌드.

```bash
python device_listener/host/dump_collector.py
# 옵션:
#   --keep                디바이스 원본 안 지움
#   --no-screenshots      스크린샷 캡처/pull 스킵
#   --no-utg              종료 시 UTG 자동 빌드 안 함
#   --include-backlog     이미 logcat 버퍼에 있던 이벤트도 처리
#   --ipg-out DIR         IPG 모드 root 변경 (기본: outputs_APK)
#   --flat-out DIR        flat 모드 root 변경 (기본: device_listener/captures)
```

## IPG에서 소비하는 예 (참고용 — 본체 변경 없음)

```python
import json
import subprocess

proc = subprocess.Popen(
    ["adb", "logcat", "-s", "IPG_EVT:I"],
    stdout=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    errors="ignore",
)

for line in proc.stdout:
    idx = line.find("IPG_EVT: ")
    if idx == -1:
        continue
    try:
        evt = json.loads(line[idx + len("IPG_EVT: "):].strip())
    except json.JSONDecodeError:
        continue
    # evt: {"ts":..., "type":"VIEW_SCROLLED", "pkg":..., ...}
    print(evt)
```

본체에 묶고 싶을 때만 위 코드를 별도 스레드로 돌려서 큐에 넣고, 메인 loop에서 `step_count` 시점과 매칭하는 방식이 깔끔하다.

## 제거

```bash
adb shell settings put secure enabled_accessibility_services ""
adb shell settings put secure accessibility_enabled 0
adb uninstall dev.ipg.listener
```

## 한계 / 메모

- **CONTENT_CHANGED는 firehose** 라서 디바이스 측에서 패키지당 300ms 디바운스를 둠 (`CONTENT_DEBOUNCE_MS`). 더 빠르게 받고 싶으면 [IpgAccessibilityService.kt](app/src/main/java/dev/ipg/listener/IpgAccessibilityService.kt)의 상수 조정.
- **Canvas / OpenGL / SurfaceView 콘텐츠**는 view tree 밖이라 어떤 이벤트도 안 옴 — 이건 안드로이드 자체 한계.
- **Toast text가 Android 12+ 에서 비어 오는 경우**: 시스템 `NotificationService` 로그는 redact되지만, 이 서비스는 직접 AccessibilityEvent를 받아서 logcat에 자기 태그로 찍기 때문에 redact 영향을 받지 않는다.
- 이 앱은 INTERNET 권한이 없다. 외부로 송신 안 함. logcat 한 채널이 전부.
