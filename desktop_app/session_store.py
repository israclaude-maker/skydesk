import os
import json
import base64
from datetime import datetime, timezone

APP_DIR_NAME = "SkyDesk"
SESSION_FILE_NAME = "session.json"


def _get_config_dir():
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    config_dir = os.path.join(base, APP_DIR_NAME)
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def _get_session_path():
    return os.path.join(_get_config_dir(), SESSION_FILE_NAME)


def _default_data():
    return {
        "token": None,
        "user": None,
        "remember_me": False,
        "saved_username": "",
        "saved_password": "",
        "recent_users": [],
        "recent_connections": [],
    }


def _load_data():
    path = _get_session_path()
    if not os.path.exists(path):
        return _default_data()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            merged = _default_data()
            merged.update(data)
            return merged
    except (json.JSONDecodeError, OSError):
        return _default_data()


def _save_data(data):
    path = _get_session_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _obfuscate(text):
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")


def _deobfuscate(text):
    try:
        return base64.b64decode(text.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""


# ---------------------------------------------------------------
# Remember Me (saved username/password)
# ---------------------------------------------------------------
def save_remember_me(username, password, remember):
    data = _load_data()
    data["remember_me"] = remember
    if remember:
        data["saved_username"] = username
        data["saved_password"] = _obfuscate(password)
    else:
        data["saved_username"] = ""
        data["saved_password"] = ""
    _save_data(data)


def get_remember_me():
    data = _load_data()
    if data.get("remember_me"):
        return data.get("saved_username", ""), _deobfuscate(data.get("saved_password", ""))
    return "", ""


# ---------------------------------------------------------------
# Session (auto-login token)
# ---------------------------------------------------------------
def save_session(token, user_data):
    data = _load_data()
    data["token"] = token
    data["user"] = user_data
    _save_data(data)
    add_recent_user(user_data)


def get_session():
    data = _load_data()
    return data.get("token"), data.get("user")


def clear_session():
    data = _load_data()
    data["token"] = None
    data["user"] = None
    _save_data(data)


# ---------------------------------------------------------------
# Recent / past logged-in users (AnyDesk-style side list)
# ---------------------------------------------------------------
def add_recent_user(user_data):
    if not user_data or not user_data.get("username"):
        return
    data = _load_data()
    recent = data.get("recent_users", [])
    recent = [u for u in recent if u.get("username") != user_data.get("username")]
    recent.insert(0, {
        "username": user_data.get("username"),
        "remote_id": user_data.get("remote_id", ""),
        "last_login": datetime.now(timezone.utc).isoformat(),
    })
    data["recent_users"] = recent[:5]
    _save_data(data)


def get_recent_users():
    data = _load_data()
    return data.get("recent_users", [])


# ---------------------------------------------------------------
# Recent connections (remote IDs this user has connected to)
# ---------------------------------------------------------------
def add_recent_connection(target_id):
    if not target_id:
        return
    data = _load_data()
    recent = data.get("recent_connections", [])
    recent = [r for r in recent if r.get("target_id") != target_id]
    recent.insert(0, {
        "target_id": target_id,
        "last_connected": datetime.now(timezone.utc).isoformat(),
    })
    data["recent_connections"] = recent[:6]
    _save_data(data)


def get_recent_connections():
    data = _load_data()
    return data.get("recent_connections", [])