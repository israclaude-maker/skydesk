import os
import json
import time
import websocket
from debug_log import log

RELAY_WS_URL = "wss://skydesk.skyfinancia.com/relay/"
CHUNK_SIZE = 65536  # 64KB per chunk

CONNECT_RETRIES = 15
CONNECT_RETRY_DELAY = 1


def get_received_folder():
    folder = os.path.join(os.path.expanduser("~"), "SkyDesk Received Files")
    os.makedirs(folder, exist_ok=True)
    return folder


def connect_file_channel(session_id, role):
    """'file' channel par relay se connect karta hai - screen/control
    channels ki tarah hi handshake pattern use karta hai."""
    last_error = None
    for attempt in range(CONNECT_RETRIES):
        try:
            ws = websocket.create_connection(RELAY_WS_URL, timeout=10)
            ws.settimeout(None)
            handshake = json.dumps({
                "session_id": session_id,
                "channel": "file",
                "role": role,
            })
            ws.send(handshake)
            log(f"Connected to relay for channel=file, session={session_id}")
            return ws
        except Exception as e:
            last_error = e
            log(f"Relay connect attempt {attempt + 1}/{CONNECT_RETRIES} for file channel failed: {e}")
            time.sleep(CONNECT_RETRY_DELAY)
    log(f"Giving up connecting to relay for file channel. Last error: {last_error}")
    return None


def send_file_over_channel(conn, filepath, start_type, end_type):
    """Ek file ko chunks mein bhejta hai: pehle JSON header (start_type),
    phir binary chunks, phir JSON footer (end_type)."""
    filename = os.path.basename(filepath)
    filesize = os.path.getsize(filepath)

    conn.send(json.dumps({
        "type": start_type,
        "filename": filename,
        "size": filesize,
    }))

    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            conn.send(chunk, opcode=websocket.ABNF.OPCODE_BINARY)

    conn.send(json.dumps({"type": end_type}))
    log(f"Sent file '{filename}' ({filesize} bytes) as {start_type}")


class IncomingFileReceiver:
    """Ek incoming file ko chunks se assemble karta hai. Ek waqt mein
    sirf ek file receive hoti hai is object ke through (hamare use-case
    ke liye kaafi hai)."""

    def __init__(self):
        self._file_handle = None
        self._save_path = None

    def start(self, filename, save_folder):
        os.makedirs(save_folder, exist_ok=True)
        save_path = os.path.join(save_folder, filename)

        # Agar isi naam ki file pehle se hai to naya naam bana do
        base, ext = os.path.splitext(save_path)
        counter = 1
        while os.path.exists(save_path):
            save_path = f"{base} ({counter}){ext}"
            counter += 1

        self._save_path = save_path
        self._file_handle = open(save_path, "wb")

    def write_chunk(self, chunk):
        if self._file_handle:
            self._file_handle.write(chunk)

    def finish(self):
        if self._file_handle:
            self._file_handle.close()
        path = self._save_path
        self._file_handle = None
        self._save_path = None
        return path