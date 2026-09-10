import os
import threading
import queue
import time
import json
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

    MODIFIER_KEYSYMS = {"control_l", "control_r", "alt_l", "alt_r", "shift_l", "shift_r"}

    CONNECT_RETRIES = 15
    CONNECT_RETRY_DELAY = 1
    FRAME_POLL_MS = 33  # ~30fps GUI refresh cap, independent of network arrival rate

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
        self.remote_width = None
        self.remote_height = None
        self._photo_ref = None

        # Latest-frame-only buffer: the network thread overwrites this as
        # fast as frames arrive; the GUI polls it at a fixed rate. This
        # prevents thousands of stale after() callbacks from piling up if
        # the window is minimized/backgrounded for a while (e.g. the user
        # steps away for a few minutes) - old frames are simply dropped
        # instead of queued, so there's no backlog to "catch up" on.
        self._frame_lock = threading.Lock()
        self._pending_frame = None

        self.file_conn = None
        self._file_receiver = IncomingFileReceiver()

        # Commands (mouse/keyboard) yahan queue hote hain, ek alag thread
        # unhe bhejta hai - taake agar network atak jaye (jaise doosri
        # taraf ka internet achanak chala jaye), to GUI thread kabhi
        # block/"Not Responding" na ho.
        self._cmd_send_queue = queue.Queue()
        self._connection_lost_shown = False
        self._modifiers_held = set()

        # Drag detection ab viewer window ke apne (unscaled) pixels mein
        # hoti hai, scaling se pehle - taake chhoti window se bari remote
        # screen tak scale hone par hath ki halki jitter amplify ho kar
        # false drag na trigger kare.
        self._mouse_down_pos = None
        self.LOCAL_DRAG_THRESHOLD = 4
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

        # Drag & drop: OS file explorer se koi bhi file seedha is window
        # pe drop karke bhej sakte hain, jaisa AnyDesk mein hota hai.
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
        threading.Thread(target=self._connect_screen_stream, daemon=True).start()
        threading.Thread(target=self._connect_control, daemon=True).start()
        threading.Thread(target=self._connect_file_channel, daemon=True).start()

        # Start the fixed-rate GUI poll loop (main thread only).
        self.window.after(self.FRAME_POLL_MS, self._poll_frame)

    def _connect_relay(self, channel):
        last_error = None
        for attempt in range(self.CONNECT_RETRIES):
            if not self.running and attempt > 0:
                return None
            try:
                ws = websocket.create_connection(RELAY_WS_URL, timeout=10)
                ws.sock.settimeout(30)  # 30s ke andar kuch na aaye to socket dead maan lo
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
                img.load()  # decode now, off the GUI thread

                if self.remote_width is None:
                    self.remote_width, self.remote_height = img.size
                    log(f"Remote resolution detected from frame: {self.remote_width}x{self.remote_height}")

                # Just overwrite the pending frame - never queue. If the GUI
                # thread hasn't had a chance to render the previous one yet
                # (e.g. window was backgrounded), it gets dropped instead of
                # piling up.
                with self._frame_lock:
                    self._pending_frame = img
        except (websocket.WebSocketConnectionClosedException, ConnectionResetError, BrokenPipeError, OSError):
            log("Sharer disconnected")
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _poll_frame(self):
        """Runs on the main/GUI thread at a fixed rate. Renders the latest
        available frame, if any, then reschedules itself. This decouples
        rendering from network arrival rate so we never build a backlog."""
        if not self.running:
            return

        with self._frame_lock:
            img = self._pending_frame
            self._pending_frame = None

        if img is not None:
            self._update_image(img)

        self.window.after(self.FRAME_POLL_MS, self._poll_frame)

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
            threading.Thread(target=self._connect_control, daemon=True).start()
        else:
            self.stop()

    def _on_resize(self, event):
        if event.widget is self.window:
            self.win_width = event.width
            self.win_height = event.height

    def _update_image(self, img):
        self.got_first_frame = True
        win_w = max(self.win_width, 100)
        win_h = max(self.win_height, 100)
        img_w, img_h = img.size

        # Aspect ratio preserve karo - stretch/distort mat karo. Jo shape
        # match nahi hoti, us hisse ko kaale background se bhar do
        # (letterbox), jaisa video players karte hain.
        scale = min(win_w / img_w, win_h / img_h)
        new_w = max(1, int(img_w * scale))
        new_h = max(1, int(img_h * scale))
        if (new_w, new_h) != img.size:
            img = img.resize((new_w, new_h), Image.LANCZOS)

        canvas_img = Image.new("RGB", (win_w, win_h), (34, 34, 34))
        offset_x = (win_w - new_w) // 2
        offset_y = (win_h - new_h) // 2
        canvas_img.paste(img, (offset_x, offset_y))

        self._photo_ref = ImageTk.PhotoImage(canvas_img)
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

        threading.Thread(target=self._control_read_loop, daemon=True).start()
        threading.Thread(target=self._command_send_loop, daemon=True).start()
        self._send_command({"action": "identify", "name": self.my_username})

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
            if self.running and self.window:
                self.window.after(0, self._show_connection_lost)

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
        # event.data mein ek ya zyada paths ho sakte hain, spaces wale
        # paths curly braces {} mein wrapped aate hain - tk.splitlist
        # ye sahi tarah parse kar deta hai.
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

    def _send_command(self, cmd):
        # GUI thread se seedha network pe kabhi mat likho - queue kar do,
        # background thread hi asal socket.send() karega.
        self._cmd_send_queue.put(cmd)

    def _command_send_loop(self):
        """Background thread jo queue se commands nikal kar bhejta hai.
        Agar network atki hui ho (send() block ho jaye), sirf ye thread
        rukta hai - GUI hamesha responsive rehti hai."""
        while self.running:
            try:
                cmd = self._cmd_send_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.control_sock:
                try:
                    self.control_sock.send(json.dumps(cmd))
                except Exception as e:
                    log(f"Failed to send control command: {e}")
                    # Connection mar chuki hai - is se aage bhejna
                    # faltu hai, aur naye connect ka wait karna better hai.
                    time.sleep(0.5)

    def _scale_coords(self, x, y):
        if not self.remote_width or not self.remote_height or not self.win_width or not self.win_height:
            return x, y

        # _update_image jaisa hi letterbox calculation - taake click
        # exactly wahin jaye jahan image dikh rahi hai, kaali patti
        # (letterbox) ke offset ko dhyan mein rakhte hue.
        win_w = max(self.win_width, 100)
        win_h = max(self.win_height, 100)
        scale = min(win_w / self.remote_width, win_h / self.remote_height)
        drawn_w = self.remote_width * scale
        drawn_h = self.remote_height * scale
        offset_x = (win_w - drawn_w) / 2
        offset_y = (win_h - drawn_h) / 2

        # Click position ko image area ke andar clamp karo (kaali patti
        # pe click ho to nearest edge maan lo).
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
        # Jab tak viewer window ke apne (unscaled) pixels mein itni
        # distance na ho jaye, "move" bhejo hi mat - taake click ke
        # waqt hath ki chhoti jitter sharer tak pahunche hi nahi.
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

        if ctrl_held or alt_held:
            # Ctrl/Alt ke sath koi bhi key = shortcut (Ctrl+C, Ctrl+V,
            # Alt+Tab waghera) - poora combo ek "hotkey" command mein bhejo.
            base_key = self.KEY_MAP.get(keysym, keysym)
            modifiers = []
            if ctrl_held:
                modifiers.append("ctrl")
            if alt_held:
                modifiers.append("alt")
            if shift_held:
                modifiers.append("shift")
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