"""설정 파일(config.json) 로드/저장."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

# exe 로 빌드된 경우(PyInstaller=sys.frozen, Nuitka=__compiled__) exe 가 있는 폴더 기준
_FROZEN = getattr(sys, "frozen", False) or ("__compiled__" in globals())
ROOT = (Path(sys.executable).resolve().parent if _FROZEN
        else Path(__file__).resolve().parent.parent)

DEFAULTS: dict = {
    "active_engine": "supertonic_korean",
    "engines": {
        "supertonic_korean": {
            "type": "supertonic",
            "options": {"model_dir": "models/supertonic3", "voice": "F1", "lang": "ko",
                        "speed": 1.0, "steps": 8},
        },
        "windows_korean": {
            "type": "sapi",
            "options": {"voice": "", "culture": "ko-KR", "rate": 0, "volume": 100},
        },
    },
    "broadcast": {
        "fallback_engine": "windows_korean",
        "normalize_text": True,
        "chime_start_file": "assets/chimes/4tone_up.wav",
        "chime_end_file": "assets/chimes/4tone_down.wav",
        "chime_start": True,
        "chime_end": False,
        "repeat_gap_sec": 1.5,
        "interrupt_on_emergency": True,
        "requeue_interrupted": True,
        "max_repeat": 10,
        "max_chars": 2000,
        "cache_max_files": 300,
        # 긴급 방송: 경보음("" = 일반 차임), 앞머리 문구, 최소 반복 횟수, 음량 강조(1.0 = 일반과 같음)
        "emergency": {
            "chime_file": "assets/chimes/emergency.wav",
            "prefix": "긴급 안내 말씀 드립니다.",
            "min_repeat": 2,
            "volume": 1.3,
        },
    },
    "facility": {
        "name": "OO아파트 관리사무소",
        "intro_enabled": True,
        "intro": "{시설}에서 알려 드립니다.",
        # AI 음성 고지: notice(게시물로 대체) / every(매 방송) / daily_first(하루 첫 방송)
        "disclosure_mode": "notice",
        "disclosure_text": "AI 음성 안내 방송입니다.",
        "notice_posted": "",
        "intro_on_emergency": True,
        "outro_enabled": False,
        "outro": "이상 {시설}에서 알려 드렸습니다.",
        "quiet_hours": {"enabled": False, "start": "22:00", "end": "07:00"},
    },
    "templates_file": "templates.json",
    "license_accepted": "",
    "watch_folder": {"enabled": True, "path": "inbox", "poll_sec": 1.0},
    "api": {"enabled": True, "host": "127.0.0.1", "port": 8765, "token": ""},
    "schedules_file": "schedules.json",
    "presets": [
        "오늘은 분리수거일입니다. 재활용품은 지정된 장소에 분리하여 배출해 주시기 바랍니다.",
        "늦은 시간 층간소음으로 이웃 간 불편이 발생하고 있습니다. 서로 배려하는 마음으로 소음을 자제해 주시기 바랍니다.",
        "공동 현관 앞 불법 주차로 긴급 차량 통행이 어렵습니다. 지정된 주차 구역에 주차해 주시기 바랍니다.",
        "단지 내 도로에서는 서행해 주시고, 어린이 안전에 각별히 유의해 주시기 바랍니다.",
    ],
    # 발음 사전 {표기: 읽기} — 예) {"parking": "파킹", "OO단지": "오오단지"}
    "pronunciations": {},
    "log_dir": "logs",
    "cache_dir": "cache",
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "engines":
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8-sig") as f:
            return _merge(DEFAULTS, json.load(f))
    cfg = copy.deepcopy(DEFAULTS)
    save_config(path, cfg)
    return cfg


def save_config(path: Path, cfg: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def resolve_path(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else ROOT / path
