import socket
import struct
import threading
import time
import json
from io import BytesIO
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import messagebox


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
    CONNECT_RETRY_DELAY = 1  # seconds

    def __init__(self, host, screen_port=9001, control_port=9002, my_username="User"):
        self.host = host
        self.screen_port = screen_port
        self.control_port = control_port
        self.my_username = my_username
        self.running = False
        self.window = None
        self.label = None
        self.control_sock = None
        self.got_first_frame = False
        self.win_width = 1000
        self.win_height = 650

    def start(self):
        self.window = tk.Toplevel()
        self.window.title("SkyDesk - Remote Screen")
        self.window.geometry("1000x650")
        self.window.minsize(400, 300)

        self.label = tk.Label(
            self.window, text="Connecting to remote screen...",
            font=("Segoe UI", 12), bg="#222", fg="white"
        )
        self.label.pack(fill="both", expand=True)

        self.label.bind("<Motion>", self._on_mouse_move)
        self.label.bind("<Button-1>", lambda e: self._on_click(e, "left"))
        self.label.bind("<Button-3>", lambda e: self._on_click(e, "right"))
        self.label.bind("<MouseWheel>", self._on_scroll)
        self.window.bind("<Key>", self._on_key)
        self.window.bind("<Configure>", self._on_resize)
        self.label.focus_set()
        self.window.protocol("WM_DELETE_WINDOW", self.stop)

        # Turant maximize karo, kisi frame ka wait mat karo
        self.window.update_idletasks()
        self.window.state("zoomed")
        self.window.update_idletasks()
        self.win_width = self.window.winfo_width()
        self.win_height = self.window.winfo_height()

        self.running = True
        threading.Thread(target=self._connect_screen_stream, daemon=True).start()
        threading.Thread(target=self._connect_control, daemon=True).start()

    # ---------- SCREEN RECEIVING ----------
    def _connect_screen_stream(self):
        sock = self._connect_with_retry(self.screen_port)
        if sock is None:
            self.window.after(0, self._connection_failed)
            return

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
                    chunk = sock.recv(4096)
                    if not chunk:
                        return
                    data += chunk

                frame_data = data[:msg_size]
                data = data[msg_size:]

                img = Image.open(BytesIO(frame_data))
                self.window.after(0, self._update_image, img)
        except (ConnectionResetError, BrokenPipeError, OSError):
            print("Sharer disconnected")
        finally:
            sock.close()

    def _connect_with_retry(self, port):
        """Sharer ka socket thoda late ban sakta hai, isliye kuch der retry karo."""
        for attempt in range(self.CONNECT_RETRIES):
            if not self.running and attempt > 0:
                return None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((self.host, port))
                sock.settimeout(None)
                return sock
            except (ConnectionRefusedError, OSError, socket.timeout):
                time.sleep(self.CONNECT_RETRY_DELAY)
        return None

    def _connection_failed(self):
        if self.label:
            self.label.config(text="Connect nahi ho saka. Sharer offline ya firewall block kar raha hai.")
        messagebox.showerror(
            "Connection Failed",
            "Remote screen se connect nahi ho paya.\n\n"
            "Check karo:\n"
            "- Doosra user abhi bhi online hai\n"
            "- Agar alag network pe hain, sharer ke router pe ports 9001/9002 forward hain"
        )

    def _on_resize(self, event):
        if event.widget is self.window:
            self.win_width = event.width
            self.win_height = event.height

    def _update_image(self, img):
        self.got_first_frame = True
        # Remote screen ko window ke poore size mein fit karo, chahe resolution alag ho
        w = max(self.win_width, 100)
        h = max(self.win_height, 100)
        if img.size != (w, h):
            img = img.resize((w, h), Image.BILINEAR)
        photo = ImageTk.PhotoImage(img)
        self.label.config(image=photo, text="")
        self.label.image = photo

    # ---------- CONTROL SENDING ----------
    def _connect_control(self):
        sock = self._connect_with_retry(self.control_port)
        if sock is None:
            return
        self.control_sock = sock
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
        if self.window:
            self.window.destroy()