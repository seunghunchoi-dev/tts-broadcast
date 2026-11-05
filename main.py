# ============================================================================
#  TTS 자동 방송 송출 시스템  —  실행 진입점
#  Copyright (c) 2026 최승훈 (Choi Seung-hun). All rights reserved.
#  본 프로그램 코드는 최승훈의 독점 저작물입니다. 무단 복제·배포·역컴파일 금지.
# ============================================================================
"""TTS 자동 방송 송출 프로그램 실행 진입점.

  python main.py                 방송 프로그램 (창을 닫아도 트레이에서 계속 방송)
  python main.py --tray          창 없이 트레이에서 시작 (Windows 시작 시 자동 실행용, 예전 --headless)
  python main.py --say "문구"     한 번 방송하고 종료 (프로그램이 켜져 있으면 그 대기열로 전달)

  한 PC 에서는 하나만 실행됩니다. 이미 켜져 있으면 기존 창을 앞으로 불러옵니다.
  python main.py --list-engines  등록된 엔진 종류
  python main.py --list-voices   현재 엔진의 음성 목록
  python main.py --reading "문구" 숫자 등을 실제로 어떻게 읽는지 확인
"""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tts_broadcast.app import App  # noqa: E402
from tts_broadcast.config import ROOT  # noqa: E402
from tts_broadcast.broadcaster import Announcement, parse_priority  # noqa: E402
from tts_broadcast.instance import SingleInstance, activate_running, message_box  # noqa: E402


def _console_title(title: str) -> None:
    # 배치 파일에 한글을 넣으면 cmd 에서 깨지므로 창 제목은 여기서 설정
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(title)
        except (AttributeError, OSError):
            pass


def _server_summary(app: App) -> str:
    from tts_broadcast.config import resolve_path
    cfg = app.config
    items = app.scheduler.items()
    on = sum(1 for it in items if it.get("enabled", True))
    lines = [
        "=" * 60,
        "  TTS 방송 - 화면 없이 실행 (자동 방송)",
        "=" * 60,
        f"  시설      : {cfg['facility'].get('name', '')}",
        f"  음성 엔진 : {app.broadcaster.engine_key}",
        f"  예약 방송 : 사용 {on}건 / 전체 {len(items)}건",
        f"  감시 폴더 : {app.watcher.folder if app.watcher else '사용 안 함'}",
        "              (.txt 파일을 넣으면 그 내용을 방송)" if app.watcher else "",
        f"  HTTP API  : http://{cfg['api']['host']}:{cfg['api']['port']}/" if app.api else "  HTTP API  : 사용 안 함",
        f"  기록      : {resolve_path(cfg['log_dir']) / 'broadcast.log'}",
        "-" * 60,
        "  종료하려면 이 창에서 Ctrl+C 를 누르거나 창을 닫으세요.",
        "  (설정 변경은 방송프로그램_실행.bat 화면에서 한 뒤 다시 실행)",
        "=" * 60,
    ]
    return "\n".join(line for line in lines if line)


def main() -> int:
    ap = argparse.ArgumentParser(description="TTS 자동 방송 송출 프로그램")
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--tray", action="store_true", help="창 없이 트레이에서 시작 (Windows 시작 시 자동 실행용)")
    ap.add_argument("--headless", action="store_true", help="(예전 서버 모드) --tray 와 같음")
    ap.add_argument("--say", help="문구 하나를 방송하고 종료")
    ap.add_argument("--priority", default="보통")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--engine", help="이번 실행에만 사용할 엔진 프로필")
    ap.add_argument("--list-engines", action="store_true")
    ap.add_argument("--list-voices", action="store_true")
    ap.add_argument("--reading", help="문구를 실제로 어떻게 읽는지 출력 (숫자 변환 확인)")
    args = ap.parse_args()

    if args.reading:
        from tts_broadcast.config import load_config
        from tts_broadcast.textnorm import english_leftovers, normalize, set_lexicon
        set_lexicon(load_config(Path(args.config)).get("pronunciations"))
        print(normalize(args.reading))
        left = english_leftovers(args.reading)
        if left:
            print("※ 발음이 부정확할 수 있는 영문:", ", ".join(left), "→ config.json 의 pronunciations 에 등록하세요")
        return 0

    if args.list_engines:
        from tts_broadcast.engines import available_engines, load_plugins
        load_plugins(ROOT / "plugins")
        print("엔진 종류:", ", ".join(available_engines()))
        return 0

    instance = SingleInstance()
    running = not instance.acquire()

    if args.say and running:
        # 방송 프로그램이 켜져 있으면 그 프로그램의 대기열로 보냄 (동시에 두 소리가 나지 않도록)
        return _say_to_running(Path(args.config), args)

    if running and not args.list_voices:
        if not activate_running():
            message_box("TTS 방송", "방송 프로그램이 이미 실행 중입니다.\n"
                                  "작업 표시줄 오른쪽 아래 알림 영역(트레이)의 TTS 방송 아이콘을 확인하세요.")
        return 0

    if args.say or args.list_voices:
        # 1회성 실행: 예약/감시/API 를 켜지 않음
        from tts_broadcast.config import load_config
        cfg = load_config(Path(args.config))
        cfg["watch_folder"]["enabled"] = False
        cfg["api"]["enabled"] = False
        import json, tempfile
        tmp = Path(tempfile.gettempdir()) / "tts_broadcast_once.json"
        tmp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        app = App(tmp)
        app.scheduler.start = lambda: None
    else:
        app = App(Path(args.config))

    if args.engine:
        app.broadcaster.set_engine(args.engine, app.build_engine(args.engine))

    if args.list_voices:
        for v in app.broadcaster.engine.list_voices():
            print(v)
        app.shutdown()
        return 0

    app.start()

    if args.say:
        done = threading.Event()
        app.broadcaster.add_listener(
            lambda k, a, m: done.set() if k in ("done", "error", "stopped") else None)
        app.broadcaster.submit(Announcement(text=args.say, priority=parse_priority(args.priority),
                                            repeat=args.repeat, source="명령줄"))
        done.wait()
        app.shutdown()
        return 0

    tray = args.tray or args.headless  # 예전 '서버 모드'는 트레이 시작으로 통합
    try:
        from tts_broadcast.qt_gui import BroadcastGUI
        gui = BroadcastGUI(app, start_hidden=tray)
    except ImportError:
        if tray:
            # PySide6 가 없는 PC: 트레이가 없으므로 콘솔에서 화면 없이 실행
            _console_title("TTS 방송 - 화면 없이 실행")
            print(_server_summary(app), flush=True)
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
            app.shutdown()
            return 0
        from tts_broadcast.gui import BroadcastGUI  # 기본(tkinter) 화면
        gui = BroadcastGUI(app)
    try:
        gui.run()
    finally:
        app.shutdown()
    if getattr(gui, "restart_requested", False):
        # 설정 복원·초기화 후 새 설정으로 다시 시작 (API 포트 등이 정리된 뒤, 창을 보이며 실행)
        import subprocess
        instance.release()
        argv = [a for a in (sys.argv[1:] if (getattr(sys, "frozen", False) or "__compiled__" in globals()) else sys.argv)
                if a not in ("--tray", "--headless")]
        subprocess.Popen([sys.executable, *argv], cwd=str(Path.cwd()))
    return 0


def _say_to_running(config_path: Path, args) -> int:
    """실행 중인 방송 프로그램에 HTTP API 로 방송 요청."""
    import json
    import urllib.request
    from tts_broadcast.config import load_config
    api = load_config(config_path)["api"]
    if not api.get("enabled"):
        print("방송 프로그램이 실행 중이라 대신 방송할 수 없습니다. (config.json 의 api 를 켜면 실행 중인 "
              "프로그램으로 전달됩니다)", file=sys.stderr)
        return 1
    host = "127.0.0.1" if api["host"] in ("0.0.0.0", "") else api["host"]
    body = json.dumps({"text": args.say, "priority": args.priority, "repeat": args.repeat}).encode("utf-8")
    req = urllib.request.Request(f"http://{host}:{api['port']}/api/announce", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-Token": api.get("token", "")})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print("실행 중인 방송 프로그램의 대기열에 넣었습니다:", r.read().decode("utf-8"))
        return 0
    except Exception as e:
        print(f"실행 중인 방송 프로그램에 전달하지 못했습니다: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
