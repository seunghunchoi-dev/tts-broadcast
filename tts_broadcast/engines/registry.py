"""엔진 등록/생성. 엔진 교체는 config.json 의 active_engine 만 바꾸면 됩니다."""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path

from .base import EngineError, TTSEngine

log = logging.getLogger(__name__)

_REGISTRY: dict[str, type[TTSEngine]] = {}


def register_engine(name: str):
    """엔진 클래스 데코레이터.  @register_engine("my_engine")"""

    def deco(cls: type[TTSEngine]) -> type[TTSEngine]:
        cls.engine_type = name
        _REGISTRY[name] = cls
        return cls

    return deco


def available_engines() -> list[str]:
    return sorted(_REGISTRY)


def create_engine(engine_type: str, options: dict | None = None,
                  base_dir: Path | None = None) -> TTSEngine:
    """engine_type 은 등록 이름("sapi") 또는 "모듈경로:클래스명" 형식."""
    if ":" in engine_type:
        module_name, cls_name = engine_type.split(":", 1)
        cls = getattr(importlib.import_module(module_name), cls_name)
    else:
        cls = _REGISTRY.get(engine_type)
        if cls is None:
            raise EngineError(
                f"알 수 없는 엔진 '{engine_type}'. 사용 가능: {', '.join(available_engines())}")
    return cls(options or {}, base_dir)


def load_plugins(folder: Path) -> None:
    """plugins 폴더의 *.py 를 불러와 엔진을 자동 등록 (_로 시작하는 파일은 무시)."""
    if not folder.is_dir():
        return
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        name = f"tts_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            log.info("플러그인 로드: %s", path.name)
        except Exception:
            log.exception("플러그인 로드 실패: %s", path.name)
