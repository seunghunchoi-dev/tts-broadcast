"""Supertonic 3 (Supertone) 신경망 음성 엔진 — 자연스러운 한국어, 완전 오프라인(CPU, ONNX).

라이선스: 코드 MIT, 모델 OpenRAIL-M (사용 제한 조항 준수 조건으로 상업적 이용 가능,
models/supertonic3/LICENSE 참고).
필요 패키지: supertonic, onnxruntime, numpy (폐쇄망은 offline_wheels 로 설치)
옵션:
  model_dir : 모델 폴더 (기본 "models/supertonic3")
  model     : "supertonic-3" (기본) 또는 "supertonic-2"
  voice     : F1~F5(여성), M1~M5(남성) 또는 voice_styles 의 json 경로 (기본 "F1")
  lang      : 언어 코드 (기본 "ko")
  speed     : 말 빠르기 0.7 ~ 2.0 (기본 1.0)
  pitch     : 음높이 반음 단위 -6 ~ +6 (기본 0, 길이는 유지)
  steps     : 품질 단계 1~100 (기본 8, 높을수록 품질↑ 속도↓)
  silence   : 문장 덩어리 사이 무음 초 (기본 0.3)
  volume    : 음량 (기본 1.0 = 최대 -1dBFS 로 정규화, 1 초과 = 압축으로 더 크게, 최대 2.0)
  threads   : CPU 스레드 수 (기본 자동)
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from .. import voicefx
from .base import EngineError, TTSEngine
from .registry import register_engine

_REQUIRED = ["onnx/duration_predictor.onnx", "onnx/text_encoder.onnx",
             "onnx/vector_estimator.onnx", "onnx/vocoder.onnx",
             "onnx/tts.json", "onnx/unicode_indexer.json"]


@register_engine("supertonic")
class SupertonicEngine(TTSEngine):

    def __init__(self, options=None, base_dir=None):
        super().__init__(options, base_dir)
        # 폐쇄망: 허깅페이스 접속 시도 차단
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        try:
            import numpy  # noqa: F401
            import supertonic  # noqa: F401
        except ImportError as e:
            raise EngineError(f"Supertonic 패키지가 설치되지 않았습니다 ({e.name}). "
                              "'폐쇄망_설치.bat' 을 실행하세요.") from e
        self.model_dir = self.resolve(self.options.get("model_dir", "models/supertonic3"))
        missing = [f for f in _REQUIRED if not (self.model_dir / f).exists()]
        if missing:
            raise EngineError(f"Supertonic 모델 파일이 없습니다: {self.model_dir / missing[0]}")
        self._tts = None
        self._styles: dict = {}
        self._error: Exception | None = None
        self._ready = threading.Event()
        # 모델 로딩(수 초)은 백그라운드에서 진행 → 프로그램 시작이 늦어지지 않음
        threading.Thread(target=self._load, name="supertonic-load", daemon=True).start()

    def _load(self) -> None:
        try:
            from supertonic import TTS
            threads = self.options.get("threads")
            tts = TTS(model=self.options.get("model", "supertonic-3"),
                      model_dir=self.model_dir, auto_download=False,
                      intra_op_num_threads=int(threads) if threads else None)
            self._tts = tts
            self._style_for(str(self.options.get("voice") or "F1"))
        except Exception as e:
            self._error = e
        finally:
            self._ready.set()

    def _style_for(self, voice: str):
        """목소리 스타일 (한 번 읽은 것은 보관 → 목소리를 바꿔도 모델을 다시 읽지 않음)."""
        if voice not in self._styles:
            if voice.lower().endswith(".json"):
                self._styles[voice] = self._tts.get_voice_style_from_path(self.resolve(voice))
            else:
                self._styles[voice] = self._tts.get_voice_style(voice)
        return self._styles[voice]

    def _wait_ready(self):
        self._ready.wait()
        if self._error:
            raise EngineError(f"Supertonic 로딩 실패: {self._error}") from self._error
        return self._tts

    def _clean(self, tts, text: str) -> str:
        """모델이 읽지 못하는 문자는 오류 대신 제거."""
        ok, unsupported = tts.model.text_processor.validate_text(text)
        if not ok:
            for ch in unsupported:
                text = text.replace(ch, " ")
        return " ".join(text.split())

    def synthesize(self, text: str, out_path: Path) -> None:
        import numpy as np

        tts = self._wait_ready()
        o = self.options
        text = self._clean(tts, text)
        if not text:
            raise EngineError("읽을 수 있는 문자가 없습니다")
        sr = int(tts.sample_rate)
        speed = float(o.get("speed", 1.0))
        pitch = float(o.get("pitch", 0) or 0)
        r = voicefx.ratio(pitch)
        # 음높이: r 배 느리게 합성한 뒤 r 배 빠르게 재표본화 → 길이는 그대로, 음높이만 r 배
        # (엔진 허용 범위를 넘어 남는 빠르기 차이만 WSOLA 로 보정)
        synth_speed = min(2.0, max(0.7, speed / r))
        try:
            style = self._style_for(str(o.get("voice") or "F1"))
        except Exception as e:
            raise EngineError(f"목소리 '{o.get('voice')}' 를 읽을 수 없습니다: {e}") from e
        wav, _ = tts.synthesize(text, voice_style=style, lang=o.get("lang", "ko"),
                                speed=synth_speed,
                                total_steps=int(o.get("steps", 8)),
                                silence_duration=float(o.get("silence", 0.3)))
        pcm = wav.squeeze().astype(np.float64)
        if pitch:
            pcm = voicefx.resample(voicefx.time_stretch(pcm, synth_speed * r / speed, sr), r)
        voicefx.write_wav(out_path, voicefx.loudness(pcm, float(o.get("volume", 1.0))), sr)

    def list_voices(self) -> list[str]:
        return sorted(p.stem for p in (self.model_dir / "voice_styles").glob("*.json"))
