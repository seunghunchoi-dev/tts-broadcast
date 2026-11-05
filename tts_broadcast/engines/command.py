"""외부 실행파일 TTS 엔진 (Piper, sherpa-onnx, 자체 엔진 등 오프라인 TTS 연결용).

코드 수정 없이 config.json 만으로 다른 TTS 프로그램을 연결할 수 있습니다.
옵션:
  command  : 실행 인자 목록. 치환자 {out} {text} {text_file} 사용 가능
  stdin    : 표준입력으로 보낼 내용 템플릿 (예: "{text}"). 생략 시 보내지 않음
  encoding : stdin / text_file 인코딩 (기본 utf-8)
  timeout  : 초 (기본 120)
  required_files : 시작 시 존재 여부를 검사할 파일 목록 (모델 등)
예) Piper:
  "command": ["tools/piper/piper.exe", "--model", "models/voice.onnx", "--output_file", "{out}"],
  "stdin": "{text}",
  "required_files": ["models/voice.onnx", "models/voice.onnx.json"]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import EngineError, TTSEngine
from .registry import register_engine

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@register_engine("command")
class CommandEngine(TTSEngine):

    def __init__(self, options=None, base_dir=None):
        super().__init__(options, base_dir)
        template = self.options.get("command")
        if not template or not isinstance(template, list):
            raise EngineError("command 엔진: options.command (목록) 설정이 필요합니다")
        exe = self.resolve(str(template[0]))
        self._exe = str(exe) if exe.exists() else shutil.which(str(template[0]))
        if not self._exe:
            raise EngineError(f"실행 파일이 없습니다: {exe}")
        for f in self.options.get("required_files", []):
            if not self.resolve(f).exists():
                raise EngineError(f"필요한 파일이 없습니다: {self.resolve(f)}")

    def synthesize(self, text: str, out_path: Path) -> None:
        template = self.options["command"]
        encoding = self.options.get("encoding", "utf-8")
        values = {"{out}": str(out_path), "{text}": text}

        text_file = None
        if any("{text_file}" in str(a) for a in template):
            fd, text_file = tempfile.mkstemp(suffix=".txt")
            with os.fdopen(fd, "w", encoding=encoding) as f:
                f.write(text)
            values["{text_file}"] = text_file

        def fill(s: str) -> str:
            for k, v in values.items():
                s = s.replace(k, v)
            return s

        args = [fill(str(a)) for a in template]
        args[0] = self._exe
        stdin_tpl = self.options.get("stdin")
        stdin_data = fill(stdin_tpl).encode(encoding) if stdin_tpl else None

        try:
            result = subprocess.run(
                args, input=stdin_data, cwd=str(self.base_dir),
                capture_output=True, timeout=float(self.options.get("timeout", 120)),
                creationflags=_NO_WINDOW)
        except FileNotFoundError as e:
            raise EngineError(f"실행 파일을 찾을 수 없습니다: {args[0]}") from e
        except subprocess.TimeoutExpired as e:
            raise EngineError("외부 TTS 실행 시간 초과") from e
        finally:
            if text_file:
                os.unlink(text_file)

        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()[-500:]
            raise EngineError(f"외부 TTS 오류 (코드 {result.returncode}): {err}")
        if not Path(out_path).exists() or Path(out_path).stat().st_size == 0:
            raise EngineError("외부 TTS 가 출력 WAV 파일을 만들지 않았습니다")
