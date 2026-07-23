import os
import datetime

LOG_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "skydesk_debug.log")


def log(message):
    """Console nahi dikhta .exe mein, isliye har cheez is file mein likh do."""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {message}\n")
    except Exception:
        pass