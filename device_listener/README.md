# IPG Device Listener (Instrumented Test APK)

작은 안드로이드 instrumentation test 한 개. `am instrument -w` 로 띄우면 `UiAutomation` 으로 디바이스의 accessibility 이벤트를 받아서 **logcat 태그 `IPG_EVT`** 로 JSON 한 줄씩 흘려보낸다. IPG 본체(`src/`)는 손대지 않고, 필요할 때 `adb logcat -s IPG_EVT:I` 만 추가로 tail해서 소비한다.

## 왜 AccessibilityService 가 아니라 instrumented test 인가

원래는 일반 `AccessibilityService` 였는데, **Samsung Galaxy / One UI 의 Knox 정책이 sideloaded APK 의 accessibility binding 을 silently 거부**해서 어떤 토글로도 동작 못 하는 경우가 있다 (`dumpsys accessibility` 에 `Bound services:{}` 인 상태). Maestro 가 쓰는 패턴 그대로 — instrumentation 으로 `UiAutomation` API 를 잡으면:

- 사용자가 폰에서 토글 안 해도 됨
- `enabled_accessibility_services` 설정 무관
- Knox `isChangeAllowed()` 검사 안 거침
- `BIND_ACCESSIBILITY_SERVICE` 권한 검사 없음
- 같은 `AccessibilityEvent`, 같은 `rootInActiveWindow` 받음

대신 **`am instrument` 가 호스트에서 띄워줘야** 한다 — 그래서 `dump_collector.py` 가 시작 시 자동으로 띄우고 종료 시 죽인다.

## 무엇을 emit하나

| 이벤트 타입 | 키 필드 |
|---|---|
| `WINDOW_STATE_CHANGED` | `pkg`, `class`, `text` |
| `WINDOW_CONTENT_CHANGED` | `pkg`, `class`, `change` (SUBTREE\|TEXT\|DESC\|PANE_*\|STATE) — 같은 패키지 300ms 디바운스 |
| `VIEW_SCROLLED` | `scrollX/Y`, `fromIndex`, `toIndex`, `itemCount`, `scrollDeltaX/Y`, `maxScrollX/Y` |
| `NOTIFICATION_STATE_CHANGED` | `class`, `text`, `isToast` |
| `VIEW_CLICKED` | `pkg`, `class`, `text` |

logcat 라인 예시:
```
01-01 12:00:00.000 12345 12345 I IPG_EVT: {"ts":1715000000000,"type":"VIEW_SCROLLED","pkg":"com.hejhome.app","class":"androidx.recyclerview.widget.RecyclerView","scrollY":420,"fromIndex":3,"toIndex":8,"itemCount":42,"maxScrollY":2100}
```

## 빌드

두 개의 APK 가 필요하다 — main app (`app-debug.apk`) + instrumented test (`app-debug-androidTest.apk`).

### Android Studio
`device_listener/` 디렉토리를 열고:
- `app` 모듈 Run/Build → `app-debug.apk` 생성
- Build → Build → Build APK(s) → `assembleDebugAndroidTest` → `app-debug-androidTest.apk` 생성

### CLI
```
cd device_listener
gradle :app:assembleDebug :app:assembleDebugAndroidTest
```

산출물:
- `app/build/outputs/apk/debug/app-debug.apk`
- `app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk`

## 설치

```bash
cd device_listener
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
```

**활성화 단계 없음.** 토글, Settings UI, Knox 동의 — 어느 것도 필요 없다.

## 실행

호스트 collector 가 자동으로 instrumentation 을 띄우고 dump 를 수집한다:

```bash
python device_listener/host/dump_collector.py
```

기동 직후 logcat 에 `SERVICE_CONNECTED` 가 한 줄 떨어지면 정상 — 그 뒤로 폰에서 아무 앱이나 켜고 스크롤하면 `VIEW_SCROLLED`, `DUMP_WRITTEN` 등이 흘러나온다. Ctrl+C 로 종료하면 instrumentation 도 같이 죽이고, IPG 모드 세션은 UTG 가 자동 빌드된다.

수동 기동을 원하면 (collector 따로 / instrument 따로):
```bash
# 터미널 A: instrumentation 직접
adb shell am instrument -w -m \
  -e class dev.ipg.listener.IpgInstrumentationTest#run \
  dev.ipg.listener.test/androidx.test.runner.AndroidJUnitRunner

# 터미널 B: collector 만 (instrument 시도 안 함)
python device_listener/host/dump_collector.py --no-instrument
```

## 동작 확인 (collector 안 띄우고 logcat 만 보고 싶을 때)

```bash
# 터미널 A
adb shell am instrument -w -m \
  -e class dev.ipg.listener.IpgInstrumentationTest#run \
  dev.ipg.listener.test/androidx.test.runner.AndroidJUnitRunner

# 터미널 B
adb logcat -c
adb logcat -s IPG_EVT:I
```

첫 줄로 `{"type":"SERVICE_CONNECTED",...,"session":"yyyyMMdd_HHmmss",...}` 가 보여야 한다.

## UI 계층 자동 덤프 + 호스트 다운로드

instrumentation 이 모든 a11y 이벤트마다 `UiAutomation.rootInActiveWindow` 트리를 walk 해서 **uiautomator 호환 XML** 로 디바이스에 저장한다 (`/sdcard/Android/data/dev.ipg.listener/files/dumps/<session>/` 또는 IPG 모드면 `captures/<app>/<session>/`). XML 옆에 같은 이름의 `.json` 사이드카가 함께 떨어지며, 이 파일에는 트리거 이벤트 메타(type, ts, pkg, scrollX/Y, change flags 등)와 `seq`/`session` 이 들어 있다. CONTENT_CHANGED 는 `(pkg, class, contentChangeTypes)` 가 같으면 300ms 디바운스 — 다른 module/flag 면 즉시 덤프.

**변경 위치 추적**: 가능한 모든 이벤트에서 `event.source` 메타(bounds, resource-id, class, 현재 text/contentDesc)를 사이드카 JSON 의 `source` 필드에 함께 저장한다. CONTENT_CHANGED 의 경우 어느 노드가 어떻게 바뀌었는지 직접 식별 가능. "이전 값" 은 직전 seq 의 XML 덤프에서 같은 노드를 찾아 비교하면 된다 (별도 캐시 없음).

**스크린샷**: `UiAutomation.takeScreenshot()` 으로 instrumentation process 가 직접 캡처 (~50ms, 안정적). API 30 이하 호스트 fallback 경로는 더 이상 필요 없음 (UiAutomation 은 모든 API 레벨에서 동작).

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

매 이벤트마다 modtime 캐시로 config 를 lazy-reload — `adb push` 로 갱신하면 다음 이벤트부터 즉시 반영. 빈 packages 리스트 또는 파일 삭제 시 필터 해제.

ConfigActivity (메인 앱 → "Edit Filter") 로 디바이스에서 직접 GUI 로 편집해도 된다.

호스트 측 출력 위치 (collector 가 자동 분기):
- IPG 모드: `outputs_APK/<appLabel>/<session>/{xml,screen,json}/<seq>.{xml,png,json}`
- flat 모드: `device_listener/captures/<session>/<basename>.{xml,json,png}`

## Monitor 연동 (UTG 자동 생성)

collector 를 **Ctrl+C 로 종료** 하면, IPG 모드로 받은 모든 세션 디렉토리에 대해 [device_listener/host/build_utg.py](device_listener/host/build_utg.py) 가 자동으로 호출되어 두 파일을 만든다:
- `<session>/screen/utg.json` — Monitor 가 처음 여는 그래프 데이터
- `<session>/json/app_memory.json` — Monitor Sidebar 가 자동 로드하는 element 데이터

Monitor (`Monitor/server` + `Monitor/client`) 를 띄운 뒤 사이드바 경로 입력창에 `outputs_APK/<appLabel>/<session>/screen` 을 넣고 `utg.json` 클릭하면:
- **노드 카드**: 각 화면의 snapshot PNG
- **bbox 오버레이**: app_memory.json 의 element 들이 화면 위에 박스로 표시
- **Trigger mode**: edge `event_key` 가 가리키는 element 만 강조
- **Diff mode** (노드 2개 선택): 두 화면의 element 를 resource_id → class+text → class+bbox 순으로 매칭

수동으로 다시 빌드하려면:
```bash
python device_listener/host/build_utg.py outputs_APK/Hejhome/<session>
```

각 덤프 직후 logcat 출력:
- `DUMP_WRITTEN` — XML/JSON 작성 완료. `screenshotMode=uiautomation`, `outputMode`(`ipg`|`flat`), `appLabel`, `xml`, `meta` 필드 포함.
- `DUMP_SCREENSHOT` — PNG 작성 완료
- `DUMP_SCREENSHOT_FAILED` — 실패 시 reason 포함

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
    print(evt)
```

본체에 묶고 싶을 때만 위 코드를 별도 스레드로 돌려서 큐에 넣고, 메인 loop에서 `step_count` 시점과 매칭하는 방식이 깔끔하다. (단, instrumentation 이 띄워져 있어야 — `dump_collector.py --no-instrument` 모드처럼 다른 곳에서 `am instrument` 실행 중이거나, 본체가 직접 띄워야 함.)

## 제거

```bash
adb uninstall dev.ipg.listener.test
adb uninstall dev.ipg.listener
```

## 한계 / 메모

- **instrumentation session 이 끊기면 listener 도 죽는다.** `dump_collector.py` 가 살아있는 동안만 동작. 본체 IPG 와 같이 묶어 쓰려면 본체가 listener 의 supervisor 역할을 해야 함 (Maestro 와 동일 패턴).
- **CONTENT_CHANGED는 firehose** 라서 디바이스 측에서 패키지당 300ms 디바운스를 둠 (`CONTENT_DEBOUNCE_MS`). 더 빠르게 받고 싶으면 [IpgInstrumentationTest.kt](app/src/androidTest/java/dev/ipg/listener/IpgInstrumentationTest.kt) 의 상수 조정.
- **Canvas / OpenGL / SurfaceView 콘텐츠**는 view tree 밖이라 어떤 이벤트도 안 옴 — 안드로이드 자체 한계.
- **Toast text가 Android 12+ 에서 비어 오는 경우**: 시스템 `NotificationService` 로그는 redact되지만, UiAutomation 은 직접 AccessibilityEvent를 받기 때문에 redact 영향을 받지 않는다.
- 이 앱은 INTERNET 권한이 없다. 외부로 송신 안 함. logcat 한 채널이 전부.
