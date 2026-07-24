import os
import datetime
import tempfile

# Desktop kabhi OneDrive se redirect hota hai jahan likhna fail ho sakta hai,
# isliye har cheez %TEMP% mein likh do -- ye hamesha exist karta hai, bina admin ke.
LOG_PATH = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()), "skydesk_debug.log")

# Har baar app start hone par ek marker line likho, taake pata chale file kaam kar rahi hai.
try:
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n===== SkyDesk started, logging to: {LOG_PATH} =====\n")
except Exception as e:
    # Agar TEMP bhi fail ho jaye (bahut rare), fallback C:\ pe try karo
    try:
        LOG_PATH = "C:\\skydesk_debug.log"
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n===== SkyDesk started (fallback path) =====\n")
    except Exception:
        pass


def log(message):
    """Console nahi dikhta .exe mein, isliye har cheez is file mein likh do."""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {message}\n")
    except Exception:
        pass