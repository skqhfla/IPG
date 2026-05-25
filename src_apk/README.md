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

`src_apk/`는 실행 직후 [A11yEventListener.verify_available()](src_apk/core/adb/a11y_event_listener.py)로 세 가지를 점검합니다. 하나라도 통과 못 하면 `A11yServiceUnavailable` 발생 → **exit code 2로 ABORT**.

1. `dev.ipg.listener` 패키지가 설치되어 있는가
2. `settings get secure accessibility_enabled = 1` 이고 `enabled_accessibility_services`에 `dev.ipg.listener/.IpgAccessibilityService`가 포함돼 있는가
3. `am broadcast -a dev.ipg.listener.DUMP_NOW` 에 5초 내 `DUMP_WRITTEN` 응답이 오는가

### 2.1 설치 / 활성화

```bash
# 빌드 (Windows: gradlew.bat, *nix: ./gradlew)
cd device_listener
./gradlew :app:assembleDebug

# 설치
adb install -r app/build/outputs/apk/debug/app-debug.apk

# 접근성 활성화
adb shell settings put secure enabled_accessibility_services \
    dev.ipg.listener/dev.ipg.listener.IpgAccessibilityService
adb shell settings put secure accessibility_enabled 1

# 확인
adb shell dumpsys accessibility | grep "enabled services"
```

> `adb install -r`은 a11y 서비스를 자동 재바인딩하지 않습니다. 재설치 후 첫 실행에서 verify가 실패하면 위의 두 `settings put` 명령을 다시 실행하거나, 폰에서 IPG Listener 앱 열어 ENABLED 상태인지 확인하세요.

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
        │   └── packet_memory.json   # 패킷 이벤트
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
```

---

## 9. 자주 마주치는 실패

| 증상 | 원인 / 조치 |
|---|---|
| `[A11Y] device_listener APK가 단말에 설치돼 있지 않음` | §2.1 설치 단계 다시 |
| `[A11Y] 접근성 서비스가 활성화돼 있지 않음` | `adb shell settings put secure enabled_accessibility_services ...` 재실행 또는 폰 설정에서 토글 |
| `[A11Y] DUMP_NOW broadcast에 5.0s 내 응답 없음` | 폰에서 IPG Listener 앱 열어 ENABLED 확인. `adb install -r` 직후 자주 발생 — 활성화 명령 재실행 |
| `xml_path` 가 device-side 경로라 push 못 받을 때 | `outputs_APK/<app>/<session>/xml/<seq>.xml`에 a11y XML이 떨어졌는지 확인 (APK 설정에 따름) |

---

## 10. src/ 와의 관계

- [../src/](../src/) — ADB uiautomator dump 기반 백업 트리. **수정 금지**, 회귀 비교·환경 fallback 용도로 보존.
- `src_apk/` — a11y 채널 기반 메인. 모든 신규 개발은 여기서.
- 현재 양쪽 파일이 거의 1:1로 공존 — drift 주의. 의미 있는 변경은 `src_apk/`에서만.
