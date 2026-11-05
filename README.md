# TTS 자동 방송 송출 시스템

> **소스 공개, 수정·재배포 금지.** 오픈소스가 아닙니다. 소스를 보고 수정 없이 직접 실행할 수는 있지만, 저작자의 사전 서면 허락 없이 수정·배포할 수 없습니다. 자세한 조건은 [LICENSE](LICENSE)를 확인하세요.

문구를 음성(TTS)으로 바꿔 **실시간 / 자동으로 방송 스피커(앰프)에 송출**하는 프로그램입니다.

- **기본 엔진: Supertonic 3** (Supertone) — 자연스러운 신경망 한국어 음성, CPU 만으로 완전 오프라인 동작(모델 라이선스는 아래 참고). 여성 F1~F5 / 남성 M1~M5.
- **폐쇄망 동작**: 설치를 마치면 인터넷 연결이 전혀 필요 없습니다.
- **예비 엔진 자동 대체**: 기본 엔진이 실패하면 Windows 내장 음성(SAPI)으로 자동 송출해 방송이 누락되지 않습니다 (`broadcast.fallback_engine`).
- **TTS 엔진 교체 쉬움**: `config.json` 의 `active_engine` 한 줄 또는 화면의 [엔진 · 차임벨] 메뉴에서 전환.
- **자동 송출 경로 4가지**: 운영자 화면 / 예약 방송 / 감시 폴더(.txt 투입) / 내부망 HTTP API·웹 페이지.
- 우선순위 대기열, **긴급 방송 끼어들기**(중단된 방송은 끝난 뒤 자동 재송출), 반복 송출, 시작·종료 차임벨, 합성 결과 캐시, 일자별 로그.

## 소스에서 실행

이 저장소에는 소스 코드만 있습니다. 음성 모델과 Python 패키지는 공식 배포처에서 받습니다. Windows, Python 3.11 64bit 기준입니다.

```powershell
pip install -r requirements-offline.txt
hf download Supertone/supertonic-3 --local-dir models/supertonic3
python main.py
```

모델을 받으면 [Open RAIL-M 라이선스](https://huggingface.co/Supertone/supertonic-3/blob/main/LICENSE)와 사용 제한(부속서 A)이 적용됩니다. `config.json` 은 첫 실행 때 자동으로 만들어집니다.

## 아파트·공공시설 운영 기능

- **안내문 양식** 탭: 차량 이동, 단수, 정전, 엘리베이터 점검, 공사, 소독, 분리수거, 택배, 층간소음, 분실물, 관리비, 주민 회의, 소방 훈련, 화재·가스 대피(긴급), 미아 찾기, 폭염·한파 등 18종. 빈칸만 채우면 됩니다. 양식은 `templates.json` 에서 추가·수정합니다 (`{이름}` 이 빈칸).
- **시설 설정** 탭
  - 시설명과 머리말·맺음말 (기본 머리말: "○○아파트 관리사무소에서 알려 드립니다.")
  - **AI 음성 고지** (음성 모델 라이선스 부속서 A(e), AI 기본법 대응) — 세 가지 중 선택
    - **게시물로 대체 (기본)**: 방송에는 고지 멘트 없음. [게시용 안내문 만들기]로 A4 안내문을 인쇄해 게시판·엘리베이터·출입구에 붙이고 "게시했습니다"에 체크. 체크 전에는 방송 기록에 경고가 표시됩니다.
    - 하루 첫 방송에만 음성 고지 / 매 방송 음성 고지 ("AI 음성 안내 방송입니다.")
  - 야간 방송 제한 (선택, 기본 꺼짐): 켜면 지정 시간(예: 22:00~07:00)에 예약·자동 방송은 긴급 방송만 송출되고, 운영자 방송은 확인 창을 거쳐 송출됩니다.
- **차량번호**: "12가 3456"은 "일이가 삼사오육", "3456 차량"은 "삼사오육 차량"으로 읽습니다. 전체 번호도 제한 없이 송출됩니다 (차량 이동 요청은 위반 사항이 아님).

## 송출 전 내용 점검 (위반 경고)

송출할 때마다 문구를 자동 점검해 라이선스(Open RAIL-M 부속서 A)나 개인정보보호법 위반 소지가 있으면 경고 창을 띄웁니다.

| 수준 | 항목 | 동작 |
|---|---|---|
| ⛔ 차단 | 주민등록번호 | 송출 불가 |
| ⚠ 경고 | 개인 휴대전화번호(동의 없을 때), 특정 세대(동·호수)를 지목한 미납·민원·위반 내용, 기관 명의(사칭 소지), 의료 조언, 차별(임대세대·외국인 등 이용 제한), 비방·모욕, 아동 개인정보(보호자 동의 없을 때), 범죄·출입국 정보 | 위반 가능성을 알리고, 운영자가 확인하면 송출 |
| ❓ 확인 | 야간 제한 시간 (야간 방송 제한을 켠 경우만) | 확인 후 송출 |

**라이선스·법률 위반에 해당할 수 있는 경우만 경고**합니다. 차량번호 전체 송출, 화재·대피 등 비상 방송처럼 위반이 아닌 내용은 제한하지 않습니다.

- 예약·감시 폴더·API처럼 운영자 확인이 없는 자동 송출은 차단 항목만 막습니다. 경고 항목은 방송 기록에 주황색으로 남고, 운영자 확인 내역은 로그에 남습니다.
- 키워드 기반 보조 기능이라 모든 위반을 잡아내지는 못합니다. 규칙은 `tts_broadcast\compliance.py` 에서 추가·수정합니다.
- 첫 실행 때 사용 제한 동의 창이 뜹니다 (`config.json` 의 `license_accepted` 에 동의 시각이 기록됨).

## 실행

| 방법 | 설명 |
|---|---|
| `방송프로그램_실행.bat` | 방송 프로그램 (하나로 통합: 화면 + 예약·감시폴더·API 자동 방송) |
| `python main.py --tray` | 창 없이 트레이에서 시작 (예전 `--headless` 서버 모드도 이것으로 동작) |
| `python main.py --say "문구" --priority 긴급 --repeat 2` | 한 번 방송 (프로그램이 켜져 있으면 그 대기열로 전달) |
| `python main.py --list-voices` | 현재 엔진의 음성 목록 |
| `python main.py --list-engines` | 등록된 엔진 종류 |

> **출력 장치**: Windows **기본 재생 장치**로 나갑니다. 방송 앰프에 연결된 사운드 장치를 Windows 소리 설정에서 기본 장치로 지정하세요.

**창을 닫아도 방송은 계속됩니다.** 창은 작업 표시줄 오른쪽 아래 알림 영역(트레이)으로 들어가고, 예약·감시 폴더·API 방송은
그대로 동작합니다. 트레이 아이콘을 누르면 창이 다시 열리고, 완전히 끄려면 트레이 아이콘 우클릭 → **프로그램 종료**.

**PC 부팅 시 자동 실행**: [엔진 · 차임벨] → 설정 관리의 **Windows 시작 시 자동 실행**(또는 트레이 메뉴)을 켜면
로그온할 때 창 없이 트레이에서 시작합니다 (현재 사용자 시작 프로그램 등록, 관리자 권한 불필요).

**중복 실행 방지**: 한 PC 에서는 하나만 실행됩니다. 이미 켜져 있을 때 다시 실행하면 새로 켜지 않고 기존 창을 앞으로 불러옵니다
(같은 방송이 두 번 나가거나 API 포트가 겹치는 것을 막음).

> `.bat` 파일은 한글이 깨지지 않도록 영문(ASCII)만 사용합니다. 한글 안내는 Python·PowerShell(`tools\offline_install.ps1`)이 출력합니다.

## 자동 방송 방법

### 1) 예약 방송
화면의 [예약 방송] 메뉴에서 추가하거나 `schedules.json` 을 직접 편집합니다 (저장하면 실행 중에도 자동 반영).
- `type: "time"` — 지정 시각 (`time`, 요일 `days` 0=월…6=일, 비우면 매일, `date` 지정 시 그 날만)
- `type: "interval"` — `start`~`end` 사이 `interval_min` 분마다

### 2) 감시 폴더 (`inbox`)
`inbox` 폴더에 `.txt` 파일을 넣으면 즉시 방송하고 `inbox\done` 으로 옮깁니다 (실패 시 `inbox\error`).
UTF-8 / ANSI(CP949) 모두 지원. 맨 위에 옵션을 붙일 수 있습니다:
```
#priority=긴급
#repeat=2
#chime=false
화재 경보가 발령되었습니다. 즉시 대피하십시오.
```
네트워크 공유 폴더로 지정하면 다른 PC·장비에서 파일만 떨어뜨려 연동할 수 있습니다 (`config.json` → `watch_folder.path`).

### 3) HTTP API / 웹 페이지 (내부망)
기본은 이 PC에서만 접속 가능(`127.0.0.1`)합니다. 내부망의 다른 PC에서 쓰려면 `config.json` 의 `api.host` 를 `"0.0.0.0"` 으로, **`api.token` 에 비밀값을 설정**하고 방화벽에서 포트(기본 8765)를 허용하세요.
- 브라우저: `http://<PC주소>:8765/`
- `POST /api/announce` `{"text":"...", "priority":"긴급|높음|보통", "repeat":1, "chime":true}`
- `GET /api/announce?text=...&priority=긴급&token=...` (간단한 장비용)
- `GET /api/status`, `POST /api/stop`, `POST /api/clear`
- 토큰: 헤더 `X-Token` 또는 `?token=`

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/announce -ContentType 'application/json; charset=utf-8' `
  -Body ([Text.Encoding]::UTF8.GetBytes('{"text":"테스트 방송입니다","priority":"높음"}'))
```

## 숫자·기호 읽기

방송 문구의 숫자는 엔진에 보내기 전에 자동으로 한국어 읽기로 바뀝니다 (`broadcast.normalize_text`).
화면의 [읽기 확인] 버튼이나 `python main.py --reading "문구"` 로 미리 확인할 수 있습니다.

| 입력 | 읽기 |
|---|---|
| 오후 2시 30분, 14:00, 3pm | 오후 두 시 삼십 분, 오후 두 시, 오후 세 시 |
| 09:00~18:00, 9시~18시 | 오전 아홉 시부터 오후 여섯 시까지, 아홉 시부터 오후 여섯 시까지 |
| 11/3(월), (월~금) | 십일 월 삼 일 월요일, 월요일부터 금요일까지 |
| 3층, B1층, 5번 출구 | 삼 층, 지하 일 층, 오 번 출구 |
| 20명, 3~4명, 1번째 | 스무 명, 세 명에서 네 명, 첫 번째 |
| 2026.10.31, 6월 | 이천이십육 년 시월 삼십일 일, 유월 |
| 1,500원, 10000원 | 천오백 원, 만 원 |
| 25.5%, -5℃, 5km | 이십오 점 오 퍼센트, 영하 오 도, 오 킬로미터 |
| 010-1234-5678, 119 | 공일공에 일이삼사에 오육칠팔, 일일구 |
| B동, KTX, CCTV | 비동, 케이티엑스, 씨씨티비 |
| Wi-Fi, A/S, Q&A, 1F, 30km/h, 84㎡ | 와이파이, 에이에스, 큐앤에이, 일 층, 시속 삼십 킬로미터, 팔십사 제곱미터 |
| 101-1502, 1+1, [안내], 주차·통행 | 백일 다시 천오백이, 일 플러스 일, 안내, 주차, 통행 |

**발음 사전**: 그 밖의 영문 단어(예: parking)는 엔진이 어색하게 읽을 수 있습니다. 방송 화면에서 영문이 감지되면
노란 안내가 뜨고, [발음 등록]으로 읽는 법을 등록할 수 있습니다 (`config.json` 의 `pronunciations`, 즉시 적용).

단위 목록은 `tts_broadcast\textnorm.py` 의 `NATIVE_COUNTERS`(한/두/세…로 읽음), `SINO_COUNTERS`(일/이/삼…으로 읽음)에 추가할 수 있습니다.

## 음성 조절 (목소리 · 빠르기 · 음높이 · 음량 · 음질 · 문장 간격)

[엔진 · 차임벨] 화면의 **음성 조절**에서 바꾸고 [적용하고 들어보기]로 바로 확인합니다 (모델 재로딩 없이 즉시 적용,
재생 중에 다시 누르면 앞 테스트를 끊고 새 설정으로 재생). 각 항목은 엔진 옵션(JSON)의 값과 같습니다.

| 화면 항목 | JSON | 내용 |
|---|---|---|
| 목소리 | `voice` | F1~F5 여성, M1~M5 남성, 또는 직접 만든 목소리 json 경로 |
| 빠르기 | `speed` | 70~150% (Windows 음성은 `rate` -10~+10) |
| 음높이 | `pitch` | -6~+6 반음. 말 빠르기는 그대로 두고 높이만 바꿈 |
| 음량 | `volume` | 최대 음량 -1dBFS 기준이 100%. 100% 초과는 찢어지지 않게 압축해서 더 크게 |
| 음질 | `steps` | 2~16 단계 (권장 8). 높을수록 깨끗하지만 합성 시간 증가 |
| 문장 간격 | `silence` | 긴 문구를 나눠 읽을 때 문장 사이 쉬는 시간 0~1.5초 |

`model_dir`(모델 폴더)·`lang`(언어)은 바꾸지 않습니다.

## 설정 저장 · 불러오기 · 초기화

[엔진 · 차임벨] 화면의 **설정 관리**에서 합니다.

- **설정 저장**: 엔진·음성 조절·차임·시설·예약·발음 사전·자주 쓰는 문구·안내문 양식, 그리고 설정이 가리키는
  사용자 파일(직접 넣은 차임 WAV, 목소리 json)을 zip 파일 하나로 저장합니다. PC 교체나 다른 단지에 같은 설정을 넣을 때 사용합니다.
- **설정 불러오기**: 저장한 zip 으로 복원하고 프로그램을 다시 시작합니다. 라이선스 동의 기록은 이 PC 것을 유지합니다.
- **초기화**: 항목(음성·방송 / 시설 / 발음·문구 / 예약 / 양식)을 골라 처음 설치 상태로 되돌립니다.
  예약·양식의 처음 상태는 `assets\defaults` 폴더의 파일입니다.
- 불러오기·초기화 직전 현재 설정이 `backups\자동백업_날짜_시각.zip` 으로 자동 저장되므로(최근 20개) 언제든 되돌릴 수 있습니다.

## 차임벨

`assets\chimes` 의 차임은 이 프로그램이 직접 합성한 음원이라 제3자 음원이 들어 있지 않습니다 (44.1kHz 스테레오, 잔향 포함).

| 파일 | 소리 |
|---|---|
| `4tone_up.wav` (기본 시작) | 딩동댕동 상승 (솔-시-레-솔) |
| `4tone_down.wav` (기본 종료) | 딩동댕동 하강 |
| `3tone_up.wav` / `3tone_down.wav` | 도-미-솔 상승 / 하강 |
| `2tone.wav` | 딩-동 |

[TTS 엔진 설정] 탭의 차임벨 영역에서 ▶ 로 미리 듣고 [차임 적용]으로 바꿉니다. 고객사 고유 차임은 WAV(PCM) 파일을 `assets\chimes` 에 넣으면 목록에 나타납니다 (그 음원의 사용 권리는 고객사가 확보해야 합니다).
차임을 다시 만들려면 `python -m tts_broadcast.audio` (음 높이·간격은 `audio.py` 의 `CHIME_PRESETS`).

## 우선순위
`긴급(0)` > `높음(1)` > `보통(5)`. 긴급 방송이 들어오면 진행 중인 일반 방송을 즉시 끊고 송출한 뒤, 끊긴 방송을 다시 처음부터 송출합니다 (`broadcast.interrupt_on_emergency`, `requeue_interrupted`).

### 긴급 방송은 소리부터 다릅니다 ([시설 설정] → 긴급 방송)

| | 일반 방송 | 긴급 방송 |
|---|---|---|
| 송출 전 | 바로 대기열 | **확인 창** (문구·반복·음량 표시, Enter 는 '취소') |
| 시작 소리 | 차임벨 (부드러운 벨) | **경보음** 5종 중 선택 (직접 합성, `tts_broadcast\alerts.py`):<br>`emergency.wav` 소방차 사이렌 '애애앵~' (웨일, 한 번 오르내림 약 3.5초 × 2)<br>`emergency_wailyelp.wav` 소방차 출동 '애앵~ → 위용위용'<br>`emergency_yelp.wav` 빠른 사이렌 '위용위용' (초당 약 3.4회)<br>`emergency_hilo.wav` 구급차형 '삐뽀삐뽀'<br>`emergency_bell.wav` 화재 비상벨 '따르르릉'<br>전자 사이렌 신호를 나팔형 스피커 특성에 통과시키고, 길거리 거리감·건물 메아리를 더해 일상에서 듣는 소리에 가깝게 함.<br>직접 녹음한 사이렌 WAV 를 `assets\chimes` 에 넣으면 그것도 고를 수 있음.<br>민방위 경보와 비슷한 소리는 실제 경보로 오인될 수 있어 넣지 않음 |
| 끝 소리 | 종료 차임 (설정 시) | 없음 (사이렌 뒤 부드러운 차임 생략) |
| 첫마디 | 바로 본문 | **"긴급 안내 말씀 드립니다."** (문구 변경 가능) |
| 반복 | 지정한 횟수 | **최소 2회** (설정 가능) |
| 음량 | 기본 | **130%** (찢어지지 않게 압축, 100~150%) |
| 순서 | 대기열 순서 | 진행 중인 방송을 끊고 바로 송출 |
| 야간 제한 | 자동 방송 보류 | 상관없이 송출 |

설정 위치: `config.json` 의 `broadcast.emergency` (`chime_file`, `prefix`, `min_repeat`, `volume`).

## TTS 엔진 교체

엔진은 `config.json` 의 `engines` 에 **프로필**로 등록하고 `active_engine` 으로 선택합니다.

```json
"active_engine": "windows_korean",
"engines": {
  "windows_korean": {"type": "sapi", "options": {"voice": "Microsoft Heami Desktop", "rate": 0, "volume": 100}},
  "piper_offline":  {"type": "command", "options": {
      "command": ["tools/piper/piper.exe", "--model", "models/voice.onnx", "--output_file", "{out}"],
      "stdin": "{text}"}}
}
```

| 종류(type) | 설명 |
|---|---|
| `supertonic` | **기본.** Supertonic 3 신경망 음성. `voice`(F1~F5, M1~M5), `lang`("ko"), `speed`(0.7~2.0), `pitch`(반음 -6~+6), `steps`(품질, 기본 8), `volume`(1.0=정규화 기준, 최대 2.0), `model_dir`. 문장당 합성 1~3초 (차임벨 울리는 동안 동시 합성) |
| `sapi` | Windows 내장 음성. 한국어 "Microsoft Heami" 기본 제공. `voice`, `culture`, `rate`(-10~10), `volume`(0~100), `pitch`(반음 -6~+6). 문구가 `<speak` 로 시작하면 SSML 로 처리 |
| `command` | **외부 오프라인 TTS 프로그램 연결** (Piper, sherpa-onnx, 자체 엔진 등). 코드 수정 없이 설정만으로 연결. 치환자 `{out}`(출력 WAV), `{text}`, `{text_file}` |
| 플러그인 | `plugins\_template_engine.py` 를 복사해 `synthesize()` 만 구현 → 자동 등록 |

새 엔진 조건: 문구를 받아 **WAV 파일**을 만들면 됩니다. 외부 엔진의 실행파일·모델은 `tools\`, `models\` 폴더에 두면 상대경로로 쓸 수 있어 폴더째 옮기기 쉽습니다.

## 폐쇄망 설치

먼저 `models\supertonic3` 에 모델을 받고, 같은 Python 으로 `pip download -r requirements-offline.txt -d offline_wheels --only-binary=:all:` 를 실행해 패키지를 받아 둡니다. Python 설치 파일도 `offline_wheels` 에 넣습니다. 이렇게 만든 패키지는 본인이 설치할 PC에만 쓸 수 있으며, 제3자에게 배포하려면 저작자의 허락이 필요합니다.

1. 인터넷 PC에서 `폐쇄망_배포패키지_만들기.ps1` 실행 → `dist\TTS방송_날짜.zip` 생성 (모델·패키지 포함 약 450MB)
2. 반입 PC에서 압축 해제 후:
   1. `offline_wheels\python-3.11.9-amd64.exe` 설치 ("Add python.exe to PATH" 체크) — 이미 Python 3.11 64bit 가 있으면 생략
   2. `폐쇄망_설치.bat` 실행 (인터넷 없이 `offline_wheels` 에서 설치)
   3. `방송프로그램_실행.bat` 실행
   - `offline_wheels` 는 **Python 3.11 64bit 전용**입니다. 다른 버전을 쓰려면 인터넷 PC의 같은 버전 Python 에서
     `pip download -r requirements-offline.txt -d offline_wheels --only-binary=:all:` 로 다시 받으세요.
   - Python 설치 없이 쓰려면 인터넷 PC에서 `pip install pyinstaller` 후 `폐쇄망_배포패키지_만들기.ps1 -BuildExe`
3. 예비 엔진(Windows 음성)용 한국어 음성이 없으면: Windows 설정 → 시간 및 언어 → 언어 → 한국어 → 음성 기능 설치 (폐쇄망은 FOD/언어팩 ISO 로 설치)

## 엔진 선정 근거 (2026-10-31 비교, CPU 전용 PC)

| 엔진 | 라이선스 | 문장(음성 9~12초) 합성 | 로딩 | 용량 | 결과 |
|---|---|---|---|---|---|
| **Supertonic 3** | OpenRAIL-M (사용 제한 조항) | **5~7초** | 2초 | 0.4GB | **채택** |
| Chatterbox Multilingual | MIT | 39~56초 | 99초 | 약 5GB | 제외: 실시간 방송 불가, 문장 끝 잘림 의심 |
| MeloTTS-Korean | MIT | — | — | 2GB 이상 | 제외: Windows용 한국어 형태소 분석기(eunjeon) 미제공, C++ 빌드 필요 |

엔진 라이선스와 관계없이 AI 기본법(AI 생성물 고지)과 개인정보보호법은 적용됩니다.

## 라이선스 (상업적 이용)

| 구성요소 | 라이선스 | 상업적 이용 |
|---|---|---|
| 이 프로그램 | [LICENSE](LICENSE), [LICENSE-EULA.txt](LICENSE-EULA.txt) | 안내 방송 송출 목적의 사용 가능, 수정·재배포·판매 금지 |
| Supertonic 코드 (`supertonic` 패키지) | MIT | 가능 |
| Supertonic 3 모델 (`models\supertonic3`) | OpenRAIL-M (`models\supertonic3\LICENSE`) | **가능 — 사용 제한 조항 준수 조건** |
| onnxruntime / numpy 등 | MIT / BSD | 가능 |
| Windows SAPI 음성 (예비 엔진) | Windows 라이선스 | **사용자 확인 필요** — 상업 방송 이용 조건은 본인의 Windows 라이선스를 확인하세요. 허용되지 않으면 [TTS 엔진 설정] → 예비 엔진 "(사용 안 함)" |

제3자 구성요소 고지는 `THIRD_PARTY_NOTICES.md`, 모델 사용 제한 조항 문안은 `docs\AI음성_사용제한_조항(계약서용).md` 에 있습니다.

OpenRAIL-M 주요 의무 (원문 `models\supertonic3\LICENSE` 확인 필수, 법률 자문 아님):
- 모델을 **제3자에게 배포**할 경우 LICENSE 사본을 함께 제공하고, 계약서에 사용 제한(Attachment A) 조항을 포함해야 합니다.
- 금지 용도: 불법 행위, 허위정보로 타인에게 해를 끼치는 행위, **동의 없는 특정인 사칭**, 의료 조언, 사법·수사·출입국 판단용 정보 생성 등.
- Attachment A(e): 기계 생성 콘텐츠를 **기계 생성임을 명확히 밝히지 않고** 게시하는 것을 금지합니다. 사내·시설 안내방송이라도 필요하면 "자동 안내 방송입니다" 같은 고지 문구를 넣으세요.
- 출력된 음성 파일의 권리는 라이선스 제공자가 주장하지 않습니다 (Section 6).

## 폴더 구조
```
main.py                     실행 진입점
config.json                 설정 (첫 실행 때 자동 생성, 저장소에 없음)
schedules.json              예약 방송 목록
tts_broadcast\
  engines\                  TTS 엔진 (base.py 인터페이스, supertonic.py, sapi.py, command.py)
models\supertonic3\         Supertonic 3 모델 + LICENSE (별도 다운로드)
offline_wheels\             폐쇄망 설치용 패키지 + Python 설치 파일 (직접 준비)
requirements-offline.txt    폐쇄망 설치 목록
폐쇄망_설치.bat              폐쇄망 PC 패키지 설치
  broadcaster.py            대기열·우선순위·차임·반복·송출
  textnorm.py               숫자·기호·차량번호 한국어 읽기 변환
  compliance.py             송출 전 위반 소지 점검, 야간 제한
templates.json              안내문 양식
docs\                       계약서용 사용 제한 조항 문안
THIRD_PARTY_NOTICES.md      제3자 라이선스 고지
  audio.py                  재생 + 차임벨 합성
assets\chimes\              차임벨 WAV (자체 합성, 교체 가능)
  scheduler.py              예약 방송
  watcher.py                감시 폴더
  api_server.py             HTTP API + 웹 페이지
  qt_gui.py                 운영자 화면 (Qt / PySide6)
  gui.py                    예비 운영자 화면 (tkinter, PySide6 가 없을 때 자동 사용)
licenses\                   LGPL-3.0 / GPL-3.0 / LGPL-2.1 원문
plugins\                    사용자 엔진 플러그인
inbox\                      감시 폴더 (done / error)
logs\                       일자별 방송 로그 (90일 보관)
cache\                      합성 음성 캐시 (자동 정리)
```
