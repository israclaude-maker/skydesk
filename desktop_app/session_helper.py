"""
Ye service ke through, thodi der ke liye, user ki interactive session ke
andar launch hota hai (ek SYSTEM token ke sath jo us session ke sath
"tagged" hai). Chunki ye wahi session mein rehta hai jahan lock screen
hai, ye asal mein Winlogon desktop open kar sakta hai - jo Session 0 mein
chalne wali service kabhi nahi kar sakti.

Usage: SkyDeskSessionHelper.exe <base64_password>
"""
import sys
import time
import base64
import ctypes
import ctypes.wintypes as wt

user32 = ctypes.windll.user32

DESKTOP_GENERIC_ALL = 0x10000000
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
VK_RETURN = 0x0D


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
        ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(wt.ULONG)),
    ]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]
    _anonymous_ = ("_i",)
    _fields_ = [("type", wt.DWORD), ("_i", _I)]


def _send(vk=0, ch=0, key_up=False):
    extra = ctypes.pointer(wt.ULONG(0))
    flags = (KEYEVENTF_UNICODE if ch else 0) | (KEYEVENTF_KEYUP if key_up else 0)
    ki = KEYBDINPUT(vk, ch, flags, 0, extra)
    inp = INPUT(INPUT_KEYBOARD, ki)
    user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(INPUT))


def main():
    if len(sys.argv) < 2:
        return
    password = base64.b64decode(sys.argv[1]).decode("utf-8")

    # Login prompt laane ke liye secure-attention-sequence uthao.
    user32.SendSAS(False)
    time.sleep(1.2)

    hdesk = user32.OpenDesktopW("Winlogon", 0, False, DESKTOP_GENERIC_ALL)
    if not hdesk:
        return
    user32.SetThreadDesktop(hdesk)
    time.sleep(0.4)

    for ch in password:
        _send(ch=ord(ch), key_up=False)
        _send(ch=ord(ch), key_up=True)
        time.sleep(0.02)

    time.sleep(0.2)
    _send(vk=VK_RETURN, key_up=False)
    _send(vk=VK_RETURN, key_up=True)


if __name__ == "__main__":
    main()