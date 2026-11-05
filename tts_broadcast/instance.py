"""중복 실행 방지 (한 PC 에서 방송 프로그램은 하나만).

두 개가 동시에 켜지면 예약 방송이 두 번 나가고 HTTP API 포트도 겹치므로,
Windows 이름 있는 뮤텍스로 막고 이미 실행 중이면 기존 창을 앞으로 불러옵니다.
"""
from __future__ import annotations

import sys

MUTEX_NAME = "Global\\TTSBroadcast.SingleInstance"
ACTIVATE_SERVER = "TTSBroadcast.Activate"  # 기존 창을 앞으로 부르는 QLocalServer 이름
_ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self):
        self._handle = None

    def acquire(self) -> bool:
        """처음 실행이면 True, 이미 다른 프로그램이 실행 중이면 False."""
        if sys.platform != "win32":
            return True
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        handle = k32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return True  # 뮤텍스를 만들 수 없으면 막지 않음 (방송 불가보다 낫다)
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            k32.CloseHandle(ctypes.c_void_p(handle))
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        """다시 시작할 때 새 프로세스가 실행될 수 있도록 먼저 해제."""
        if self._handle:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None


def activate_running() -> bool:
    """실행 중인 프로그램의 창을 앞으로 불러옴. 전달되면 True."""
    try:
        from PySide6.QtNetwork import QLocalSocket
    except ImportError:
        return False
    sock = QLocalSocket()
    sock.connectToServer(ACTIVATE_SERVER)
    if not sock.waitForConnected(1500):
        return False
    sock.write(b"show")
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def message_box(title: str, text: str) -> None:
    """화면 라이브러리 없이 띄우는 Windows 알림창."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)  # MB_ICONINFORMATION
    else:
        print(f"{title}: {text}")
