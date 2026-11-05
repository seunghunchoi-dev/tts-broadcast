"""Windows 내장 SAPI5 음성 엔진 (인터넷 불필요, 추가 설치 불필요).

PowerShell 프로세스를 하나 띄워 계속 재사용하므로 매 방송마다 기동 지연이 없습니다.
옵션:
  voice   : 음성 이름 (예: "Microsoft Heami Desktop"). 비우면 culture 로 자동 선택
  culture : 음성 자동 선택 언어 (기본 "ko-KR")
  rate    : 속도 -10 ~ 10 (기본 0)
  volume  : 음량 0 ~ 100 (기본 100)
  pitch   : 음높이 반음 단위 -6 ~ +6 (기본 0, 합성 후 처리 · numpy 필요)
"""
from __future__ import annotations

import base64
import json
import queue
import subprocess
import threading
from pathlib import Path

from .. import voicefx
from .base import EngineError, TTSEngine
from .registry import register_engine

_WORKER = Path(__file__).with_name("_sapi_worker.ps1")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@register_engine("sapi")
class SapiEngine(TTSEngine):

    def __init__(self, options=None, base_dir=None):
        super().__init__(options, base_dir)
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue = queue.Queue()

    def _ensure_worker(self) -> None:
        if self._proc and self._proc.poll() is None:
            return
        self._lines = queue.Queue()
        self._proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(_WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        threading.Thread(target=self._reader, args=(self._proc, self._lines),
                         daemon=True).start()

    @staticmethod
    def _reader(proc: subprocess.Popen, lines: queue.Queue) -> None:
        for raw in proc.stdout:
            lines.put(raw)
        lines.put(None)

    def _call(self, request: dict, timeout: float) -> dict:
        with self._lock:
            self._ensure_worker()
            payload = base64.b64encode(json.dumps(request).encode("utf-8")) + b"\n"
            try:
                self._proc.stdin.write(payload)
                self._proc.stdin.flush()
            except OSError as e:
                self._kill()
                raise EngineError(f"SAPI 워커 통신 실패: {e}") from e
            while True:
                try:
                    raw = self._lines.get(timeout=timeout)
                except queue.Empty:
                    self._kill()
                    raise EngineError("SAPI 응답 시간 초과")
                if raw is None:
                    self._kill()
                    raise EngineError("SAPI 워커가 종료되었습니다")
                try:
                    return json.loads(base64.b64decode(raw.strip()).decode("utf-8"))
                except ValueError:
                    continue  # 프로토콜 외 출력은 무시

    def _kill(self) -> None:
        if self._proc:
            try:
                self._proc.kill()
            except OSError:
                pass
            self._proc = None

    def synthesize(self, text: str, out_path: Path) -> None:
        o = self.options
        resp = self._call({
            "cmd": "speak",
            "text": text,
            "out": str(out_path),
            "voice": o.get("voice", ""),
            "culture": o.get("culture", "ko-KR"),
            "rate": int(o.get("rate", 0)),
            "volume": int(o.get("volume", 100)),
            "ssml": text.lstrip().startswith("<speak"),
        }, timeout=float(o.get("timeout", 120)))
        if not resp.get("ok"):
            raise EngineError(f"SAPI 합성 실패: {resp.get('error')}")
        pitch = float(o.get("pitch", 0) or 0)
        if pitch:
            try:
                voicefx.process_file(out_path, pitch=pitch)
            except ImportError as e:
                raise EngineError("음높이 조절에는 numpy 가 필요합니다 ('폐쇄망_설치.bat' 실행)") from e

    def list_voices(self) -> list[str]:
        resp = self._call({"cmd": "voices"}, timeout=30)
        voices = resp.get("voices") or []
        return [voices] if isinstance(voices, str) else list(voices)

    def close(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.stdin.close()
                    self._proc.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    self._kill()
            self._proc = None
