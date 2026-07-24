import websocket
import json
import socket
import threading
from config import WS_PRESENCE_URL


def get_local_ip():
    """Apna LAN IP nikalo (agar sharer/viewer same network pe hon toh ye tez chalega)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


class WSClient:
    def __init__(self, token, on_message_callback):
        self.token = token
        self.on_message_callback = on_message_callback
        self.status_callback = None
        self.ws = None
        self.thread = None

    def set_status_callback(self, callback):
        self.status_callback = callback

    def connect(self):
        url = f"{WS_PRESENCE_URL}?token={self.token}"

        self.ws = websocket.WebSocketApp(
            url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )

        self.thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self.thread.start()

    def _on_open(self, ws):
        print("WebSocket connected!")
        if self.status_callback:
            self.status_callback(True)

    def _on_message(self, ws, message):
        data = json.loads(message)
        # Callback ko UI thread ki taraf bhej rahe hain
        self.on_message_callback(data)

    def _on_error(self, ws, error):
        print("WebSocket error:", error)
        if self.status_callback:
            self.status_callback(False)

    def _on_close(self, ws, close_status_code, close_msg):
        print("WebSocket closed")

    def send_connect_request(self, target_remote_id):
        message = {"type": "id_connect_request", "target_remote_id": target_remote_id}
        if self.ws:
            self.ws.send(json.dumps(message))

    def send_accept(self, requester_remote_id):
        message = {
            "type": "id_connect_accept",
            "requester_remote_id": requester_remote_id,
            "local_ip": get_local_ip(),
        }
        if self.ws:
            self.ws.send(json.dumps(message))

    def send_reject(self, requester_remote_id):
        message = {
            "type": "id_connect_reject",
            "requester_remote_id": requester_remote_id,
        }
        if self.ws:
            self.ws.send(json.dumps(message))

    def close(self):
        if self.ws:
            self.ws.close()