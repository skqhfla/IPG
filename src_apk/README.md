# IoT Packet Generator (IPG) — src_apk

안드로이드 IoT 앱을 자동 탐색(UI Traversal)하면서 UI 전이(UTG)와 네트워크 패킷을 수집하는 프레임워크. `src_apk/`는 **a11y 채널 기반** 메인 트리이고, [../src/](../src/)는 ADB uiautomator dump 기반 백업으로 동결되어 있습니다.

> 두 트리의 차이: `src/`는 `adb shell uiautomator dump`로 XML을 받지만, `src_apk/`는 단말에 설치된 [device_listener APK](../device_listener/)의 AccessibilityService가 emit하는 a11y XML을 받습니다. Hybrid Detector(a11y + YOLOv8 + OCR + IoU-priority merge) 구조는 동일.

---

## 1. 요구 사항

- Python 3.10 이상
- `adb` (Android Platform Tools) — PATH에 등록되어 있어야 함
- USB 디버깅이 활성화된 안드로이드 기기
- **`device_listener` APK가 단말에 설치되고 접근성 서비스가 활성화돼 있어야 함** (아래 §2)
- YOLO 가중치 — `src_apk/models/yolov8.pt` (또는 `core/config/model_paths.py`의 `MODEL_PATH` 참조)
- (선택) PaddleOCR 모델 — OCR 모드를 `paddle`로 사용할 때 필요

주요 파이썬 의존성: `torch`, `ultralytics`, `paddleocr`, `opencv-python`, `numpy` 등.

---

## 2. device_listener APK 사전 준비 (필수)

[device_listener](../device_listener/) 는 **instrumented test** 로 동작합니다. AccessibilityService 가 아니라 `am instrument -w` 로 띄우는 `UiAutomation` 기반 — 사용자 토글 없이, Samsung Knox 같은 OEM 정책에도 막히지 않고 즉시 동작.

`src_apk/`는 실행 직후 [A11yEventListener.start()](src_apk/core/adb/a11y_event_listener.py) 가 자동으로 instrumentation 을 띄우고 [verify_available()](src_apk/core/adb/a11y_event_listener.py) 로 검증합니다. 실패하면 `A11yServiceUnavailable` → **exit code 2로 ABORT**.

검증 단계:
1. `dev.ipg.listener` (main APK) + `dev.ipg.listener.test` (instrumented test APK) 둘 다 설치돼 있는가
2. `am instrument` 가 띄운 instrumentation 이 15초 안에 `SERVICE_CONNECTED` 를 logcat 으로 emit 했는가
3. trigger-file (`dump_now.trigger`) probe 가 정상 동작해 `DUMP_WRITTEN` 응답이 오는가

### 2.1 설치 (활성화 단계 없음)

```bash
# 빌드 (Windows: gradlew.bat, *nix: ./gradlew)
cd device_listener
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest

# 두 APK 모두 설치
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
```

> **이전 AccessibilityService 활성화 단계 (Settings 토글, `settings put secure enabled_accessibility_services ...`) 는 더 이상 필요 없음.** 설치만 하면 끝. `src_apk` 실행 시 `am instrument` 가 자동으로 띄움.

### 2.2 캡처 대상 필터 (선택)

캡처할 패키지를 좁히고 싶으면 `/sdcard/Android/data/dev.ipg.listener/files/config.json` 에 `{appLabel, packages}` 작성 (APK의 EDIT FILTER UI에서도 편집 가능). 없으면 모든 앱이 캡처 대상.

---

## 3. 실행

```bash
python src_apk/main.py --app Hejhome
```

실행 결과는 `outputs_APK/<app>/<timestamp>/` 아래에 저장됩니다.

---

## 4. CLI 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--app <name>` | `Hejhome` | 탐색 대상 앱 이름. 지원 앱 목록은 아래 §6 |
| `--serial <id>` | 자동 | ADB 기기 시리얼 (여러 기기 연결 시 명시) |
| `--runtime <sec>` | `3600` | 탐색 타임아웃 (초) |
| `--utg` | off | UTG 기록 활성화 (`utg.json`, `utg.png`) |
| `--draw` | off | 감지된 UI 요소 시각화 이미지 저장 |
| `--no-log` | off | 로그 파일 출력 비활성화 |
| `--debug` | off | 디버그 로그 활성화 |
| `--node-loop-repetition <n>` | `3` | 노드 루프 감지 반복 임계값 |
| `--setup` | off | **Setup 모드** 진입 (§5 참조) |
| `--rerun <path>` | off | **재실행 모드** — 이전 run dir의 memory를 로드해 미트리거 이벤트만 수행 (§5.5 참조) |

---

## 5. Setup 모드 — 탐색 제외 화면 등록

특정 화면(로그인 / 결제 / 권한 요청 등)을 탐색에서 제외하고 싶을 때 사용합니다. Setup 모드에서 등록한 화면에 도달하면 일반 실행 시 자동으로 `BACK` 키를 눌러 회피합니다.

### 5.1 화면 등록

```bash
python src_apk/main.py --app Hejhome --setup
```

대화형 프롬프트:

```
[Setup 모드] 앱=Hejhome
예외 파일: exceptions/Hejhome/exceptions.json
기존 등록된 제외 화면 0개 로드됨.
Setup 모드 명령어:
  add            - 현재 기기 화면을 감지해 제외 목록에 추가
  list           - 등록된 제외 화면 목록 보기
  remove <id>    - 제외 목록에서 제거 (앞부분 일치로 검색 가능)
  help           - 이 도움말 보기
  quit           - 종료

setup>
```

**워크플로:**
1. 폰에서 수동으로 제외하고 싶은 화면으로 이동
2. 터미널에 `add` 입력 → 현재 화면을 감지(=`DUMP_NOW` broadcast + Hybrid Detection)해 ScreenID 계산 후 저장
3. 반복
4. `list` / `remove <prefix>` / `quit`

### 5.2 저장 위치

```
exceptions/
└── <app>/
    ├── exceptions.json         # 등록된 ScreenID 목록
    └── screenshots/
        └── <screen_id>.png     # 등록 시점의 스크린샷
```

### 5.3 일반 실행 시 동작

- 시작 시 `exceptions/<app>/exceptions.json` 로드
- 탐색 중 감지된 화면의 ScreenID가 등록 목록과 일치하면:
  - `[EXCLUDED] step=... stage=before|after screen=... — 제외 화면 도달, back 실행`
  - `BACK` 키 전송 후 다음 스텝에서 화면 재감지
- `excluded_streak` 임계값 초과 시 `home + relaunch` hard escape

---

## 5.5 재실행 모드 — 이전 run의 미트리거 이벤트만 수행

이미 한 번 돌린 run의 결과를 이어받아, 그 run에서 **트리거되지 않은(미실행)** 이벤트만 추가로 수행하고 싶을 때 사용합니다. 시간이 부족해 끊긴 탐색을 이어가거나, 첫 run의 커버리지를 보강할 때 유용합니다.

```bash
python src_apk/main.py --app Hejhome \
  --rerun outputs_APK/Hejhome/20260526_120000
```

동작:
- `--rerun PATH/json/` 에서 `app_memory.json` / `screen_memory.json` / `packet_memory.json` 을 로드 (UTG가 필요하면 `--utg` 와 함께 사용하면 `PATH/utg/utg.json` 도 로드).
- 로드된 메모리에는 각 element 별 `executed_events`, `swipe_directions_tried/exhausted` 가 그대로 들어 있으므로, Traversal Policy 가 자연스럽게 이미 트리거된 이벤트를 건너뛰고 **남은 미트리거 이벤트만** 후보로 골라 수행합니다.
- 출력은 평소처럼 새 timestamp 디렉터리 (`outputs_APK/<app>/<new_timestamp>/`) 에 기록 — 원본 PATH 는 절대 변경하지 않습니다.
- 미트리거 이벤트가 더 이상 없으면 `terminal_reason = no_more_actionable_events` 로 정상 종료.

---

## 6. 출력 구조

```
outputs_APK/
└── <app>/
    └── <timestamp>/
        ├── screen/                  # 원본 스크린샷 (<snapshot_id>.png)
        ├── xml/                     # a11y XML (<snapshot_id>.xml)
        ├── detect_images/           # --draw 사용 시 감지 시각화
        │   ├── yolo/
        │   ├── uiauto/
        │   └── merged/
        ├── json/
        │   ├── app_memory.json      # 화면 / 요소 인벤토리
        │   ├── screen_memory.json   # 화면 전이 기록
        │   └── packet_memory.json   # 패킷 이벤트 (screen_id × snapshot_id × event_key)
        ├── utg/                     # --utg 사용 시
        │   ├── utg.json
        │   └── utg.png
        ├── logs/runtime.log
        └── run_meta.json            # 실험 메타데이터 (설정, 기기, 통계)
```

**지원 앱:** `BN-LINK`, `Hejhome`, `Hue`, `Kasa`, `LG`, `Sengled`, `SmartThings`, `Tapo`, `Xiaomi`, `cam720` ([core/config/app_packages.py](src_apk/core/config/app_packages.py))

---

## 7. 시각화 (Monitor)

수집된 UTG(`utg.json`)는 별도 웹 뷰어로 확인할 수 있습니다. 사용법은 [../Monitor/README.md](../Monitor/README.md) 참조.

---

## 8. 사용 예시

```bash
# 기본 실행 (Hejhome, 1시간 타임아웃)
python src_apk/main.py --app Hejhome

# UTG + 감지 시각화 + 디버그 로그
python src_apk/main.py --app SmartThings --utg --draw --debug

# 여러 기기 연결 시 특정 시리얼 지정
python src_apk/main.py --app Tapo --serial R5CX12345678

# 제외 화면 등록 후 자동 회피 실행
python src_apk/main.py --app Hejhome --setup                  # 화면 등록
python src_apk/main.py --app Hejhome --utg --runtime 1800     # 실제 탐색

# 이전 run을 이어받아 미트리거 이벤트만 추가 수행 (재실행 모드)
python src_apk/main.py --app Hejhome \
    --rerun outputs_APK/Hejhome/20260526_120000 --utg
```

---

## 9. 자주 마주치는 실패

| 증상 | 원인 / 조치 |
|---|---|
| `[A11Y] device_listener APK 가 단말에 설치돼 있지 않음` | §2.1 설치 단계 다시. main APK + test APK 둘 다 필요 |
| `[A11Y] instrumentation 이 ... SERVICE_CONNECTED 를 emit 하지 않음` | system_server 에 stale UiAutomation 등록이 남음 — `adb reboot` 가 가장 확실. 또는 `adb shell am instrument -w -m -e class dev.ipg.listener.IpgInstrumentationTest#run dev.ipg.listener.test/androidx.test.runner.AndroidJUnitRunner` 를 직접 띄워 stdout 의 에러 확인 |
| `[A11Y] trigger-file 응답이 ... 안 옴` | instrumentation 의 polling thread 가 stuck. `adb shell am force-stop dev.ipg.listener` 후 재시도 |
| `xml_path` 가 device-side 경로라 push 못 받을 때 | `outputs_APK/<app>/<session>/xml/<seq>.xml`에 a11y XML이 떨어졌는지 확인 (APK 설정에 따름) |

---

## 10. src/ 와의 관계

- [../src/](../src/) — ADB uiautomator dump 기반 백업 트리. **수정 금지**, 회귀 비교·환경 fallback 용도로 보존.
- `src_apk/` — a11y 채널 기반 메인. 모든 신규 개발은 여기서.
- 현재 양쪽 파일이 거의 1:1로 공존 — drift 주의. 의미 있는 변경은 `src_apk/`에서만.
