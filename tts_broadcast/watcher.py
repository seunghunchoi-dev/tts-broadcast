"""감시 폴더 자동 방송: inbox 폴더에 .txt 파일을 넣으면 즉시 방송.

다른 시스템(출입통제, 화재수신기 연동 PC, 배치 작업 등)이 파일만 떨어뜨리면 되므로
네트워크가 없는 환경에서도 연동이 쉽습니다.
파일 맨 위에 옵션 줄을 넣을 수 있습니다 (선택):
  #priority=긴급      (긴급/높음/보통 또는 0~9)
  #repeat=2
  #chime=false
인코딩은 UTF-8 또는 CP949(ANSI) 자동 판별. 처리된 파일은 done/ 또는 error/ 로 이동합니다.
"""
from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from .broadcaster import Announcement, parse_bool, parse_priority

log = logging.getLogger(__name__)


def parse_message_file(raw: bytes, source: str) -> Announcement:
    for enc in ("utf-8-sig", "cp949"):
        try:
            content = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        content = raw.decode("utf-8", errors="replace")
    opts, body = {}, []
    for line in content.splitlines():
        s = line.strip()
        if not body and s.startswith("#") and "=" in s:
            k, v = s[1:].split("=", 1)
            opts[k.strip().lower()] = v.strip()
        else:
            body.append(line)
    return Announcement(text="\n".join(body).strip(),
                        priority=parse_priority(opts.get("priority")),
                        repeat=int(opts.get("repeat") or 1),
                        chime=parse_bool(opts.get("chime")),
                        source=source)


class FolderWatcher:
    def __init__(self, folder: Path, submit: Callable[[Announcement], Announcement],
                 poll_sec: float = 1.0):
        self.folder = folder
        self.submit = submit
        self.poll_sec = poll_sec
        self._stop = threading.Event()
        for sub in ("", "done", "error"):
            (folder / sub).mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        threading.Thread(target=self._run, name="watcher", daemon=True).start()
        log.info("감시 폴더: %s", self.folder)

    def stop(self) -> None:
        self._stop.set()

    def _move(self, path: Path, sub: str) -> None:
        dest = self.folder / sub / f"{time.strftime('%Y%m%d_%H%M%S')}_{path.name}"
        shutil.move(str(path), str(dest))

    def _run(self) -> None:
        while not self._stop.wait(self.poll_sec):
            files = sorted(self.folder.glob("*.txt"), key=lambda p: p.stat().st_mtime)
            for path in files:
                try:
                    if time.time() - path.stat().st_mtime < 0.5:
                        continue  # 아직 쓰는 중일 수 있음
                    ann = parse_message_file(path.read_bytes(), f"파일:{path.name}")
                    self.submit(ann)
                    self._move(path, "done")
                except PermissionError:
                    continue  # 다른 프로그램이 잠금 중 → 다음 주기에 재시도
                except Exception as e:
                    log.warning("감시 파일 처리 실패 %s: %s", path.name, e)
                    try:
                        self._move(path, "error")
                    except OSError:
                        pass
