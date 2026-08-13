import threading
import time
import json
from io import BytesIO
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import messagebox
import websocket
from debug_log import log

# Relay ab WebSocket (wss://) ke through, VPS ke already-open HTTPS (443)
# port par - isliye har network isko pass hone deta hai, chahe wo sirf
# real HTTPS traffic allow karta ho.
RELAY_WS_URL = "wss://skydesk.skyfinancia.com/relay/"


class ScreenViewer:
    KEY_MAP = {
        "return": "enter",
        "backspace": "backspace",
        "space": "space",
        "tab": "tab",
        "escape": "esc",
        "shift_l": "shift",
        "shift_r": "shift",
        "control_l": "ctrl",
        "control_r": "ctrl",
        "alt_l": "alt",
        "alt_r": "alt",
        "up": "up",
        "down": "down",
        "left": "left",
        "right": "right",
        "delete": "delete",
        "home": "home",
        "end": "end",
    }

    CONNECT_RETRIES = 15
    CONNECT_RETRY_DELAY = 1

    def __init__(self, session_id, my_username="User"):
        self.session_id = session_id
        self.my_username = my_username
        self.running = False
        self.window = None
        self.canvas = None
        self.canvas_image_id = None
        self.status_text_id = None
        self.host_cursor_id = None
        self.host_cursor_label_id = None
        self.control_sock = None
        self.got_first_frame = False
        self.win_width = 1000
        self.win_height = 650
        self.remote_width = None
        self.remote_height = None
        self._photo_ref = None

    def start(self):
        log(f"ScreenViewer starting for session={self.session_id} via relay {RELAY_WS_URL}")
        self.window = tk.Toplevel()
        self.window.title("SkyDesk - Remote Screen")
        self.window.geometry("1000x650")
        self.window.minsize(400, 300)

        self.canvas = tk.Canvas(self.window, bg="#222", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas_image_id = self.canvas.create_image(0, 0, anchor="nw")
        self.status_text_id = self.canvas.create_text(
            10, 10, anchor="nw", text="Connecting to remote screen...",
            fill="white", font=("Segoe UI", 12)
        )

        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<Button-1>", lambda e: self._on_click(e, "left"))
        self.canvas.bind("<Button-3>", lambda e: self._on_click(e, "right"))
        self.canvas.bind("<MouseWheel>", self._on_scroll)
        self.window.bind("<Key>", self._on_key)
        self.window.bind("<Configure>", self._on_resize)
        self.canvas.focus_set()
        self.window.protocol("WM_DELETE_WINDOW", self.stop)

        self.window.update_idletasks()
        self.window.state("zoomed")
        self.window.update_idletasks()
        self.win_width = self.window.winfo_width()
        self.win_height = self.window.winfo_height()

        self.running = True
        threading.Thread(target=self._connect_screen_stream, daemon=True).start()
        threading.Thread(target=self._connect_control, daemon=True).start()

    def _connect_relay(self, channel):
        last_error = None
        for attempt in range(self.CONNECT_RETRIES):
            if not self.running and attempt > 0:
                return None
            try:
                ws = websocket.create_connection(RELAY_WS_URL, timeout=10)
                ws.settimeout(None)  # connect timeout only - don't timeout while waiting for a partner
                handshake = json.dumps({
                    "session_id": self.session_id,
                    "channel": channel,
                    "role": "viewer",
                })
                ws.send(handshake)
                log(f"Connected to relay for channel={channel}")
                return ws
            except Exception as e:
                last_error = e
                log(f"Relay connect attempt {attempt + 1}/{self.CONNECT_RETRIES} for {channel} failed: {e}")
            time.sleep(self.CONNECT_RETRY_DELAY)
        log(f"Giving up connecting to relay for channel={channel}. Last error: {last_error}")
        return None

    def _connect_screen_stream(self):
        sock = self._connect_relay("screen")
        if sock is None:
            self.window.after(0, self._connection_failed)
            return

        log("Connected to sharer (screen) via relay!")

        try:
            while self.running:
                frame_data = sock.recv()
                if not frame_data or isinstance(frame_data, str):
                    continue

                img = Image.open(BytesIO(frame_data))

                if self.remote_width is None:
                    self.remote_width, self.remote_height = img.size
                    log(f"Remote resolution detected from frame: {self.remote_width}x{self.remote_height}")

                self.window.after(0, self._update_image, img)
        except (websocket.WebSocketConnectionClosedException, ConnectionResetError, BrokenPipeError, OSError):
            log("Sharer disconnected")
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _connection_failed(self):
        if self.canvas and self.status_text_id:
            self.canvas.itemconfig(
                self.status_text_id,
                text="Connect nahi ho saka. Sharer offline ho sakta hai ya VPS relay down hai."
            )
        messagebox.showerror(
            "Connection Failed",
            "Remote screen se connect nahi ho paya.\n\n"
            "Check karo:\n"
            "- Doosra user abhi bhi online hai\n"
            "- Internet connection theek hai"
        )

    def _on_resize(self, event):
        if event.widget is self.window:
            self.win_width = event.width
            self.win_height = event.height

    def _update_image(self, img):
        self.got_first_frame = True
        w = max(self.win_width, 100)
        h = max(self.win_height, 100)
        if img.size != (w, h):
            img = img.resize((w, h), Image.BILINEAR)
        self._photo_ref = ImageTk.PhotoImage(img)
        self.canvas.itemconfig(self.canvas_image_id, image=self._photo_ref)
        if self.status_text_id:
            self.canvas.itemconfig(self.status_text_id, text="")
        if self.host_cursor_id is not None:
            self.canvas.tag_raise(self.host_cursor_id)
            self.canvas.tag_raise(self.host_cursor_label_id)

    def _connect_control(self):
        sock = self._connect_relay("control")
        if sock is None:
            return
        self.control_sock = sock
        log("Connected to sharer (control) via relay!")

        self._send_command({"action": "identify", "name": self.my_username})
        threading.Thread(target=self._control_read_loop, daemon=True).start()

    def _control_read_loop(self):
        try:
            while self.running:
                raw = self.control_sock.recv()
                if not raw or isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self._handle_control_message(msg)
        except (websocket.WebSocketConnectionClosedException, ConnectionResetError, BrokenPipeError, OSError):
            log("Control channel closed")

    def _handle_control_message(self, msg):
        action = msg.get("action")
        if action == "screen_info":
            if self.remote_width is None:
                self.remote_width = msg.get("width")
                self.remote_height = msg.get("height")
                log(f"Remote resolution from screen_info: {self.remote_width}x{self.remote_height}")
        elif action == "host_cursor":
            x, y = msg.get("x"), msg.get("y")
            name = msg.get("name", "Sharer")
            if self.window:
                self.window.after(0, self._draw_host_cursor, x, y, name)

    def _draw_host_cursor(self, x, y, name="Sharer"):
        if x is None or y is None or not self.remote_width or not self.remote_height:
            return
        cx = x * (self.win_width / self.remote_width)
        cy = y * (self.win_height / self.remote_height)

        if self.host_cursor_id is None:
            self.host_cursor_id = self.canvas.create_oval(
                cx - 6, cy - 6, cx + 6, cy + 6,
                fill="#FF5722", outline="white", width=2
            )
            self.host_cursor_label_id = self.canvas.create_text(
                cx + 12, cy - 10, anchor="nw", text=name,
                fill="#FF5722", font=("Segoe UI", 9, "bold")
            )
        else:
            self.canvas.coords(self.host_cursor_id, cx - 6, cy - 6, cx + 6, cy + 6)
            self.canvas.coords(self.host_cursor_label_id, cx + 12, cy - 10)
            self.canvas.itemconfig(self.host_cursor_label_id, text=name)
        self.canvas.tag_raise(self.host_cursor_id)
        self.canvas.tag_raise(self.host_cursor_label_id)

    def _send_command(self, cmd):
        if self.control_sock:
            try:
                self.control_sock.send(json.dumps(cmd))
            except Exception as e:
                log(f"Failed to send control command: {e}")

    def _scale_coords(self, x, y):
        if not self.remote_width or not self.remote_height or not self.win_width or not self.win_height:
            return x, y
        real_x = int(x * (self.remote_width / self.win_width))
        real_y = int(y * (self.remote_height / self.win_height))
        real_x = max(0, min(real_x, self.remote_width - 1))
        real_y = max(0, min(real_y, self.remote_height - 1))
        return real_x, real_y

    def _on_mouse_move(self, event):
        x, y = self._scale_coords(event.x, event.y)
        self._send_command({"action": "move", "x": x, "y": y})

    def _on_click(self, event, button):
        x, y = self._scale_coords(event.x, event.y)
        self._send_command({"action": "click", "x": x, "y": y, "button": button})

    def _on_scroll(self, event):
        x, y = self._scale_coords(event.x, event.y)
        self._send_command({"action": "scroll", "amount": event.delta, "x": x, "y": y})

    def _on_key(self, event):
        keysym = event.keysym.lower()
        if keysym in self.KEY_MAP:
            self._send_command({"action": "key", "key": self.KEY_MAP[keysym]})
        elif len(event.char) == 1 and event.char.isprintable():
            self._send_command({"action": "type", "text": event.char})

    def stop(self):
        self.running = False
        if self.control_sock:
            try:
                self.control_sock.close()
            except Exception:
                pass
        if self.window:
            self.window.destroy()