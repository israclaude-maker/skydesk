"""
SkyDesk Unlock Service
=======================
SYSTEM ke tor pe Session 0 mein chalti hai. Session 0 Windows Vista se
isolated hai user ki interactive session (Session 1+) se - isliye ye
service kabhi seedha user ka Winlogon/lock-screen desktop access nahi
kar sakti, chahe SYSTEM ho ya kuch bhi (yehi Session 0 isolation ka
maqsad hai - services ko login UI se chhed-chhaad karne se rokna).

Asal fix: ek SYSTEM token banao jo target session ke sath "tagged" ho,
aur usi se ek chhota helper (SkyDeskSessionHelper.exe) us session ke
andar launch karo. Chunki helper asal mein usi session/window-station
mein rehta hai jahan lock screen hai, wo Winlogon open kar sakta hai.
(Yehi trick PsExec -s -i jaise tools use karte hain.)

Requires: pip install pywin32
"""
import os
import sys
import time
import json
import base64

import win32serviceutil
import win32service
import win32event
import win32pipe
import win32file
import win32security
import win32process
import win32profile
import win32con
import win32ts
import win32api
import servicemanager

PIPE_NAME = r'\\.\pipe\SkyDeskUnlock'


def _enable_privilege(htoken, name):
    try:
        priv_id = win32security.LookupPrivilegeValue(None, name)
        win32security.AdjustTokenPrivileges(htoken, False, [(priv_id, win32security.SE_PRIVILEGE_ENABLED)])
    except Exception:
        pass


def _system_token_for_session(session_id):
    """Is (SYSTEM) process ka token duplicate karke, target session id se
    re-tag karta hai - taake isse launch hone wala process Session 0 ke
    isolated window station ki bajaye us session ke andar lande."""
    hproc = win32api.GetCurrentProcess()
    htok = win32security.OpenProcessToken(
        hproc,
        win32con.TOKEN_DUPLICATE | win32con.TOKEN_QUERY | win32con.TOKEN_ADJUST_PRIVILEGES
    )
    for priv in ("SeTcbPrivilege", "SeAssignPrimaryTokenPrivilege", "SeIncreaseQuotaPrivilege"):
        _enable_privilege(htok, priv)

    dup = win32security.DuplicateTokenEx(
        htok, win32security.SecurityImpersonation,
        win32con.TOKEN_ALL_ACCESS, win32security.TokenPrimary, None
    )
    win32security.SetTokenInformation(dup, win32security.TokenSessionId, session_id)
    return dup


def _launch_session_helper(args):
    """SkyDeskSessionHelper.exe ko abhi ke active console session ke
    andar, SYSTEM ke tor pe launch karta hai. True return hone ka matlab
    sirf itna hai ke launch call kamyab hui - helper ka action kamyab
    hua ya nahi wo guarantee nahi karta."""
    session_id = win32ts.WTSGetActiveConsoleSessionId()
    if session_id in (0xFFFFFFFF, -1, None):
        return False, "No active console session"

    token = _system_token_for_session(session_id)
    env = win32profile.CreateEnvironmentBlock(token, False)

    startup = win32process.STARTUPINFO()
    startup.dwFlags = win32process.STARTF_USESHOWWINDOW
    startup.wShowWindow = win32con.SW_HIDE

    helper_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "SkyDeskSessionHelper.exe")
    cmdline = f'"{helper_path}" {args}'

    try:
        win32process.CreateProcessAsUser(
            token, None, cmdline, None, None, False,
            win32con.CREATE_NEW_CONSOLE, env, None, startup
        )
        return True, "launched"
    except Exception as e:
        return False, str(e)


def request_unlock(password):
    args = base64.b64encode(password.encode("utf-8")).decode("ascii")
    return _launch_session_helper(args)


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
                    ok, msg = request_unlock(cmd.get("password", ""))
                    response = json.dumps({"ok": ok, "message": msg}).encode("utf-8")
                else:
                    response = json.dumps({"ok": False, "message": "unknown action"}).encode("utf-8")

                win32file.WriteFile(pipe, response)
                win32file.FlushFileBuffers(pipe)
                win32pipe.DisconnectNamedPipe(pipe)
                win32file.CloseHandle(pipe)
            except Exception as e:
                servicemanager.LogErrorMsg(f"SkyDeskUnlock loop error: {e}")
                time.sleep(1)


if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(SkyDeskUnlockService)