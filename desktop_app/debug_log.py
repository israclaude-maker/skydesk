import os
import datetime

LOG_DIR = "C:\\SkyDeskLogs"
LOG_PATH = os.path.join(LOG_DIR, "skydesk_debug.log")


def log(message):
    """Console nahi dikhta .exe mein, isliye har cheez is fixed file mein likh do."""
    print(message)  # agar source se python se run ho raha hai to terminal mein bhi dikhe
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {message}\n")
    except Exception as e:
        # Agar ye bhi fail ho to kam se kam ye pata chale kyun
        try:
            with open(os.path.join(os.environ.get("TEMP", "C:\\"), "skydesk_debug_fallback.log"), "a", encoding="utf-8") as f2:
                f2.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] LOG FAILED: {e} -- original message: {message}\n")
        except Exception:
            pass
        