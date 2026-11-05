# 제3자 구성요소 및 라이선스 고지

이 제품은 다음 제3자 구성요소를 포함하거나 사용합니다. 각 구성요소의 저작권은 해당 저작권자에게 있습니다.

GitHub 저장소에는 소스 코드만 있으며, 표의 모델·패키지 파일은 들어 있지 않습니다. 표의 위치는 설치 패키지 기준입니다.

| 구성요소 | 저작권자 | 라이선스 | 위치 |
|---|---|---|---|
| Supertonic 3 음성 합성 모델 | Supertone Inc. | BigScience Open RAIL-M (사용 제한 조항 포함) | `models/supertonic3/` (`LICENSE` 동봉) |
| supertonic (Python 패키지) | Supertone Inc. | MIT | `offline_wheels/` |
| ONNX Runtime | Microsoft Corporation | MIT | `offline_wheels/` |
| NumPy | NumPy Developers | BSD-3-Clause | `offline_wheels/` |
| soundfile / libsndfile | Bastian Bechtold / Erik de Castro Lopo | BSD-3-Clause / LGPL-2.1 (`licenses/LGPL-2.1.txt`) | `offline_wheels/` |
| tqdm | tqdm developers | MPL-2.0 AND MIT | `offline_wheels/` |
| huggingface_hub 및 의존 패키지 | 각 저작권자 | Apache-2.0 / MIT / BSD 등 | `offline_wheels/` (각 wheel 내 라이선스 파일) |
| Python | Python Software Foundation | PSF License | `offline_wheels/python-3.11.9-amd64.exe` |
| Qt for Python (PySide6-Essentials 6.12.0, shiboken6 6.12.0) | The Qt Company Ltd. | LGPL-3.0 (LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only 중 LGPL-3.0 선택) | `offline_wheels/` |

빌드한 실행 파일에는 다음 구성요소도 들어갑니다: Pillow(MIT-CMU), certifi(MPL-2.0), charset-normalizer(MIT), Brotli(MIT), Tcl/Tk(TCL 라이선스), pywin32(PSF), Microsoft Visual C++ 런타임(Microsoft 재배포 조건). 실행 파일은 Nuitka로 컴파일하며, 포함되는 Nuitka 런타임에는 AGPL-3.0과 Nuitka Runtime Library Exception이 적용됩니다.

## Qt for Python (PySide6) — LGPL-3.0

이 제품의 운영자 화면은 Qt for Python(PySide6)을 사용하며, PySide6 와 Qt 라이브러리 및 그 사용은
GNU Lesser General Public License v3 (LGPL-3.0) 의 적용을 받습니다. Copyright (C) The Qt Company Ltd.

- 라이선스 원문: `licenses/LGPL-3.0.txt`, `licenses/GPL-3.0.txt`
- PySide6/Qt 는 수정하지 않았으며, 별도 라이브러리 파일(DLL·Python 패키지)로 실행 시 동적으로 불러옵니다.
  사용자는 인터페이스가 호환되는 다른 버전의 PySide6/Qt 로 교체해 사용할 수 있습니다.
- Qt 및 PySide6 의 소스 코드는 https://code.qt.io 및 https://download.qt.io 에서 받을 수 있습니다.
  폐쇄망 등으로 받을 수 없는 경우 요청 시 해당 버전의 소스 코드를 제공합니다.
- 이 제품의 사용 조건은 사용자가 위 라이브러리를 수정해 사용하거나 그 수정의 디버깅을 위해
  리버스 엔지니어링하는 것을 제한하지 않습니다.

## Supertonic 3 모델 사용 제한

모델은 https://huggingface.co/Supertone/supertonic-3 에서 받을 수 있으며 Open RAIL-M 라이선스 부속서 A의 사용 제한을 따릅니다. 요약은 `docs/AI음성_사용제한_조항(계약서용).md`,
전문은 `models/supertonic3/LICENSE` 를 참고하세요.

- 이 제품은 Supertone Inc.의 공식 제품이 아니며, Supertone Inc.의 보증·제휴를 의미하지 않습니다.
- 모델 파일은 수정하지 않았습니다.

## 차임벨 음원

`assets/chimes/` 의 차임벨과 경보음은 이 제품의 코드(`tts_broadcast/audio.py`, `tts_broadcast/alerts.py`)로 직접 합성한 음원이며 제3자 음원을 포함하지 않습니다.
