import socket
import threading
import time
import json
from io import BytesIO
import mss
from PIL import Image
import struct
import pyautogui
import tkinter as tk
from debug_log import log

pyautogui.FAILSAFE = False


class CursorOverlay:
    """Sharer ki screen par controller ka naam dikhane wala chhota badge.
    Tkinter thread-safe nahi hai, isliye har operation main_root.after() se
    main thread mein bheja jata hai."""

    def __init__(self, main_root, label_text):
        self.main_root = main_root
        self.window = None
        self.label = None
        self.main_root.after(0, self._create, label_text)

    def _create(self, label_text):
        self.window = tk.Toplevel(self.main_root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#2196F3")
        self.label = tk.Label(
            self.window, text=label_text, fg="white", bg="#2196F3",
            font=("Arial", 10, "bold"), padx=6, pady=2
        )
        self.label.pack()
        self.window.geometry("+0+0")

    def move_to(self, x, y):
        self.main_root.after(0, self._move, x, y)

    def _move(self, x, y):
        if self.window:
            self.window.geometry(f"+{x + 15}+{y + 15}")

    def set_text(self, text):
        self.main_root.after(0, self._set_text, text)

    def _set_text(self, text):
        if self.label:
            self.label.config(text=text)

    def close(self):
        self.main_root.after(0, self._close)

    def _close(self):
        if self.window:
            self.window.destroy()
            self.window = None


class ScreenSharer:
    def __init__(self, main_root, screen_port=9001, control_port=9002):
        self.main_root = main_root
        self.screen_port = screen_port
        self.control_port = control_port
        self.running = False
        self.overlay = None

    def start(self):
        log("ScreenSharer.start() called - launching screen + control servers")
        self.running = True
        threading.Thread(target=self._run_screen_server, daemon=True).start()
        threading.Thread(target=self._run_control_server, daemon=True).start()

    # ---------- SCREEN STREAMING ----------
    def _run_screen_server(self):
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(("0.0.0.0", self.screen_port))
            server_socket.listen(1)
            log(f"Screen sharing server listening on port {self.screen_port}")
        except OSError as e:
            log(f"FAILED to bind screen server on port {self.screen_port}: {e}")
            return

        try:
            conn, addr = server_socket.accept()
            log(f"Viewer connected from {addr}")
        except OSError as e:
            log(f"FAILED to accept viewer connection: {e}")
            return

        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                while self.running:
                    screenshot = sct.grab(monitor)
                    img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

                    buffer = BytesIO()
                    img.save(buffer, format="JPEG", quality=50)
                    data = buffer.getvalue()

                    size = struct.pack(">L", len(data))
                    conn.sendall(size + data)

                    time.sleep(1 / 15)
        except (ConnectionResetError, BrokenPipeError) as e:
            log(f"Viewer disconnected: {e}")
        except Exception as e:
            log(f"Screen capture/send error: {e}")
        finally:
            conn.close()

    # ---------- CONTROL RECEIVING ----------
    def _run_control_server(self):
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(("0.0.0.0", self.control_port))
            server_socket.listen(1)
            log(f"Control server listening on port {self.control_port}")
        except OSError as e:
            log(f"FAILED to bind control server on port {self.control_port}: {e}")
            return

        try:
            conn, addr = server_socket.accept()
            log(f"Controller connected from {addr}")
        except OSError as e:
            log(f"FAILED to accept controller connection: {e}")
            return

        buffer = ""
        try:
            while self.running:
                data = conn.recv(4096).decode()
                if not data:
                    break
                buffer += data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        self._execute_command(json.loads(line))
        except (ConnectionResetError, BrokenPipeError):
            print("Controller disconnected")
        finally:
            if self.overlay:
                self.overlay.close()
            conn.close()

    def _execute_command(self, cmd):
        action = cmd.get("action")
        try:
            if action == "identify":
                name = cmd.get("name", "?")
                badge_text = name[0].upper()
                if self.overlay is None:
                    self.overlay = CursorOverlay(self.main_root, badge_text)
                else:
                    self.overlay.set_text(badge_text)

            elif action == "move":
                pyautogui.moveTo(cmd["x"], cmd["y"])
                if self.overlay:
                    self.overlay.move_to(cmd["x"], cmd["y"])

            elif action == "click":
                pyautogui.click(cmd["x"], cmd["y"], button=cmd.get("button", "left"))

            elif action == "scroll":
                pyautogui.scroll(cmd["amount"])

            elif action == "key":
                pyautogui.press(cmd["key"])

            elif action == "type":
                pyautogui.typewrite(cmd["text"])

        except Exception as e:
            print("Control execution error:", e)

    def stop(self):
        self.running = False
        if self.overlay:
            self.overlay.close()