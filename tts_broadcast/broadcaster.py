"""방송 대기열 및 송출 처리 (우선순위, 긴급 끼어들기, 반복, 차임, 캐시)."""
from __future__ import annotations

import hashlib
import heapq
import itertools
import json
import logging
import queue
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import audio
from .config import resolve_path
from .engines import EngineError, TTSEngine
from .compliance import check as compliance_check
from .compliance import in_quiet_hours
from .textnorm import normalize

log = logging.getLogger(__name__)

PRIORITY_EMERGENCY = 0
PRIORITY_HIGH = 1
PRIORITY_NORMAL = 5
PRIORITY_NAMES = {PRIORITY_EMERGENCY: "긴급", PRIORITY_HIGH: "높음", PRIORITY_NORMAL: "보통"}
_PRIORITY_ALIASES = {
    "긴급": 0, "emergency": 0, "urgent": 0,
    "높음": 1, "high": 1,
    "보통": 5, "normal": 5,
}


def parse_priority(value) -> int:
    if value is None or value == "":
        return PRIORITY_NORMAL
    if isinstance(value, str) and value.strip().lower() in _PRIORITY_ALIASES:
        return _PRIORITY_ALIASES[value.strip().lower()]
    return max(0, min(9, int(value)))


def parse_bool(value) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y", "예")


@dataclass
class Announcement:
    text: str
    priority: int = PRIORITY_NORMAL
    repeat: int = 1
    chime: bool | None = None          # None = 설정 기본값 사용
    source: str = "manual"
    wrap: bool = True                  # 시설 머리말/맺음말 붙이기
    confirmed: bool = False            # 운영자가 점검 경고를 확인하고 송출함
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "priority": self.priority,
                "priority_name": PRIORITY_NAMES.get(self.priority, str(self.priority)),
                "repeat": self.repeat, "source": self.source,
                "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.created))}


Listener = Callable[[str, "Announcement | None", str], None]


class Broadcaster:
    """events: queued / start / done / interrupted / stopped / error / engine / cleared"""

    def __init__(self, engine: TTSEngine, engine_key: str, settings: dict, cache_dir: Path,
                 fallback_factory: Callable[[], tuple[str, TTSEngine]] | None = None,
                 facility: dict | None = None):
        self.settings = settings
        self.facility = facility if facility is not None else {}
        self._disclosed_on = ""
        self._fallback_factory = fallback_factory
        self._fallback: tuple[str, TTSEngine] | None = None
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._engine = engine
        self._engine_key = engine_key
        self._engine_lock = threading.Lock()
        self._q: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self._front_seq = itertools.count(-1, -1)
        self._stop_play = threading.Event()
        self._stop_reason = ""
        self._shutdown = threading.Event()
        self._listeners: list[Listener] = []
        self._thread: threading.Thread | None = None
        self.current: Announcement | None = None
        self.history: list[tuple[str, str, dict]] = []
        self.reload_chimes()

    # ---------- 공개 API ----------
    def reload_chimes(self) -> None:
        """설정의 차임 파일을 적용. 파일이 없으면 기본 차임을 합성해 사용."""
        for attr, key, preset in (("_chime_start", "chime_start_file", "4tone_up"),
                                  ("_chime_end", "chime_end_file", "4tone_down")):
            path = resolve_path(self.settings.get(key) or f"assets/chimes/{preset}.wav")
            if not path.exists():
                log.warning("차임 파일 없음: %s → 기본 차임 생성", path)
                path = self.cache_dir / f"_{preset}.wav"
                if not path.exists():
                    audio.generate_chime(path, preset)
            setattr(self, attr, path)
        # 긴급 방송 경보음 ("" 이면 일반 차임 사용)
        f = self.emergency.get("chime_file", "assets/chimes/emergency.wav")
        self._chime_emergency = None
        if f:
            path = resolve_path(f)
            if not path.exists():
                log.warning("긴급 경보음 파일 없음: %s → 기본 경보음 생성", path)
                path = self.cache_dir / "_emergency.wav"
                if not path.exists():
                    try:
                        audio.generate_alert(path)
                    except ImportError:  # numpy 없음 → 일반 차임 사용
                        log.warning("경보음을 만들 수 없어 일반 차임을 사용합니다 (numpy 없음)")
                        return
            self._chime_emergency = path

    @property
    def emergency(self) -> dict:
        return self.settings.get("emergency") or {}

    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    @property
    def engine_key(self) -> str:
        return self._engine_key

    @property
    def engine(self) -> TTSEngine:
        return self._engine

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="broadcaster", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._shutdown.set()
        self._stop_reason = "shutdown"
        self._stop_play.set()
        self._q.put((-99, 0, None))
        if self._thread:
            self._thread.join(timeout=5)
        with self._engine_lock:
            self._engine.close()
            if self._fallback:
                self._fallback[1].close()

    def submit(self, ann: Announcement) -> Announcement:
        ann.text = (ann.text or "").strip()
        if not ann.text:
            raise ValueError("방송 문구가 비어 있습니다")
        max_chars = int(self.settings.get("max_chars", 2000))
        if len(ann.text) > max_chars:
            raise ValueError(f"방송 문구가 너무 깁니다 (최대 {max_chars}자)")
        if not ann.confirmed:
            # 자동 송출 경로(예약/감시폴더/API)는 운영자 확인이 없으므로 여기서 점검
            if ann.priority > PRIORITY_EMERGENCY and in_quiet_hours(self.facility):
                self._reject(ann, "야간 방송 제한 시간이라 송출하지 않았습니다 (긴급 방송만 허용)")
            findings = compliance_check(ann.text)
            blocks = [f.title for f in findings if f.level == "block"]
            if blocks:
                self._reject(ann, "송출 차단: " + ", ".join(blocks))
            if findings:
                self._emit("warning", ann, "점검 경고: " + ", ".join(f.title for f in findings))
        max_repeat = int(self.settings.get("max_repeat", 10))
        ann.repeat = max(1, min(max_repeat, int(ann.repeat)))
        if ann.priority == PRIORITY_EMERGENCY:
            # 긴급 방송은 최소 반복 횟수 보장 (못 들은 사람이 없도록)
            ann.repeat = max(ann.repeat, min(max_repeat, int(self.emergency.get("min_repeat", 1))))
        self._q.put((ann.priority, next(self._seq), ann))
        self._emit("queued", ann, "")
        cur = self.current
        if (cur and ann.priority == PRIORITY_EMERGENCY and cur.priority > PRIORITY_EMERGENCY
                and self.settings.get("interrupt_on_emergency", True)):
            self._stop_reason = "emergency"
            self._stop_play.set()
        return ann

    def _reject(self, ann: Announcement, reason: str) -> None:
        self._emit("rejected", ann, reason)
        raise ValueError(reason)

    def compose(self, ann: Announcement, consume: bool = False) -> str:
        """AI 음성 고지·시설 머리말/맺음말을 붙인 실제 송출 문구.
        consume=True 는 실제 송출 시에만 사용 ('하루 첫 방송' 고지 처리)."""
        return " ".join(p for p in self.compose_parts(ann, consume) if p)

    def compose_parts(self, ann: Announcement, consume: bool = False) -> tuple[str, str, str]:
        """(머리 = 고지+머리말, 본문, 맺음말). 반복 송출 시 본문만 반복한다."""
        f = self.facility
        if ann.text.lstrip().startswith("<speak"):
            return "", ann.text, ""
        prefix = (self.emergency.get("prefix") or "").strip() if ann.priority == PRIORITY_EMERGENCY else ""
        if not ann.wrap:
            return prefix, ann.text, ""
        name = f.get("name", "")
        head = [prefix]
        mode = f.get("disclosure_mode", "notice")
        today = time.strftime("%Y-%m-%d")
        if mode == "every" or (mode == "daily_first" and self._disclosed_on != today):
            head.append(f.get("disclosure_text", "AI 음성 안내 방송입니다."))
            if consume:
                self._disclosed_on = today
        if f.get("intro_enabled") and (ann.priority > PRIORITY_EMERGENCY or f.get("intro_on_emergency", True)):
            head.append(f.get("intro", "").replace("{시설}", name))
        tail = f.get("outro", "").replace("{시설}", name).strip() if f.get("outro_enabled") else ""
        return " ".join(p.strip() for p in head if p.strip()), ann.text.strip(), tail

    def stop_current(self) -> None:
        if self.current:
            self._stop_reason = "user"
            self._stop_play.set()

    def cancel_source(self, source: str) -> int:
        """해당 출처(예: "테스트")의 대기 방송을 지우고, 송출 중이면 즉시 중단. 다른 방송은 건드리지 않음."""
        with self._q.mutex:
            keep = [it for it in self._q.queue if it[2] is None or it[2].source != source]
            n = len(self._q.queue) - len(keep)
            self._q.queue[:] = keep
            heapq.heapify(self._q.queue)
        cur = self.current
        if cur and cur.source == source:
            self.stop_current()
        return n

    def clear_queue(self) -> int:
        n = 0
        while True:
            try:
                self._q.get_nowait()
                n += 1
            except queue.Empty:
                break
        self._emit("cleared", None, f"{n}건 삭제")
        return n

    def pending(self) -> list[Announcement]:
        with self._q.mutex:
            items = sorted(self._q.queue, key=lambda x: (x[0], x[1]))
        return [a for _, _, a in items if a is not None]

    def set_engine(self, key: str, engine: TTSEngine) -> None:
        with self._engine_lock:
            old = self._engine
            self._engine, self._engine_key = engine, key
        old.close()
        self._emit("engine", None, f"엔진 변경: {key} ({engine.engine_type})")

    def tune_engine(self, options: dict) -> None:
        """엔진을 다시 만들지 않고 합성 시 읽는 옵션(빠르기·음높이·음량 등)만 교체."""
        with self._engine_lock:
            self._engine.options = dict(options)
        self._emit("engine", None, f"음성 조절 변경: {self._engine_key}")

    def synthesize_to(self, text: str, gain: float = 1.0) -> Path:
        """합성만 수행 (캐시 사용). 같은 문구/엔진/옵션이면 재합성하지 않음.
        현재 엔진이 실패하면 예비 엔진(broadcast.fallback_engine)으로 합성.
        gain != 1 이면 음량을 강조한 사본을 돌려줌 (긴급 방송)."""
        path = self._synthesize(text)
        if abs(gain - 1.0) < 0.01:
            return path
        boosted = path.with_name(f"{path.stem}_v{round(gain * 100)}.wav")
        if not boosted.exists():
            tmp = boosted.with_suffix(".tmp.wav")
            try:
                from . import voicefx
                shutil.copyfile(path, tmp)
                voicefx.process_file(tmp, volume=gain)
                tmp.replace(boosted)
            except Exception:
                log.exception("음량 강조 실패 → 원래 음량으로 송출")
                tmp.unlink(missing_ok=True)
                return path
        return boosted

    def _synthesize(self, text: str) -> Path:
        if self.settings.get("normalize_text", True) and not text.lstrip().startswith("<speak"):
            text = normalize(text)
        with self._engine_lock:
            try:
                path = self._synth(self._engine, self._engine_key, text)
            except Exception as e:
                fallback = self._get_fallback()
                if fallback is None:
                    raise
                self._emit("fallback", None,
                           f"엔진 '{self._engine_key}' 실패 → 예비 엔진 '{fallback[0]}' 사용 ({e})")
                path = self._synth(fallback[1], fallback[0], text)
        self._prune_cache()
        return path

    def _synth(self, engine: TTSEngine, key: str, text: str) -> Path:
        sig = json.dumps([key, engine.engine_type, engine.options, text],
                         ensure_ascii=False, sort_keys=True)
        path = self.cache_dir / (hashlib.sha1(sig.encode("utf-8")).hexdigest() + ".wav")
        if path.exists() and path.stat().st_size > 44:
            path.touch()
            return path
        tmp = path.with_suffix(".tmp.wav")
        engine.synthesize(text, tmp)
        tmp.replace(path)
        return path

    def reset_fallback(self) -> None:
        """예비 엔진 설정이 바뀌었을 때 다음 실패 시 새로 만들도록 초기화."""
        with self._engine_lock:
            if self._fallback:
                self._fallback[1].close()
            self._fallback = None

    def _get_fallback(self) -> tuple[str, TTSEngine] | None:
        if self._fallback is None and self._fallback_factory:
            try:
                self._fallback = self._fallback_factory()
            except EngineError:
                return None  # 예비 엔진 사용 안 함
            except Exception:
                log.exception("예비 엔진 생성 실패")
                return None
        if self._fallback and self._fallback[0] == self._engine_key:
            return None
        return self._fallback

    # ---------- 내부 ----------
    def _emit(self, kind: str, ann: Announcement | None, msg: str) -> None:
        entry = (time.strftime("%Y-%m-%d %H:%M:%S"), kind, ann.to_dict() if ann else {"msg": msg})
        self.history.append(entry)
        del self.history[:-500]
        text = ann.text.replace("\n", " ")[:80] if ann else ""
        log.info("[%s] %s %s %s", kind, f"#{ann.id}({ann.source})" if ann else "", text, msg)
        for fn in list(self._listeners):
            try:
                fn(kind, ann, msg)
            except Exception:
                log.exception("listener 오류")

    def _prune_cache(self) -> None:
        limit = int(self.settings.get("cache_max_files", 300))
        files = [p for p in self.cache_dir.glob("*.wav") if not p.name.startswith("_")]
        if len(files) <= limit:
            return
        files.sort(key=lambda p: p.stat().st_mtime)
        for p in files[: len(files) - limit]:
            try:
                p.unlink()
            except OSError:
                pass

    def _run(self) -> None:
        while not self._shutdown.is_set():
            try:
                _, _, ann = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if ann is None or self._shutdown.is_set():
                break
            self._broadcast(ann)

    def _play(self, path: Path) -> bool:
        return audio.play_wav(path, self._stop_play)

    def _broadcast(self, ann: Announcement) -> None:
        self._stop_play.clear()
        self._stop_reason = ""
        self.current = ann  # 중지 요청이 지워지지 않도록 초기화 뒤에 설정
        s = self.settings
        try:
            emg = ann.priority == PRIORITY_EMERGENCY
            chime = s.get("chime_start", True) if ann.chime is None else ann.chime
            start_chime = self._chime_start
            gain = 1.0
            if emg:
                # 긴급: 일반 차임 대신 경보음 (차임을 끈 설정이어도 경보음은 울림), 음량 강조
                if self._chime_emergency:
                    start_chime = self._chime_emergency
                    chime = True if ann.chime is None else ann.chime
                gain = float(self.emergency.get("volume", 1.0) or 1.0)
            head, body, tail = self.compose_parts(ann, consume=True)
            # 고지·머리말은 첫 회에만, 맺음말은 마지막 회 뒤에 한 번만 송출
            texts = {"first": " ".join(p for p in (head, body) if p)}
            if ann.repeat > 1:
                texts["body"] = body
            if tail:
                texts["tail"] = tail
            wavs: dict = {}

            def synth(keys):
                for k in keys:
                    try:
                        wavs[k] = self.synthesize_to(texts[k], gain)
                    except Exception as e:
                        wavs[k] = e

            def get(k, worker):
                worker.join()
                if isinstance(wavs[k], Exception):
                    raise wavs[k]
                return wavs[k]

            # 차임벨이 울리는 동안 첫 음성을 합성하고, 첫 음성이 나가는 동안 나머지를 합성
            first = threading.Thread(target=synth, args=(["first"],), daemon=True)
            first.start()
            if self._stop_play.is_set():
                ok = False
            else:
                self._emit("start", ann, "")
                ok = self._play(start_chime) if chime else True
            first_wav = get("first", first)
            rest = threading.Thread(target=synth, args=([k for k in texts if k != "first"],), daemon=True)
            rest.start()
            if ok:
                for i in range(ann.repeat):
                    if i > 0 and self._stop_play.wait(float(s.get("repeat_gap_sec", 1.5))):
                        ok = False
                        break
                    ok = self._play(first_wav if i == 0 else get("body", rest))
                    if not ok:
                        break
                if ok and tail:
                    ok = self._play(get("tail", rest))
                # 긴급 방송은 사이렌 뒤 부드러운 종료 차임이 어울리지 않아 생략
                if ok and chime and s.get("chime_end", False) and not emg:
                    self._play(self._chime_end)
            rest.join()
            if ok:
                self._emit("done", ann, "")
            elif self._stop_reason == "emergency":
                self._emit("interrupted", ann, "긴급 방송으로 중단")
                if s.get("requeue_interrupted", True):
                    self._q.put((ann.priority, next(self._front_seq), ann))
            else:
                self._emit("stopped", ann, "사용자 중지")
        except Exception as e:
            log.exception("방송 실패")
            self._emit("error", ann, str(e))
        finally:
            self.current = None
