import os
import threading
import queue
import time
import json
import ctypes
import ctypes.wintypes as wintypes
from io import BytesIO
import mss
from PIL import Image
import pyautogui
import tkinter as tk
import websocket
from debug_log import log
from file_transfer import (
    connect_file_channel, send_file_over_channel, IncomingFileReceiver, get_received_folder
)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0
pyautogui.MINIMUM_DURATION = 0
pyautogui.MINIMUM_SLEEP = 0

RELAY_WS_URL = "wss://skydesk.skyfinancia.com/relay/"

CONNECT_RETRIES = 15
CONNECT_RETRY_DELAY = 1

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x00000010
LLMHF_INJECTED = 0x00000001

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT), ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


def click_without_moving_cursor(x, y, button="left"):
    """Reliable real click - asal Windows cursor ko turant us jagah
    le jata hai, click karta hai, phir wapas laata hai. Message-based
    (PostMessage) click ki koshish ki thi taake cursor bilkul na hile,
    lekin bohot saare apps/controls bina window-focus ke usay ignore
    kar dete hain - is liye reliability ke liye real click use kar rahe
    hain. Cursor thodi der ke liye visible move hoga, lekin click har
    jagah kaam karega."""
    try:
        home = pyautogui.position()
    except Exception:
        home = None
    pyautogui.click(x, y, button=button)
    if home is not None:
        pyautogui.moveTo(home.x, home.y, duration=0)


class InputGuard:
    def __init__(self):
        self._thread = None
        self._thread_id = None
        self._kbd_hook = None
        self._mouse_hook = None
        self._allowed_rect = None
        self._kbd_proc_ref = None
        self._mouse_proc_ref = None
        self._running = False

    def set_allowed_rect(self, rect):
        self._allowed_rect = rect

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        self._kbd_proc_ref = HOOKPROC(self._low_level_keyboard_proc)
        self._mouse_proc_ref = HOOKPROC(self._low_level_mouse_proc)
        hmod = kernel32.GetModuleHandleW(None)
        self._kbd_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kbd_proc_ref, hmod, 0)
        self._mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_proc_ref, hmod, 0)
        msg = wintypes.MSG()
        while self._running:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if self._kbd_hook:
            user32.UnhookWindowsHookEx(self._kbd_hook)
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)

    def _low_level_keyboard_proc(self, nCode, wParam, lParam):
        if nCode == 0:
            info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if not (info.flags & LLKHF_INJECTED):
                return 1
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _low_level_mouse_proc(self, nCode, wParam, lParam):
        if nCode == 0:
            info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not (info.flags & LLMHF_INJECTED):
                rect = self._allowed_rect
                x, y = info.pt.x, info.pt.y
                inside = rect and rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]
                if not inside:
                    return 1
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def stop(self):
        self._running = False
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=2)


class StopSharingButton:
    def __init__(self, main_root, on_click):
        self.main_root = main_root
        self.window = tk.Toplevel(main_root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#e11d48")
        tk.Button(
            self.window, text="\u274C Stop Sharing", command=on_click,
            bg="#e11d48", fg="white", font=("Segoe UI", 10, "bold"),
            relief="flat", bd=0, cursor="hand2", activebackground="#c11842",
            activeforeground="white", padx=14, pady=8
        ).pack()
        self.window.update_idletasks()
        self.window.geometry("+20+20")

    def get_rect(self):
        if not self.window:
            return None
        self.window.update_idletasks()
        x = self.window.winfo_rootx()
        y = self.window.winfo_rooty()
        return (x, y, x + self.window.winfo_width(), y + self.window.winfo_height())

    def close(self):
        if self.window:
            self.window.destroy()
            self.window = None


_active_overlay = None


def make_click_through(tk_window):
    hwnd = user32.GetParent(tk_window.winfo_id())
    if not hwnd:
        hwnd = tk_window.winfo_id()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def connect_to_relay(channel, session_id, role, retries=CONNECT_RETRIES):
    last_error = None
    for attempt in range(retries):
        try:
            ws = websocket.create_connection(RELAY_WS_URL, timeout=10)
            ws.settimeout(None)
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


def _show_file_notification(main_root, text):
    main_root.after(0, lambda: _create_file_notification(main_root, text))


def _create_file_notification(main_root, text):
    win = tk.Toplevel(main_root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg="#4CAF50")
    tk.Label(
        win, text=text, fg="white", bg="#4CAF50",
        font=("Arial", 10, "bold"), padx=10, pady=6
    ).pack()
    win.update_idletasks()
    screen_w = win.winfo_screenwidth()
    win.geometry(f"+{screen_w - win.winfo_width() - 20}+20")
    try:
        make_click_through(win)
    except Exception as e:
        log(f"File notification click-through style failed: {e}")
    win.after(4000, win.destroy)


class CursorOverlay:
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


class BorderOverlay:
    def __init__(self, main_root):
        self.main_root = main_root
        self.window = None
        self.main_root.after(0, self._create)

    def _create(self):
        self.window = tk.Toplevel(self.main_root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)

        try:
            with mss.mss() as sct:
                mon = sct.monitors[1]
            width, height = mon["width"], mon["height"]
        except Exception:
            width = self.window.winfo_screenwidth()
            height = self.window.winfo_screenheight()
        self.window.geometry(f"{width}x{height}+0+0")

        transparent_key = "#123456"
        self.window.configure(bg=transparent_key)
        try:
            self.window.attributes("-transparentcolor", transparent_key)
        except tk.TclError:
            pass

        canvas = tk.Canvas(self.window, width=width, height=height, bg=transparent_key, highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        thickness = 6
        canvas.create_rectangle(
            thickness // 2, thickness // 2,
            width - thickness // 2, height - thickness // 2,
            outline="#2196F3", width=thickness
        )

        self.window.update_idletasks()
        try:
            make_click_through(self.window)
        except Exception as e:
            log(f"BorderOverlay click-through style failed: {e}")

    def close(self):
        self.main_root.after(0, self._close)

    def _close(self):
        if self.window:
            self.window.destroy()
            self.window = None


class ScreenSharer:
    def __init__(self, main_root, session_id, username="Sharer", ws_client=None):
        self.main_root = main_root
        self.session_id = session_id
        self.username = username
        self.ws_client = ws_client
        self.running = False
        self.overlay = None
        self.border_overlay = None
        self.cmd_queue = queue.Queue()
        self._control_conn_alive = False
        self._dragging = False

        self.file_conn = None
        self._file_receiver = IncomingFileReceiver()

        self.input_guard = None
        self.stop_button = None
        self._pending_mouse_down = None

    def start(self):
        log(f"ScreenSharer.start() called for session={self.session_id} via relay {RELAY_WS_URL}")
        self.running = True

        self.input_guard = InputGuard()
        self.input_guard.start()
        self.stop_button = StopSharingButton(self.main_root, self._on_stop_button_click)
        self.input_guard.set_allowed_rect(self.stop_button.get_rect())

        self.border_overlay = BorderOverlay(self.main_root)
        threading.Thread(target=self._run_screen_channel, daemon=True).start()
        threading.Thread(target=self._run_control_channel, daemon=True).start()
        threading.Thread(target=self._command_worker, daemon=True).start()
        threading.Thread(target=self._run_file_channel, daemon=True).start()

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
                    img.save(buffer, format="JPEG", quality=68)
                    data = buffer.getvalue()

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

    def _run_control_channel(self):
        conn = connect_to_relay("control", self.session_id, "sharer")
        if conn is None:
            return

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
            if self.overlay:
                self.overlay.close()
                if _active_overlay is self.overlay:
                    _active_overlay = None
            if self.border_overlay:
                self.border_overlay.close()
                self.border_overlay = None
            try:
                conn.close()
            except Exception:
                pass

    def _host_cursor_send_thread(self, conn):
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

    def _on_stop_button_click(self):
        self.stop()

    def _run_file_channel(self):
        conn = connect_file_channel(self.session_id, "sharer")
        if conn is None:
            return
        self.file_conn = conn
        log("File channel connected (sharer side)")
        try:
            while self.running:
                raw = conn.recv()
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    self._file_receiver.write_chunk(raw)
                else:
                    self._handle_file_message(json.loads(raw), conn)
        except (websocket.WebSocketConnectionClosedException, ConnectionResetError, BrokenPipeError, OSError):
            log("File channel closed (sharer side)")

    def _handle_file_message(self, msg, conn):
        msg_type = msg.get("type")

        if msg_type == "upload_start":
            self._file_receiver.start(msg.get("filename", "file"), get_received_folder())
        elif msg_type == "upload_end":
            path = self._file_receiver.finish()
            _show_file_notification(self.main_root, f"\U0001F4E5 File received: {path}")

        elif msg_type == "download_request":
            remote_path = msg.get("filename", "")
            if remote_path and os.path.isfile(remote_path):
                try:
                    send_file_over_channel(
                        conn, remote_path, "download_data_start", "download_data_end",
                        on_complete=self._log_file_sent
                    )
                    _show_file_notification(self.main_root, f"\U0001F4E4 File sent: {os.path.basename(remote_path)}")
                except Exception as e:
                    log(f"Failed to send requested file: {e}")
                    conn.send(json.dumps({"type": "download_error", "message": str(e)}))
            else:
                conn.send(json.dumps({
                    "type": "download_error",
                    "message": f"File not found: {remote_path}"
                }))

    def _log_file_sent(self, filename, filesize):
        if self.ws_client:
            try:
                self.ws_client.send_file_transfer_log(self.session_id, filename, filesize)
            except Exception as e:
                log(f"Failed to log file transfer: {e}")

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
                if _active_overlay is not None and _active_overlay is not self.overlay:
                    _active_overlay.close()
                    _active_overlay = None
                if self.overlay is None:
                    self.overlay = CursorOverlay(self.main_root, badge_text)
                    _active_overlay = self.overlay
                else:
                    self.overlay.set_text(badge_text)

            elif action == "move":
                # Agar mouse_down "pending" hai (abhi tak decide nahi hua
                # ke ye simple click hai ya real drag), aur ab movement aa
                # gaya - to ye asal drag hai. Ab hi physical mouseDown
                # karo (drag ke liye zaroori hai), warna simple click ke
                # waqt cursor kabhi hilta hi nahi.
                if self._pending_mouse_down and not self._dragging:
                    pd = self._pending_mouse_down
                    pyautogui.mouseDown(pd["x"], pd["y"], button=pd["button"])
                    self._dragging = True

                if self._dragging:
                    pyautogui.moveTo(cmd["x"], cmd["y"], duration=0)
                if self.overlay:
                    self.overlay.move_to(cmd["x"], cmd["y"])

            elif action == "click":
                click_without_moving_cursor(cmd["x"], cmd["y"], cmd.get("button", "left"))

            elif action == "mouse_down":
                # Turant physical mouseDown mat karo - pehle wait karo
                # dekhne ke liye ke ye simple click hai ya drag. Simple
                # click ke liye asal cursor bilkul nahi hilna chahiye.
                self._pending_mouse_down = {
                    "x": cmd["x"], "y": cmd["y"], "button": cmd.get("button", "left")
                }

            elif action == "mouse_up":
                if self._dragging:
                    # Real drag ho chuka tha - normal tarah se release karo.
                    pyautogui.mouseUp(cmd["x"], cmd["y"], button=cmd.get("button", "left"))
                    pyautogui.moveTo(cmd["x"], cmd["y"], duration=0)
                    self._dragging = False
                elif self._pending_mouse_down:
                    # Beech mein koi move nahi aaya - ye simple click tha.
                    # Message-based click karo, asal cursor bilkul nahi hilega.
                    pd = self._pending_mouse_down
                    click_without_moving_cursor(pd["x"], pd["y"], pd["button"])
                self._pending_mouse_down = None

            elif action == "scroll":
                x, y = cmd.get("x"), cmd.get("y")
                try:
                    home = pyautogui.position()
                except Exception:
                    home = None
                if x is not None and y is not None:
                    pyautogui.moveTo(x, y, duration=0)
                pyautogui.scroll(cmd["amount"])
                if home is not None:
                    pyautogui.moveTo(home.x, home.y, duration=0)

            elif action == "key":
                pyautogui.press(cmd["key"])

            elif action == "hotkey":
                keys = cmd.get("keys", [])
                if keys:
                    pyautogui.hotkey(*keys)

            elif action == "type":
                pyautogui.write(cmd["text"], interval=0)

            else:
                log(f"Unknown command action received: {action}")

        except Exception as e:
            log(f"Control execution error for cmd={cmd}: {e}")

    def stop(self):
        global _active_overlay
        self.running = False
        if self.ws_client:
            try:
                self.ws_client.send_session_ended(self.session_id)
            except Exception:
                pass
        self._control_conn_alive = False
        if self.input_guard:
            self.input_guard.stop()
            self.input_guard = None
        if self.stop_button:
            self.stop_button.close()
            self.stop_button = None
        if self.overlay:
            self.overlay.close()
            if _active_overlay is self.overlay:
                _active_overlay = None
        if self.border_overlay:
            self.border_overlay.close()
            self.border_overlay = None
        if self.file_conn:
            try:
                self.file_conn.close()
            except Exception:
                pass