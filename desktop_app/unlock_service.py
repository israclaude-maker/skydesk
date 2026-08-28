"""
SkyDesk Unlock Service
Runs as a Windows Service (SYSTEM account) so it can interact with the
secure Winlogon desktop even when no one is logged in. Listens on a
local named pipe for unlock requests from the main SkyDesk app.

Requires: pip install pywin32
"""
import sys
import time
import json
import ctypes
import ctypes.wintypes as wt

import win32serviceutil
import win32service
import win32event
import win32pipe
import win32file
import servicemanager

PIPE_NAME = r'\\.\pipe\SkyDeskUnlock'

user32 = ctypes.windll.user32

DESKTOP_GENERIC_ALL = 0x10000000
GENERIC_ALL = 0x10000000
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wt.ULONG)),
    ]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]
    _anonymous_ = ("_i",)
    _fields_ = [("type", wt.DWORD), ("_i", _I)]


def _send_unicode_char(ch, key_up=False):
    extra = ctypes.pointer(wt.ULONG(0))
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if key_up else 0)
    ki = KEYBDINPUT(0, ord(ch), flags, 0, extra)
    inp = INPUT(INPUT_KEYBOARD, ki)
    user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(INPUT))


def _send_vk(vk, key_up=False):
    extra = ctypes.pointer(wt.ULONG(0))
    flags = KEYEVENTF_KEYUP if key_up else 0
    ki = KEYBDINPUT(vk, 0, flags, 0, extra)
    inp = INPUT(INPUT_KEYBOARD, ki)
    user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(INPUT))


VK_RETURN = 0x0D


def type_password_and_enter(password):
    """Attaches this thread to the secure Winlogon desktop and types the
    password followed by Enter."""
    hdesk = user32.OpenDesktopW(
        "Winlogon", 0, False, DESKTOP_GENERIC_ALL
    )
    if not hdesk:
        return False, "OpenDesktop(Winlogon) failed"

    if not user32.SetThreadDesktop(hdesk):
        return False, "SetThreadDesktop failed"

    time.sleep(0.5)  # give the lock screen a moment to render

    for ch in password:
        _send_unicode_char(ch, key_up=False)
        _send_unicode_char(ch, key_up=True)
        time.sleep(0.02)

    time.sleep(0.2)
    _send_vk(VK_RETURN, key_up=False)
    _send_vk(VK_RETURN, key_up=True)

    return True, "ok"


def request_unlock(password):
    """Full sequence: raise SAS to bring up the secure desktop's login
    prompt, then type the password."""
    user32.SendSAS(False)
    time.sleep(1.0)
    return type_password_and_enter(password)


class SkyDeskUnlockService(win32serviceutil.ServiceFramework):
    _svc_name_ = "SkyDeskUnlock"
    _svc_display_name_ = "SkyDesk Unlock Service"
    _svc_description_ = "Allows SkyDesk to unlock the screen during a remote session."

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.running = True

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.running = False
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, "")
        )
        self.main_loop()

    def main_loop(self):
        while self.running:
            try:
                pipe = win32pipe.CreateNamedPipe(
                    PIPE_NAME,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                    1, 65536, 65536, 0, None
                )
                win32pipe.ConnectNamedPipe(pipe, None)
                raw = win32file.ReadFile(pipe, 65536)[1]
                try:
                    cmd = json.loads(raw.decode("utf-8"))
                except Exception:
                    cmd = {}

                if cmd.get("action") == "unlock":
                    password = cmd.get("password", "")
                    ok, msg = request_unlock(password)
                    response = json.dumps({"ok": ok, "message": msg}).encode("utf-8")
                else:
                    response = json.dumps({"ok": False, "message": "unknown action"}).encode("utf-8")

                win32file.WriteFile(pipe, response)
                win32file.FlushFileBuffers(pipe)
                win32pipe.DisconnectNamedPipe(pipe)
                win32file.CloseHandle(pipe)
            except Exception:
                time.sleep(1)


if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(SkyDeskUnlockService)