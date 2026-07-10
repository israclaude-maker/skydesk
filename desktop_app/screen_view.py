import socket
import struct
import threading
import json
from io import BytesIO
from PIL import Image, ImageTk
import tkinter as tk


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

    def __init__(self, host, screen_port=9001, control_port=9002, my_username="User"):
        self.host = host
        self.screen_port = screen_port
        self.control_port = control_port
        self.my_username = my_username
        self.running = False
        self.window = None
        self.label = None
        self.control_sock = None

    def start(self):
        self.window = tk.Toplevel()
        self.window.title("SkyDesk - Remote Screen")
        self.label = tk.Label(self.window)
        self.label.pack()

        self.label.bind("<Motion>", self._on_mouse_move)
        self.label.bind("<Button-1>", lambda e: self._on_click(e, "left"))
        self.label.bind("<Button-3>", lambda e: self._on_click(e, "right"))
        self.label.bind("<MouseWheel>", self._on_scroll)
        self.window.bind("<Key>", self._on_key)
        self.label.focus_set()

        self.running = True
        threading.Thread(target=self._connect_screen_stream, daemon=True).start()
        threading.Thread(target=self._connect_control, daemon=True).start()

    # ---------- SCREEN RECEIVING ----------
    def _connect_screen_stream(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.host, self.screen_port))
        print("Connected to sharer (screen)!")

        data = b""
        payload_size = struct.calcsize(">L")

        try:
            while self.running:
                while len(data) < payload_size:
                    packet = sock.recv(4096)
                    if not packet:
                        return
                    data += packet

                packed_size = data[:payload_size]
                data = data[payload_size:]
                msg_size = struct.unpack(">L", packed_size)[0]

                while len(data) < msg_size:
                    data += sock.recv(4096)

                frame_data = data[:msg_size]
                data = data[msg_size:]

                img = Image.open(BytesIO(frame_data))
                photo = ImageTk.PhotoImage(img)

                self.window.after(0, self._update_image, photo)
        except (ConnectionResetError, BrokenPipeError):
            print("Sharer disconnected")
        finally:
            sock.close()

    def _update_image(self, photo):
        self.label.config(image=photo)
        self.label.image = photo

    # ---------- CONTROL SENDING ----------
    def _connect_control(self):
        self.control_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.control_sock.connect((self.host, self.control_port))
        print("Connected to sharer (control)!")

        # Apna naam bhejo taake sharer ki screen par badge dikhe
        self._send_command({"action": "identify", "name": self.my_username})

    def _send_command(self, cmd):
        if self.control_sock:
            try:
                message = json.dumps(cmd) + "\n"
                self.control_sock.sendall(message.encode())
            except Exception as e:
                print("Failed to send control command:", e)

    def _on_mouse_move(self, event):
        self._send_command({"action": "move", "x": event.x, "y": event.y})

    def _on_click(self, event, button):
        self._send_command({"action": "click", "x": event.x, "y": event.y, "button": button})

    def _on_scroll(self, event):
        amount = 1 if event.delta > 0 else -1
        self._send_command({"action": "scroll", "amount": amount})

    def _on_key(self, event):
        keysym = event.keysym.lower()

        if keysym in self.KEY_MAP:
            self._send_command({"action": "key", "key": self.KEY_MAP[keysym]})
        elif len(event.char) == 1 and event.char.isprintable():
            self._send_command({"action": "type", "text": event.char})

    def stop(self):
        self.running = False
        if self.control_sock:
            self.control_sock.close()