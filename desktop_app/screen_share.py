import threading
import queue
import time
import json
import ctypes
from io import BytesIO
import mss
from PIL import Image
import pyautogui
import tkinter as tk
import websocket
from debug_log import log

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0
pyautogui.MINIMUM_DURATION = 0
pyautogui.MINIMUM_SLEEP = 0

# Relay ab WebSocket (wss://) ke through, VPS ke already-open HTTPS (443)
# port par - isliye har network isko pass hone deta hai, chahe wo sirf
# real HTTPS traffic allow karta ho. Agar domain kabhi badle to sirf
# yahan update karna hoga (ya isko config.py mein move kar lo).
RELAY_WS_URL = "wss://skydesk.skyfinancia.com/relay/"

CONNECT_RETRIES = 15
CONNECT_RETRY_DELAY = 1  # seconds

# ---------- Win32 constants for click-through, no-activate overlay ----------
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

user32 = ctypes.windll.user32

# Module-level singleton: sirf EK badge/overlay window hamesha exist kare.
# Agar purani session ka overlay properly band nahi hua tha (crash/abrupt
# disconnect), naya ScreenSharer start hote hi ye purane ko destroy kar
# dega - taake kabhi do overlays ek sath na dikhein.
_active_overlay = None


def make_click_through(tk_window):
    """Overlay ko OS level pe click-through + no-activate bana deta hai
    taake yeh kabhi bhi mouse/keyboard focus na le."""
    hwnd = user32.GetParent(tk_window.winfo_id())
    if not hwnd:
        hwnd = tk_window.winfo_id()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def connect_to_relay(channel, session_id, role, retries=CONNECT_RETRIES):
    """VPS relay (WebSocket) ko connect karta hai aur handshake bhejta
    hai taake relay isko sahi partner ke sath pair kar sake."""
    last_error = None
    for attempt in range(retries):
        try:
            ws = websocket.create_connection(RELAY_WS_URL, timeout=10)
            ws.settimeout(None)  # connect timeout only - don't timeout while waiting for a partner
            handshake = json.dumps({
                "session_id": session_id,
                "channel": channel,
                "role": role,
            })
            ws.send(handshake)
            log(f"Connected to relay for channel={channel}, session={session_id}")
            return ws
        except Exception as e:
            last_error = e
            log(f"Relay connect attempt {attempt + 1}/{retries} for {channel} failed: {e}")
            time.sleep(CONNECT_RETRY_DELAY)
    log(f"Giving up connecting to relay for channel={channel} after {retries} attempts. Last error: {last_error}")
    return None


class CursorOverlay:
    """Sharer ki screen par controller ka naam dikhane wala chhota badge.
    Click-through + no-activate hai, isliye kabhi bhi mouse/keyboard input
    intercept nahi karega."""

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
        self.window.update_idletasks()
        try:
            make_click_through(self.window)
        except Exception as e:
            log(f"CursorOverlay click-through style failed: {e}")

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
    def __init__(self, main_root, session_id, username="Sharer"):
        self.main_root = main_root
        self.session_id = session_id
        self.username = username
        self.running = False
        self.overlay = None
        self.cmd_queue = queue.Queue()
        self._control_conn_alive = False
        self._input_blocked = False

    def _set_input_blocked(self, blocked):
        """Sharer ka apna physical mouse/keyboard block/unblock karta hai,
        taake controller ke commands ke sath overlap na ho. Sirf hardware
        input block hota hai - hamare apne pyautogui commands (isi process
        se aa rahe) is process ke andar hi chalte rehte hain."""
        if blocked == self._input_blocked:
            return
        try:
            result = user32.BlockInput(blocked)
            self._input_blocked = blocked
            log(f"BlockInput({blocked}) -> {result}")
        except Exception as e:
            log(f"BlockInput({blocked}) failed: {e}")

    def start(self):
        log(f"ScreenSharer.start() called for session={self.session_id} via relay {RELAY_WS_URL}")
        self.running = True
        # Sharer ka apna physical mouse/keyboard block kar do - taake sirf
        # controller (viewer) ka mouse chale, dono ka mouse ek sath fight
        # na kare. Windows khud Ctrl+Alt+Del pe hamesha input unblock kar
        # deta hai (safety net), isliye sharer kabhi permanently lock nahi hoti.
        self._set_input_blocked(True)
        threading.Thread(target=self._run_screen_channel, daemon=True).start()
        threading.Thread(target=self._run_control_channel, daemon=True).start()
        threading.Thread(target=self._command_worker, daemon=True).start()

    # ---------- SCREEN STREAMING (via relay) ----------
    def _run_screen_channel(self):
        conn = connect_to_relay("screen", self.session_id, "sharer")
        if conn is None:
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

                    # WebSocket messages already have their own boundaries -
                    # no need to manually prefix with a length like raw TCP did.
                    conn.send(data, opcode=websocket.ABNF.OPCODE_BINARY)

                    time.sleep(1 / 15)
        except (websocket.WebSocketConnectionClosedException, ConnectionResetError, BrokenPipeError) as e:
            log(f"Viewer disconnected: {e}")
        except Exception as e:
            log(f"Screen capture/send error: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ---------- CONTROL (via relay) ----------
    def _run_control_channel(self):
        conn = connect_to_relay("control", self.session_id, "sharer")
        if conn is None:
            return

        # Real screen resolution ek dafa bhej do - viewer isse coordinate
        # scaling sahi karega.
        try:
            with mss.mss() as sct:
                mon = sct.monitors[1]
            screen_info = json.dumps({
                "action": "screen_info",
                "width": mon["width"],
                "height": mon["height"],
            })
            conn.send(screen_info)
        except Exception as e:
            log(f"Failed to send screen_info: {e}")

        self._host_cursor_send_thread(conn)

        try:
            while self.running:
                raw = conn.recv()
                if not raw or isinstance(raw, bytes):
                    continue
                try:
                    cmd = json.loads(raw)
                    self.cmd_queue.put(cmd)
                except json.JSONDecodeError as e:
                    log(f"Bad command JSON ignored: {e}")
        except (websocket.WebSocketConnectionClosedException, ConnectionResetError, BrokenPipeError):
            log("Controller disconnected")
        finally:
            global _active_overlay
            self._control_conn_alive = False
            self._set_input_blocked(False)
            if self.overlay:
                self.overlay.close()
                if _active_overlay is self.overlay:
                    _active_overlay = None
            try:
                conn.close()
            except Exception:
                pass

    def _host_cursor_send_thread(self, conn):
        """Sharer ki apni real mouse position har ~50ms mein viewer ko
        wapas bhejta hai (naam ke sath), taake viewer usko bhi dikha sake."""
        self._control_conn_alive = True

        def _worker():
            last_pos = None
            while self.running and self._control_conn_alive:
                try:
                    x, y = pyautogui.position()
                except Exception:
                    time.sleep(0.05)
                    continue
                if (x, y) != last_pos:
                    last_pos = (x, y)
                    try:
                        msg = json.dumps({
                            "action": "host_cursor",
                            "x": x,
                            "y": y,
                            "name": self.username,
                        })
                        conn.send(msg)
                    except (websocket.WebSocketConnectionClosedException, BrokenPipeError, ConnectionResetError, OSError):
                        break
                time.sleep(0.05)

        threading.Thread(target=_worker, daemon=True).start()

    # ---------- COMMAND EXECUTION (separate worker thread) ----------
    def _command_worker(self):
        while True:
            try:
                cmd = self.cmd_queue.get()
            except Exception:
                continue

            if cmd.get("action") == "move":
                latest_move = cmd
                while True:
                    try:
                        next_cmd = self.cmd_queue.get_nowait()
                    except queue.Empty:
                        break
                    if next_cmd.get("action") == "move":
                        latest_move = next_cmd
                    else:
                        self._execute_command(latest_move)
                        self._execute_command(next_cmd)
                        latest_move = None
                        break
                if latest_move is not None:
                    self._execute_command(latest_move)
            else:
                self._execute_command(cmd)

    def _execute_command(self, cmd):
        global _active_overlay
        action = cmd.get("action")
        try:
            if action == "identify":
                name = cmd.get("name", "?")
                badge_text = name[0].upper()
                # Pehle purani (kisi bhi wajah se reh gayi) overlay window
                # hamesha destroy kar do - taake kabhi 2 badges ek sath na
                # dikhein, sirf ek hi (current session ka) rahe.
                if _active_overlay is not None and _active_overlay is not self.overlay:
                    _active_overlay.close()
                    _active_overlay = None
                if self.overlay is None:
                    self.overlay = CursorOverlay(self.main_root, badge_text)
                    _active_overlay = self.overlay
                else:
                    self.overlay.set_text(badge_text)
                # Controller connect ho gaya - ab sharer ka apna mouse/keyboard
                # block kar do taake dono ka input ek dusre se na takraye.
                self._set_input_blocked(True)

            elif action == "move":
                pyautogui.moveTo(cmd["x"], cmd["y"], duration=0)
                if self.overlay:
                    self.overlay.move_to(cmd["x"], cmd["y"])

            elif action == "click":
                pyautogui.click(cmd["x"], cmd["y"], button=cmd.get("button", "left"))

            elif action == "scroll":
                pyautogui.scroll(cmd["amount"])

            elif action == "key":
                pyautogui.press(cmd["key"])

            elif action == "type":
                pyautogui.write(cmd["text"], interval=0)

            else:
                log(f"Unknown command action received: {action}")

        except Exception as e:
            log(f"Control execution error for cmd={cmd}: {e}")

    def stop(self):
        global _active_overlay
        self.running = False
        self._control_conn_alive = False
        self._set_input_blocked(False)
        if self.overlay:
            self.overlay.close()
            if _active_overlay is self.overlay:
                _active_overlay = None