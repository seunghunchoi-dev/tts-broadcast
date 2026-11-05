"""Windows 시작 시 자동 실행 (현재 사용자 '시작 프로그램' 레지스트리, 관리자 권한 불필요).

자동 실행 시에는 --tray 로 시작해 창 없이 트레이에서 방송합니다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .config import ROOT

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_NAME = "TTSBroadcast"


def command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")  # 콘솔 창 없이 실행
    if pythonw.exists():
        exe = pythonw
    return f'"{exe}" "{ROOT / "main.py"}" --tray'


def is_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY) as k:
            winreg.QueryValueEx(k, _NAME)
            return True
    except OSError:
        return False


def set_enabled(on: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, _NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(k, _NAME)
            except FileNotFoundError:
                pass
