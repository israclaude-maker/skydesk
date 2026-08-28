"""Client helper for the main SkyDesk app to talk to unlock_service.py
over the local named pipe."""
import json
import time
import win32file
import win32pipe
import pywintypes

PIPE_NAME = r'\\.\pipe\SkyDeskUnlock'


def request_unlock(password, timeout=5):
    """Sends an unlock request to the SkyDeskUnlock service. Returns
    (ok, message)."""
    try:
        win32pipe.WaitNamedPipe(PIPE_NAME, int(timeout * 1000))
        handle = win32file.CreateFile(
            PIPE_NAME,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0, None, win32file.OPEN_EXISTING, 0, None
        )
        payload = json.dumps({"action": "unlock", "password": password}).encode("utf-8")
        win32file.WriteFile(handle, payload)
        resp = win32file.ReadFile(handle, 65536)[1]
        win32file.CloseHandle(handle)
        data = json.loads(resp.decode("utf-8"))
        return data.get("ok", False), data.get("message", "")
    except pywintypes.error as e:
        return False, f"Service not reachable: {e}"
    except Exception as e:
        return False, str(e)