"""모든 TTS 엔진이 따라야 하는 공통 인터페이스."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class EngineError(RuntimeError):
    """엔진 초기화/합성 실패."""


class TTSEngine(ABC):
    """새 엔진을 만들려면 이 클래스를 상속하고 synthesize()만 구현하면 됩니다.

    - options : config.json 의 engines.<프로필>.options 값이 그대로 전달됩니다.
    - base_dir: 프로그램 폴더 (상대 경로 해석용)
    """

    engine_type = "base"

    def __init__(self, options: dict | None = None, base_dir: Path | None = None):
        self.options = dict(options or {})
        self.base_dir = Path(base_dir or Path.cwd())

    @abstractmethod
    def synthesize(self, text: str, out_path: Path) -> None:
        """text 를 음성으로 합성해 out_path 에 WAV(PCM) 파일로 저장."""

    def list_voices(self) -> list[str]:
        """선택 가능한 음성 목록 (지원하지 않으면 빈 목록)."""
        return []

    def close(self) -> None:
        """엔진이 사용하던 프로세스/리소스 정리."""

    def resolve(self, path: str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else self.base_dir / p
