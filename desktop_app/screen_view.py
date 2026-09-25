import os
import socket
import threading
import queue
import time
import json
import ctypes
import ctypes.wintypes as wintypes
from io import BytesIO
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog
from tkinterdnd2 import DND_FILES
import websocket
from debug_log import log
from file_transfer import (
    connect_file_channel, send_file_over_channel, IncomingFileReceiver, get_received_folder
)

# Relay WebSocket (wss://) ke through, VPS ke already-open HTTPS (443) port par.
RELAY_WS_URL = "wss://skydesk.skyfinancia.com/relay/"


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x00000010
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_D = 0x44

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class WinSnapGuard:
    """Jab viewer window focused ho, Win+Arrow/Win+D ko Windows OS ke
    khud snap/minimize karne se PEHLE hi 'chura' leta hai (suppress kar
    deta hai) - taake ye sirf remote ko forward ho, aur controller ki
    apni window kabhi snap na ho."""

    ARROW_KEYS = {VK_LEFT: "left", VK_UP: "up", VK_RIGHT: "right", VK_DOWN: "down"}

    def __init__(self, get_hwnd, on_win_combo):
        self._get_hwnd = get_hwnd
        self._on_win_combo = on_win_combo
        self._win_down = False
        self._thread = None
        self._thread_id = None
        self._hook = None
        self._proc_ref = None
        self._running = False

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        self._proc_ref = HOOKPROC(self._proc)
        hmod = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc_ref, hmod, 0)
        msg = wintypes.MSG()
        while self._running:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)

    def _proc(self, nCode, wParam, lParam):
        WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
        if nCode == 0:
            info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if not (info.flags & LLKHF_INJECTED):
                our_hwnd = self._get_hwnd()
                is_our_window = our_hwnd and user32.GetForegroundWindow() == our_hwnd

                if info.vkCode in (VK_LWIN, VK_RWIN):
                    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        self._win_down = True
                    elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                        self._win_down = False

                elif self._win_down and is_our_window and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    if info.vkCode in self.ARROW_KEYS:
                        self._on_win_combo(self.ARROW_KEYS[info.vkCode])
                        return 1  # suppress - controller ki apni window snap nahi hogi
                    elif info.vkCode == VK_D:
                        self._on_win_combo("d")
                        return 1
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def stop(self):
        self._running = False
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=2)


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
        "prior": "pageup",
        "next": "pagedown",
        "f1": "f1",
        "f2": "f2",
        "f3": "f3",
        "f4": "f4",
        "f5": "f5",
        "f6": "f6",
        "f7": "f7",
        "f8": "f8",
        "f9": "f9",
        "f10": "f10",
        "f11": "f11",
        "f12": "f12",
    }

    MODIFIER_KEYSYMS = {"control_l", "control_r", "alt_l", "alt_r", "shift_l", "shift_r", "super_l", "super_r"}

    CONNECT_RETRIES = 15
    CONNECT_RETRY_DELAY = 1
    FRAME_POLL_MS = 16            # ~60Hz GUI poll (sirf tab draw hota hai jab naya frame ho)
    SOCKET_TIMEOUT = 30
    MOVE_SEND_INTERVAL = 0.012    # max ~80 mouse-move/sec

    def __init__(self, session_id, my_username="User", ws_client=None):
        self.session_id = session_id
        self.my_username = my_username
        self.ws_client = ws_client
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
        # remote_width/height SIRF screen_info se aate hain (sharer ki asal
        # screen size) - frame size se nahi, kyunke sharer frame downscale
        # karta hai. Clicks asal size ke hisab se map hote hain.
        self.remote_width = None
        self.remote_height = None
        self._photo_ref = None

        # Pipeline: recv thread (raw bytes) -> decode thread -> GUI thread.
        # Har stage sirf LATEST item rakhta hai, purane drop ho jate hain.
        self._frame_lock = threading.Lock()
        self._raw_frame = None
        self._last_raw = None
        self._frame_event = threading.Event()
        self._pending_frame = None
        self._last_frame_time = None

        self.file_conn = None
        self._file_receiver = IncomingFileReceiver()

        # Commands queue hote hain, alag thread bhejta hai - GUI kabhi block nahi hota.
        # Mouse "move" coalesce hota hai (sirf latest move bhejo).
        self._cmd_send_queue = queue.Queue()
        self._cmd_lock = threading.Lock()
        self._cmd_event = threading.Event()
        self._pending_move = None

        self._connection_lost_shown = False
        self._modifiers_held = set()
        self._gen = 0   # reconnect ke waqt purane threads ko band karne ke liye

        self._mouse_down_pos = None
        self.LOCAL_DRAG_THRESHOLD = 4

        self._win_snap_guard = None
        self.FRAME_TIMEOUT_SECONDS = 15   # sharer har 2s mein keepalive frame bhejta hai

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

        # Drag & drop: file seedha window pe drop karke bhej sakte hain.
        self.window.drop_target_register(DND_FILES)
        self.window.dnd_bind("<<Drop>>", self._on_file_drop)

        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonPress-1>", lambda e: self._on_mouse_down(e, "left"))
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: self._on_mouse_up(e, "left"))
        self.canvas.bind("<Leave>", lambda e: self._on_mouse_up(e, "left"))
        self.canvas.bind("<Button-3>", lambda e: self._on_click(e, "right"))
        self.canvas.bind("<MouseWheel>", self._on_scroll)
        self.window.bind("<Key>", self._on_key)
        self.window.bind("<KeyRelease>", self._on_key_release)
        self.window.bind("<Configure>", self._on_resize)
        # Safety net: focus change par modifiers clear.
        self.window.bind("<FocusIn>", lambda e: self._modifiers_held.clear())
        self.window.bind("<FocusOut>", lambda e: self._modifiers_held.clear())
        self.canvas.focus_set()
        self.window.protocol("WM_DELETE_WINDOW", self.stop)

        self.send_file_btn = tk.Button(
            self.window, text="\U0001F4E4 Send File", command=self._send_file_dialog,
            bg="#4CAF50", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", bd=0, cursor="hand2"
        )
        self.send_file_btn.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)

        self.request_file_btn = tk.Button(
            self.window, text="\U0001F4E5 Request File", command=self._request_file_dialog,
            bg="#FF9800", fg="white", font=("Segoe UI", 9, "bold"),
            relief="flat", bd=0, cursor="hand2"
        )
        self.request_file_btn.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=48)

        self.window.update_idletasks()
        self.window.state("zoomed")
        self.window.update_idletasks()
        self.win_width = self.window.winfo_width()
        self.win_height = self.window.winfo_height()

        self.running = True

        # Ek hi command-send thread poori session ke liye (reconnect par dobara nahi banta).
        threading.Thread(target=self._command_send_loop, daemon=True).start()
        threading.Thread(target=self._decode_loop, daemon=True).start()
        threading.Thread(target=self._connect_file_channel, daemon=True).start()
        self._start_stream_threads()

        self._win_snap_guard = WinSnapGuard(self._get_window_hwnd, self._on_win_combo)
        self._win_snap_guard.start()

        self.window.after(self.FRAME_POLL_MS, self._poll_frame)

    def _start_stream_threads(self):
        """Screen + control + watchdog threads (reconnect par bhi yahi chalta hai)."""
        self._gen += 1
        gen = self._gen
        with self._frame_lock:
            self._last_frame_time = None
        threading.Thread(target=self._connect_screen_stream, args=(gen,), daemon=True).start()
        threading.Thread(target=self._connect_control, args=(gen,), daemon=True).start()
        threading.Thread(target=self._frame_watchdog, args=(gen,), daemon=True).start()

    def _get_window_hwnd(self):
        if not self.window:
            return None
        try:
            hwnd = user32.GetParent(self.window.winfo_id())
            return hwnd if hwnd else self.window.winfo_id()
        except Exception:
            return None

    def _on_win_combo(self, key):
        # WinSnapGuard ki background thread se call hota hai - sirf queue.put, koi Tk call nahi.
        self._send_command({"action": "hotkey", "keys": ["win", key]})

    def _frame_watchdog(self, gen):
        """Agar screen channel se bohot der koi frame na aaye to user ko batao."""
        while self.running and gen == self._gen:
            time.sleep(2)
            with self._frame_lock:
                last = self._last_frame_time
            if last and (time.time() - last) > self.FRAME_TIMEOUT_SECONDS:
                if self.window and gen == self._gen:
                    self.window.after(0, self._show_connection_lost)
                break

    def _connect_relay(self, channel, gen=None):
        last_error = None
        for attempt in range(self.CONNECT_RETRIES):
            if not self.running or (gen is not None and gen != self._gen):
                return None
            try:
                ws = websocket.create_connection(
                    RELAY_WS_URL, timeout=10,
                    sockopt=((socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
                             (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1))
                )
                ws.settimeout(self.SOCKET_TIMEOUT)
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

    # ------------------------------------------------------------------
    # SCREEN: recv thread (raw bytes only) -> decode thread -> GUI
    # ------------------------------------------------------------------
    def _connect_screen_stream(self, gen):
        sock = self._connect_relay("screen", gen)
        if sock is None:
            if self.window and self.running and gen == self._gen:
                self.window.after(0, self._connection_failed)
            return

        log("Connected to sharer (screen) via relay!")

        try:
            while self.running and gen == self._gen:
                try:
                    data = sock.recv()
                except websocket.WebSocketTimeoutException:
                    continue   # screen static thi, frame nahi aaya - normal
                if not data or isinstance(data, str):
                    continue
                # Sirf raw bytes rakho - purana undecoded frame drop ho jata hai.
                with self._frame_lock:
                    self._raw_frame = data
                    self._last_frame_time = time.time()
                self._frame_event.set()
        except Exception as e:
            log(f"Screen stream ended: {e}")
            if self.running and gen == self._gen and self.window:
                self.window.after(0, self._show_connection_lost)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _decode_loop(self):
        while self.running:
            if not self._frame_event.wait(0.5):
                continue
            self._frame_event.clear()
            with self._frame_lock:
                raw, self._raw_frame = self._raw_frame, None
            if raw is None:
                continue
            self._last_raw = raw
            try:
                img = Image.open(BytesIO(raw))
                # Purane sharer (jo downscale nahi karte) ke saath compatible:
                # agar screen_info abhi tak nahi aaya to frame ki asal size use
                # karo. Naya sharer screen_info bhejta hai jo ise override kar deta hai.
                if self.remote_width is None:
                    self.remote_width, self.remote_height = img.width, img.height
                win_w = max(self.win_width, 100)
                win_h = max(self.win_height, 100)
                scale = min(win_w / img.width, win_h / img.height)
                new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
                if img.format == "JPEG":
                    img.draft("RGB", new_size)   # JPEG ko chhota hi decode karo - bohot fast
                img.load()
                if img.size != new_size:
                    img = img.resize(new_size, Image.BILINEAR)
                ox = (win_w - new_size[0]) // 2
                oy = (win_h - new_size[1]) // 2
                with self._frame_lock:
                    self._pending_frame = (img, ox, oy)
            except Exception as e:
                log(f"Decode failed: {e}")

    def _poll_frame(self):
        """GUI thread par: sirf latest frame draw karo."""
        if not self.running:
            return

        with self._frame_lock:
            frame, self._pending_frame = self._pending_frame, None

        if frame is not None:
            self._update_image(*frame)

        self.window.after(self.FRAME_POLL_MS, self._poll_frame)

    def _update_image(self, img, ox, oy):
        self.got_first_frame = True
        self._photo_ref = ImageTk.PhotoImage(img)
        self.canvas.itemconfig(self.canvas_image_id, image=self._photo_ref)
        self.canvas.coords(self.canvas_image_id, ox, oy)
        if self.status_text_id:
            self.canvas.itemconfig(self.status_text_id, text="")
        if self.host_cursor_id is not None:
            self.canvas.tag_raise(self.host_cursor_id)
            self.canvas.tag_raise(self.host_cursor_label_id)

    def _connection_failed(self):
        if self.canvas and self.status_text_id:
            self.canvas.itemconfig(
                self.status_text_id,
                text="Could not connect. The other user may be offline or the relay server is down."
            )
        messagebox.showerror(
            "Connection Failed",
            "Could not connect to the remote screen.\n\n"
            "Please check:\n"
            "- The other user is still online\n"
            "- Your internet connection is working"
        )

    def _show_connection_lost(self):
        if self._connection_lost_shown or not self.running:
            return
        self._connection_lost_shown = True

        if self.canvas and self.status_text_id:
            self.canvas.itemconfig(
                self.status_text_id,
                text="Connection lost. The other computer may have disconnected."
            )

        retry = messagebox.askretrycancel(
            "Connection Lost",
            "Lost connection to the remote computer.\n"
            "This can happen if their internet disconnected unexpectedly.\n\n"
            "Try to reconnect?"
        )
        if not self.running:
            return
        if retry:
            self._connection_lost_shown = False
            if self.control_sock:
                try:
                    self.control_sock.close()
                except Exception:
                    pass
                self.control_sock = None
            # Screen + control + watchdog teeno dobara start
            self._start_stream_threads()
        else:
            self.stop()

    def _on_resize(self, event):
        if event.widget is self.window:
            self.win_width = event.width
            self.win_height = event.height
            # Static screen par bhi naye size par turant re-scale karo
            with self._frame_lock:
                if self._raw_frame is None and self._last_raw is not None:
                    self._raw_frame = self._last_raw
            self._frame_event.set()

    # ------------------------------------------------------------------
    # CONTROL
    # ------------------------------------------------------------------
    def _connect_control(self, gen):
        sock = self._connect_relay("control", gen)
        if sock is None:
            return
        if gen != self._gen:
            try:
                sock.close()
            except Exception:
                pass
            return
        self.control_sock = sock
        log("Connected to sharer (control) via relay!")

        threading.Thread(target=self._control_read_loop, args=(sock, gen), daemon=True).start()
        self._send_command({"action": "identify", "name": self.my_username})

    def _control_read_loop(self, sock, gen):
        try:
            while self.running and gen == self._gen:
                try:
                    raw = sock.recv()
                except websocket.WebSocketTimeoutException:
                    continue   # idle - normal
                if not raw or isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self._handle_control_message(msg)
        except Exception as e:
            log(f"Control channel closed: {e}")
            if self.running and gen == self._gen and self.window:
                self.window.after(0, self._show_connection_lost)

    def _handle_control_message(self, msg):
        action = msg.get("action")
        if action == "screen_info":
            self.remote_width = msg.get("width")
            self.remote_height = msg.get("height")
            log(f"Remote resolution from screen_info: {self.remote_width}x{self.remote_height}")
        elif action == "host_cursor":
            x, y = msg.get("x"), msg.get("y")
            name = msg.get("name", "Sharer")
            if self.window:
                self.window.after(0, self._draw_host_cursor, x, y, name)

    # ---------- FILE TRANSFER (via relay, separate channel) ----------
    def _connect_file_channel(self):
        conn = connect_file_channel(self.session_id, "viewer")
        if conn is None:
            return
        self.file_conn = conn
        log("Connected to sharer (file) via relay!")
        try:
            while self.running:
                raw = conn.recv()
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    self._file_receiver.write_chunk(raw)
                else:
                    self._handle_file_message(json.loads(raw))
        except (websocket.WebSocketConnectionClosedException, ConnectionResetError, BrokenPipeError, OSError):
            log("File channel closed")

    def _handle_file_message(self, msg):
        msg_type = msg.get("type")

        if msg_type == "upload_start":
            self._file_receiver.start(msg.get("filename", "file"), get_received_folder())
        elif msg_type == "upload_end":
            path = self._file_receiver.finish()
            if self.window:
                self.window.after(0, lambda: messagebox.showinfo(
                    "File Received", f"File saved to:\n{path}"
                ))

        elif msg_type == "download_data_start":
            self._file_receiver.start(msg.get("filename", "file"), get_received_folder())
        elif msg_type == "download_data_end":
            path = self._file_receiver.finish()
            if self.window:
                self.window.after(0, lambda: messagebox.showinfo(
                    "Download Complete", f"File saved to:\n{path}"
                ))
        elif msg_type == "download_error":
            error_msg = msg.get("message", "File not found on remote device.")
            if self.window:
                self.window.after(0, lambda: messagebox.showerror("Download Failed", error_msg))

    def _send_file_dialog(self):
        filepath = filedialog.askopenfilename(title="Select a file to send")
        if not filepath:
            return
        self._send_file(filepath)

    def _on_file_drop(self, event):
        paths = self.window.tk.splitlist(event.data)
        for path in paths:
            if os.path.isfile(path):
                self._send_file(path)
            else:
                messagebox.showwarning("Not a File", f"Skipped (not a file):\n{path}")

    def _send_file(self, filepath):
        if not self.file_conn:
            messagebox.showwarning("Not Connected", "File channel is not connected yet. Please wait a moment.")
            return
        try:
            threading.Thread(
                target=send_file_over_channel,
                args=(self.file_conn, filepath, "upload_start", "upload_end"),
                kwargs={"on_complete": self._log_file_sent},
                daemon=True
            ).start()
            messagebox.showinfo("Sending", f"Sending '{os.path.basename(filepath)}' to the remote computer...")
        except Exception as e:
            messagebox.showerror("Send Failed", str(e))

    def _log_file_sent(self, filename, filesize):
        if self.ws_client:
            try:
                self.ws_client.send_file_transfer_log(self.session_id, filename, filesize)
            except Exception as e:
                log(f"Failed to log file transfer: {e}")

    def _request_file_dialog(self):
        if not self.file_conn:
            messagebox.showwarning("Not Connected", "File channel is not connected yet. Please wait a moment.")
            return
        remote_path = simpledialog.askstring(
            "Request File",
            "Enter the full file path on the remote computer\n(e.g. C:\\Users\\Name\\Desktop\\file.pdf):",
            parent=self.window
        )
        if not remote_path:
            return
        self.file_conn.send(json.dumps({"type": "download_request", "filename": remote_path}))
        messagebox.showinfo("Request Sent", "Waiting for the remote computer to send the file...")

    def _draw_host_cursor(self, x, y, name="Sharer"):
        if x is None or y is None or not self.remote_width or not self.remote_height:
            return
        win_w = max(self.win_width, 100)
        win_h = max(self.win_height, 100)
        scale = min(win_w / self.remote_width, win_h / self.remote_height)
        offset_x = (win_w - self.remote_width * scale) / 2
        offset_y = (win_h - self.remote_height * scale) / 2
        cx = offset_x + x * scale
        cy = offset_y + y * scale

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

    # ------------------------------------------------------------------
    # COMMAND SENDING (mouse move coalescing)
    # ------------------------------------------------------------------
    def _send_command(self, cmd):
        """GUI thread se seedha network pe mat likho. Move commands overwrite
        hote hain (sirf latest bhejo); baaki commands order mein queue hote hain,
        aur click se pehle latest move flush hoti hai."""
        with self._cmd_lock:
            if cmd.get("action") == "move":
                self._pending_move = cmd
            else:
                if self._pending_move:
                    self._cmd_send_queue.put(self._pending_move)
                    self._pending_move = None
                self._cmd_send_queue.put(cmd)
        self._cmd_event.set()

    def _raw_send(self, cmd):
        sock = self.control_sock
        if not sock:
            return
        try:
            sock.send(json.dumps(cmd))
        except Exception as e:
            log(f"Failed to send control command: {e}")
            time.sleep(0.3)

    def _command_send_loop(self):
        while self.running:
            self._cmd_event.wait(0.5)
            self._cmd_event.clear()
            sent_move = False
            while True:
                try:
                    cmd = self._cmd_send_queue.get_nowait()
                except queue.Empty:
                    break
                self._raw_send(cmd)
            with self._cmd_lock:
                move, self._pending_move = self._pending_move, None
            if move:
                self._raw_send(move)
                sent_move = True
            if sent_move:
                time.sleep(self.MOVE_SEND_INTERVAL)

    def _scale_coords(self, x, y):
        if not self.remote_width or not self.remote_height or not self.win_width or not self.win_height:
            return x, y

        win_w = max(self.win_width, 100)
        win_h = max(self.win_height, 100)
        scale = min(win_w / self.remote_width, win_h / self.remote_height)
        drawn_w = self.remote_width * scale
        drawn_h = self.remote_height * scale
        offset_x = (win_w - drawn_w) / 2
        offset_y = (win_h - drawn_h) / 2

        rel_x = min(max(x - offset_x, 0), drawn_w)
        rel_y = min(max(y - offset_y, 0), drawn_h)

        real_x = int(rel_x / scale)
        real_y = int(rel_y / scale)
        real_x = max(0, min(real_x, self.remote_width - 1))
        real_y = max(0, min(real_y, self.remote_height - 1))
        return real_x, real_y

    def _on_mouse_move(self, event):
        x, y = self._scale_coords(event.x, event.y)
        self._send_command({"action": "move", "x": x, "y": y})

    def _on_click(self, event, button):
        x, y = self._scale_coords(event.x, event.y)
        self._send_command({"action": "click", "x": x, "y": y, "button": button})

    def _on_mouse_down(self, event, button):
        self._mouse_down_pos = (event.x, event.y)
        x, y = self._scale_coords(event.x, event.y)
        self._send_command({"action": "mouse_down", "x": x, "y": y, "button": button})

    def _on_drag(self, event):
        # Chhoti hath ki jitter ko sharer tak mat bhejo.
        if self._mouse_down_pos:
            dx = abs(event.x - self._mouse_down_pos[0])
            dy = abs(event.y - self._mouse_down_pos[1])
            if dx < self.LOCAL_DRAG_THRESHOLD and dy < self.LOCAL_DRAG_THRESHOLD:
                return
        x, y = self._scale_coords(event.x, event.y)
        self._send_command({"action": "move", "x": x, "y": y})

    def _on_mouse_up(self, event, button):
        self._mouse_down_pos = None
        x, y = self._scale_coords(event.x, event.y)
        self._send_command({"action": "mouse_up", "x": x, "y": y, "button": button})

    def _on_scroll(self, event):
        x, y = self._scale_coords(event.x, event.y)
        self._send_command({"action": "scroll", "amount": event.delta, "x": x, "y": y})

    def _on_key(self, event):
        keysym = event.keysym.lower()

        if keysym in self.MODIFIER_KEYSYMS:
            self._modifiers_held.add(keysym)
            return  # sirf modifier dabane se kuch bhejna nahi

        ctrl_held = "control_l" in self._modifiers_held or "control_r" in self._modifiers_held
        alt_held = "alt_l" in self._modifiers_held or "alt_r" in self._modifiers_held
        shift_held = "shift_l" in self._modifiers_held or "shift_r" in self._modifiers_held
        win_held = "super_l" in self._modifiers_held or "super_r" in self._modifiers_held

        # Ctrl/Alt ke sath koi bhi key = shortcut. Shift ke sath sirf named
        # keys (arrow, Home, End...) hotkey banti hain; Shift+letter event.char se aa jata hai.
        needs_shift_combo = shift_held and keysym in self.KEY_MAP

        if ctrl_held or alt_held or win_held or needs_shift_combo:
            base_key = self.KEY_MAP.get(keysym, keysym)
            modifiers = []
            if ctrl_held:
                modifiers.append("ctrl")
            if alt_held:
                modifiers.append("alt")
            if shift_held:
                modifiers.append("shift")
            if win_held:
                modifiers.append("win")
            self._send_command({"action": "hotkey", "keys": modifiers + [base_key]})
            return

        if keysym in self.KEY_MAP:
            self._send_command({"action": "key", "key": self.KEY_MAP[keysym]})
        elif len(event.char) == 1 and event.char.isprintable():
            self._send_command({"action": "type", "text": event.char})

    def _on_key_release(self, event):
        self._modifiers_held.discard(event.keysym.lower())

    def _prompt_unlock(self):
        dialog = tk.Toplevel(self.window)
        dialog.title("Unlock Remote PC")
        dialog.configure(bg="#ffffff")
        dialog.resizable(False, False)
        dialog.transient(self.window)
        dialog.grab_set()

        pad = tk.Frame(dialog, bg="#ffffff")
        pad.pack(padx=24, pady=20)

        tk.Label(
            pad, text="Enter the remote PC's password", font=("Segoe UI", 11, "bold"),
            bg="#ffffff"
        ).pack(anchor="w", pady=(0, 10))

        entry = tk.Entry(pad, font=("Segoe UI", 11), show="*", width=28)
        entry.pack(fill="x", ipady=6)
        entry.focus_set()

        def submit():
            password = entry.get()
            dialog.destroy()
            if password:
                self._send_command({"action": "unlock_request", "password": password})

        entry.bind("<Return>", lambda e: submit())

        btn_row = tk.Frame(pad, bg="#ffffff")
        btn_row.pack(fill="x", pady=(14, 0))
        tk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side="left", expand=True, fill="x", padx=(0, 4))
        tk.Button(btn_row, text="Unlock", command=submit, bg="#2196F3", fg="white").pack(side="left", expand=True, fill="x", padx=(4, 0))

        dialog.update_idletasks()
        w, h = dialog.winfo_width(), dialog.winfo_height()
        x = self.window.winfo_x() + (self.window.winfo_width() - w) // 2
        y = self.window.winfo_y() + (self.window.winfo_height() - h) // 2
        dialog.geometry(f"+{x}+{y}")

    def stop(self):
        self.running = False
        self._gen += 1
        self._frame_event.set()
        self._cmd_event.set()
        if self._win_snap_guard:
            self._win_snap_guard.stop()
            self._win_snap_guard = None
        if self.ws_client:
            try:
                self.ws_client.send_session_ended(self.session_id)
            except Exception:
                pass
        if self.control_sock:
            try:
                self.control_sock.close()
            except Exception:
                pass
        if self.file_conn:
            try:
                self.file_conn.close()
            except Exception:
                pass
        if self.window:
            self.window.destroy()
