"""구성요소 조립: 엔진 + 방송 대기열 + 예약 + 감시 폴더 + HTTP API."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from .broadcaster import Broadcaster
from .config import ROOT, load_config, resolve_path, save_config
from .engines import EngineError, TTSEngine, create_engine, load_plugins
from .textnorm import set_lexicon

log = logging.getLogger(__name__)

# 합성할 때마다 읽는 옵션 (바꿔도 엔진을 다시 만들 필요 없음)
LIVE_OPTIONS = {"voice", "speed", "pitch", "volume", "rate", "steps", "silence"}


class UnavailableEngine(TTSEngine):
    """주 엔진이 실패했고 예비 엔진도 없을 때 자리만 채우는 엔진 (방송 시 오류)."""
    engine_type = "unavailable"

    def synthesize(self, text, out_path):
        raise EngineError(f"사용 가능한 음성 엔진이 없습니다: {self.options.get('reason')}")


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = logging.handlers.TimedRotatingFileHandler(
        log_dir / "broadcast.log", when="midnight", backupCount=90, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if sys.stderr:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)


class App:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = load_config(config_path)
        setup_logging(resolve_path(self.config["log_dir"]))
        set_lexicon(self.config.get("pronunciations"))
        load_plugins(ROOT / "plugins")

        key = self.config["active_engine"]
        try:
            engine = self.build_engine(key)
        except Exception as e:
            try:
                key, engine = self._fallback_engine()
                log.error("엔진 '%s' 초기화 실패 (%s) → 예비 엔진 '%s' 사용",
                          self.config["active_engine"], e, key)
            except EngineError:
                key, engine = "(엔진 없음)", UnavailableEngine({"reason": str(e)})
                log.error("엔진 '%s' 초기화 실패 (%s), 예비 엔진 사용 안 함 → 방송 불가",
                          self.config["active_engine"], e)

        self.broadcaster = Broadcaster(engine, key, self.config["broadcast"],
                                       resolve_path(self.config["cache_dir"]),
                                       self._fallback_engine, self.config["facility"])
        from .scheduler import Scheduler
        self.scheduler = Scheduler(resolve_path(self.config["schedules_file"]),
                                   self.broadcaster.submit)
        self.watcher = None
        wf = self.config["watch_folder"]
        if wf.get("enabled"):
            from .watcher import FolderWatcher
            self.watcher = FolderWatcher(resolve_path(wf["path"]), self.broadcaster.submit,
                                         float(wf.get("poll_sec", 1.0)))
        self.api = None
        api = self.config["api"]
        if api.get("enabled"):
            from .api_server import ApiServer
            try:
                self.api = ApiServer(self.broadcaster, api["host"], int(api["port"]),
                                     api.get("token", ""))
            except OSError:
                log.exception("HTTP API 시작 실패 (포트 %s 사용 중?)", api["port"])

    def build_engine(self, key: str) -> TTSEngine:
        profile = self.config["engines"].get(key)
        if profile is None:
            raise KeyError(f"engines 에 '{key}' 프로필이 없습니다")
        return create_engine(profile["type"], profile.get("options", {}), ROOT)

    def _fallback_engine(self) -> tuple[str, TTSEngine]:
        """예비 엔진: broadcast.fallback_engine 프로필.
        "" 이면 사용 안 함(EngineError), 없는 프로필이면 Windows 기본 한국어 음성."""
        key = self.config["broadcast"].get("fallback_engine") or ""
        if not key:
            raise EngineError("예비 엔진 사용 안 함")
        if key in self.config["engines"]:
            try:
                return key, self.build_engine(key)
            except Exception:
                log.exception("예비 엔진 '%s' 생성 실패", key)
        return "sapi(기본)", create_engine("sapi", {"culture": "ko-KR"}, ROOT)

    def set_fallback(self, key: str) -> None:
        """예비 엔진 변경 ("" = 사용 안 함)."""
        self.config["broadcast"]["fallback_engine"] = key
        self.broadcaster.reset_fallback()
        self.save()
        log.info("예비 엔진 변경: %s", key or "사용 안 함")

    def switch_engine(self, key: str, options: dict | None = None) -> None:
        """엔진 프로필 전환 (옵션 변경 시 config.json 에 저장)."""
        if options is not None and key == self.broadcaster.engine_key:
            old = self.config["engines"][key].get("options", {})
            changed = {k for k in set(old) | set(options) if old.get(k) != options.get(k)}
            # 목소리는 합성 때마다 읽는 내장 엔진만 즉시 적용 (플러그인 엔진은 다시 생성)
            live = LIVE_OPTIONS if self.broadcaster.engine.engine_type in ("supertonic", "sapi") \
                else LIVE_OPTIONS - {"voice"}
            if changed <= live:
                # 빠르기·음높이·음량만 바뀜 → 모델 재로딩 없이 즉시 적용
                self.config["engines"][key]["options"] = options
                self.broadcaster.tune_engine(options)
                self.save()
                return
        if options is not None:
            self.config["engines"][key]["options"] = options
        engine = self.build_engine(key)
        self.broadcaster.set_engine(key, engine)
        self.config["active_engine"] = key
        self.save()

    def set_pronunciations(self, entries: dict[str, str]) -> None:
        """발음 사전 변경 (즉시 적용·저장)."""
        self.config["pronunciations"] = entries
        set_lexicon(entries)
        self.save()
        log.info("발음 사전 변경: %d건", len(entries))

    def save(self) -> None:
        save_config(self.config_path, self.config)

    def start(self) -> None:
        self.broadcaster.start()
        self.scheduler.start()
        if self.watcher:
            self.watcher.start()
        if self.api:
            self.api.start()
        log.info("방송 시스템 시작 (엔진: %s)", self.broadcaster.engine_key)

    def shutdown(self) -> None:
        self.scheduler.stop()
        if self.watcher:
            self.watcher.stop()
        if self.api:
            self.api.stop()
        self.broadcaster.shutdown()
        log.info("방송 시스템 종료")
