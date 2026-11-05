"""예약 방송 (지정 시각 / 요일 / 날짜 / 일정 간격).

schedules.json 항목 예:
  {"id": "a1", "enabled": true, "name": "점심 안내", "text": "점심시간입니다.",
   "type": "time", "time": "12:00", "days": [0,1,2,3,4], "date": "",
   "priority": 5, "repeat": 2, "chime": true}
  {"id": "b2", "enabled": true, "name": "정기 안내", "text": "...",
   "type": "interval", "interval_min": 30, "start": "09:00", "end": "18:00", "days": []}
days: 0=월 ~ 6=일, 비어 있으면 매일.  date: "YYYY-MM-DD" 지정 시 그 날만.
파일을 직접 수정해도 자동으로 다시 읽습니다.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from .broadcaster import Announcement, parse_bool, parse_priority

log = logging.getLogger(__name__)

DAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]


def _minutes(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)


def is_due(item: dict, now: datetime) -> bool:
    if not item.get("enabled", True):
        return False
    days = item.get("days") or []
    if days and now.weekday() not in days:
        return False
    if item.get("date") and item["date"] != now.strftime("%Y-%m-%d"):
        return False
    cur = now.hour * 60 + now.minute
    if item.get("type", "time") == "interval":
        interval = int(item.get("interval_min", 0))
        start = _minutes(item.get("start") or "00:00")
        end = _minutes(item.get("end") or "23:59")
        return interval > 0 and start <= cur <= end and (cur - start) % interval == 0
    return cur == _minutes(item["time"])


def describe(item: dict) -> str:
    days = item.get("days") or []
    day_txt = "매일" if not days else ",".join(DAY_NAMES[d] for d in days)
    if item.get("date"):
        day_txt = item["date"]
    if item.get("type") == "interval":
        return f"{day_txt} {item.get('start')}~{item.get('end')} {item.get('interval_min')}분마다"
    return f"{day_txt} {item.get('time')}"


class Scheduler:
    def __init__(self, path: Path, submit: Callable[[Announcement], Announcement]):
        self.path = path
        self.submit = submit
        self._lock = threading.Lock()
        self._items: list[dict] = []
        self._mtime = 0.0
        self._fired: dict[str, str] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._items = []
            self._save_locked()
            return
        try:
            with open(self.path, encoding="utf-8-sig") as f:
                items = json.load(f)
            for it in items:
                it.setdefault("id", uuid.uuid4().hex[:8])
            self._items = items
            self._mtime = self.path.stat().st_mtime
            log.info("예약 %d건 로드", len(items))
        except (OSError, ValueError, KeyError):
            log.exception("예약 파일 읽기 실패: %s", self.path)

    def _save_locked(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._items, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)
        self._mtime = self.path.stat().st_mtime

    def items(self) -> list[dict]:
        with self._lock:
            return [dict(i) for i in self._items]

    def add(self, item: dict) -> dict:
        item = dict(item)
        item.setdefault("id", uuid.uuid4().hex[:8])
        item.setdefault("enabled", True)
        if item.get("type", "time") == "time":
            _minutes(item["time"])  # 형식 검증
        else:
            _minutes(item.get("start") or "00:00")
            _minutes(item.get("end") or "23:59")
        with self._lock:
            self._items.append(item)
            self._save_locked()
        return item

    def remove(self, item_id: str) -> None:
        with self._lock:
            self._items = [i for i in self._items if i["id"] != item_id]
            self._save_locked()

    def update(self, item_id: str, **changes) -> None:
        with self._lock:
            for i in self._items:
                if i["id"] == item_id:
                    i.update(changes)
            self._save_locked()

    def fire(self, item: dict) -> Announcement:
        return self.submit(Announcement(
            text=item["text"], priority=parse_priority(item.get("priority")),
            repeat=int(item.get("repeat", 1)), chime=parse_bool(item.get("chime")),
            source=f"예약:{item.get('name') or item['id']}"))

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop.wait(1.0):
            try:
                if self.path.exists() and self.path.stat().st_mtime != self._mtime:
                    with self._lock:
                        self._load()
                now = datetime.now()
                key = now.strftime("%Y-%m-%d %H:%M")
                for item in self.items():
                    if self._fired.get(item["id"]) == key:
                        continue
                    try:
                        due = is_due(item, now)
                    except (ValueError, KeyError):
                        log.warning("예약 형식 오류: %s", item)
                        self._fired[item["id"]] = key
                        continue
                    if due:
                        self._fired[item["id"]] = key
                        try:
                            self.fire(item)
                        except ValueError:
                            pass  # 야간 제한·점검 차단 등 (방송 기록에 사유 표시됨)
            except Exception:
                log.exception("스케줄러 오류")
