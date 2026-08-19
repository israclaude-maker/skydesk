import tkinter as tk
from tkinter import messagebox
from ws_client import WSClient
from debug_log import log


def round_rect(canvas, x1, y1, x2, y2, radius=16, **kwargs):
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class Theme:
    BG = "#f5f6fb"
    CARD_BG = "#ffffff"
    CARD_BORDER = "#e9eaf3"
    SHADOW = "#e4e5f1"
    ACCENT = "#6d5efc"
    ACCENT_HOVER = "#5b4dfa"
    ACCENT_SOFT = "#efecff"
    FIELD_BG = "#f7f8fc"
    FIELD_BORDER = "#e3e5f0"
    FIELD_FOCUS = "#6d5efc"
    TEXT_PRIMARY = "#1f2333"
    TEXT_MUTED = "#8b8fa3"
    ONLINE = "#16a34a"
    ONLINE_BG = "#e7f8ee"
    OFFLINE = "#e11d48"
    OFFLINE_BG = "#fdeaec"
    CONNECTING = "#d97706"
    CONNECTING_BG = "#fdf3e2"
    DANGER = "#e11d48"
    DANGER_BORDER = "#f6d9de"
    DANGER_HOVER = "#fdeef0"


class RoundedCard(tk.Frame):
    """A white rounded card with a soft shadow. Supports resize() so its
    height can grow/shrink smoothly when its content changes (e.g. a
    collapsible field being shown/hidden) without clipping anything."""

    def __init__(self, parent, width, height, radius=18):
        super().__init__(parent, bg=Theme.BG)
        self.width = width
        self.height = height
        self.radius = radius
        self.canvas = tk.Canvas(self, width=width + 10, height=height + 10, bg=Theme.BG, highlightthickness=0)
        self.canvas.pack()
        self.shadow_id = None
        self.card_id = None
        self.content = tk.Frame(self.canvas, bg=Theme.CARD_BG)
        self._draw()
        self.window_id = self.canvas.create_window(
            (width + 4) / 2, (height + 4) / 2, window=self.content, width=width - 8, height=height - 8
        )

    def _draw(self):
        if self.shadow_id:
            self.canvas.delete(self.shadow_id)
        if self.card_id:
            self.canvas.delete(self.card_id)
        self.shadow_id = round_rect(
            self.canvas, 6, 8, self.width + 6, self.height + 8, radius=self.radius, fill=Theme.SHADOW, outline=""
        )
        self.card_id = round_rect(
            self.canvas, 2, 2, self.width + 2, self.height + 2, radius=self.radius,
            fill=Theme.CARD_BG, outline=Theme.CARD_BORDER
        )

    def resize(self, new_height):
        self.height = new_height
        self.canvas.config(height=new_height + 10)
        self._draw()
        self.canvas.coords(self.window_id, (self.width + 4) / 2, (new_height + 4) / 2)
        self.canvas.itemconfig(self.window_id, height=new_height - 8)
        self.canvas.tag_raise(self.window_id)


class PinDialog(tk.Toplevel):
    """A themed replacement for tkinter's default simpledialog, matching
    the rest of the app's visual style."""

    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("Set Access PIN")
        self.configure(bg=Theme.CARD_BG)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        pad = tk.Frame(self, bg=Theme.CARD_BG)
        pad.pack(padx=28, pady=24)

        tk.Label(
            pad, text="Set Access PIN", font=("Segoe UI", 13, "bold"),
            bg=Theme.CARD_BG, fg=Theme.TEXT_PRIMARY
        ).pack(anchor="w")
        tk.Label(
            pad, text="Enter a new PIN (4+ digits, numbers only).\nLeave blank and click Save to remove the PIN.",
            font=("Segoe UI", 9), bg=Theme.CARD_BG, fg=Theme.TEXT_MUTED, justify="left"
        ).pack(anchor="w", pady=(4, 16))

        wrap = tk.Frame(pad, bg=Theme.FIELD_BG, highlightthickness=1,
                         highlightbackground=Theme.FIELD_BORDER, highlightcolor=Theme.FIELD_FOCUS)
        wrap.pack(fill="x")
        self.entry = tk.Entry(
            wrap, font=("Consolas", 13), relief="flat", bg=Theme.FIELD_BG,
            fg=Theme.TEXT_PRIMARY, insertbackground=Theme.TEXT_PRIMARY, bd=0,
            highlightthickness=0, show="\u2022", justify="center"
        )
        self.entry.pack(fill="x", padx=10, ipady=9)
        self.entry.bind("<FocusIn>", lambda e: wrap.config(highlightbackground=Theme.FIELD_FOCUS))
        self.entry.bind("<FocusOut>", lambda e: wrap.config(highlightbackground=Theme.FIELD_BORDER))
        self.entry.bind("<Return>", lambda e: self._save())
        self.entry.bind("<Escape>", lambda e: self._cancel())

        btn_row = tk.Frame(pad, bg=Theme.CARD_BG)
        btn_row.pack(fill="x", pady=(18, 0))

        cancel_btn = tk.Button(
            btn_row, text="Cancel", command=self._cancel,
            bg=Theme.CARD_BG, fg=Theme.TEXT_MUTED, font=("Segoe UI", 10, "bold"),
            relief="flat", bd=0, cursor="hand2",
            highlightbackground=Theme.FIELD_BORDER, highlightthickness=1
        )
        cancel_btn.pack(side="left", expand=True, fill="x", padx=(0, 6), ipady=9)

        save_btn = tk.Button(
            btn_row, text="Save", command=self._save,
            bg=Theme.ACCENT, fg="white", font=("Segoe UI", 10, "bold"),
            relief="flat", bd=0, cursor="hand2", activebackground=Theme.ACCENT_HOVER,
            activeforeground="white"
        )
        save_btn.pack(side="left", expand=True, fill="x", padx=(6, 0), ipady=9)

        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"+{x}+{y}")

        self.entry.focus_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.wait_window(self)

    def _save(self):
        self.result = self.entry.get().strip()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class MainWindow:
    CONNECT_CARD_COLLAPSED_H = 250
    CONNECT_CARD_EXPANDED_H = 322

    def __init__(self, root, token, user_data):
        self.root = root
        self.token = token
        self.user_data = user_data
        self.pin_visible = False

        self.root.title("SkyDesk - Dashboard")
        self.root.configure(bg=Theme.BG)
        self.root.state("zoomed")

        container = tk.Frame(self.root, bg=Theme.BG)
        container.pack(expand=True, fill="both")

        content = tk.Frame(container, bg=Theme.BG)
        content.place(relx=0.5, rely=0.5, anchor="center", width=540)

        # ---- Big greeting header (centered) ----
        header = tk.Frame(content, bg=Theme.BG)
        header.pack(pady=(0, 26), fill="x")

        brand_row = tk.Frame(header, bg=Theme.BG)
        brand_row.pack()
        logo_canvas = tk.Canvas(brand_row, width=30, height=30, bg=Theme.BG, highlightthickness=0)
        logo_canvas.pack(side="left", padx=(0, 8))
        round_rect(logo_canvas, 1, 1, 29, 29, radius=9, fill=Theme.ACCENT, outline="")
        logo_canvas.create_text(15, 15, text="S", font=("Segoe UI", 13, "bold"), fill="white")
        tk.Label(brand_row, text="SkyDesk", font=("Segoe UI", 11, "bold"),
                 bg=Theme.BG, fg=Theme.TEXT_MUTED).pack(side="left")

        tk.Label(
            header, text=f"Hello, {user_data['username']}!", font=("Segoe UI", 28, "bold"),
            bg=Theme.BG, fg=Theme.TEXT_PRIMARY
        ).pack(pady=(8, 0))
        tk.Label(
            header, text="Welcome back to your SkyDesk dashboard", font=("Segoe UI", 11),
            bg=Theme.BG, fg=Theme.TEXT_MUTED
        ).pack()

        # ---- Remote ID hero card ----
        id_card = RoundedCard(content, width=540, height=150, radius=18)
        id_card.pack(pady=(0, 16))
        ic = id_card.content

        tk.Label(ic, text="YOUR REMOTE ID", font=("Segoe UI", 8, "bold"),
                 bg=Theme.CARD_BG, fg=Theme.TEXT_MUTED).pack(pady=(20, 6))

        id_badge = tk.Frame(ic, bg=Theme.ACCENT_SOFT)
        id_badge.pack()
        id_row = tk.Frame(id_badge, bg=Theme.ACCENT_SOFT)
        id_row.pack(padx=22, pady=10)
        tk.Label(id_row, text=user_data["remote_id"], font=("Consolas", 22, "bold"),
                 bg=Theme.ACCENT_SOFT, fg=Theme.ACCENT).pack(side="left")
        self.copy_btn = tk.Label(
            id_row, text="  Copy", font=("Segoe UI", 9, "bold"), bg=Theme.ACCENT_SOFT,
            fg=Theme.ACCENT_HOVER, cursor="hand2"
        )
        self.copy_btn.pack(side="left", padx=(10, 0), pady=(3, 0))
        self.copy_btn.bind("<Button-1>", lambda e: self._copy_remote_id())

        self.status_pill = tk.Label(
            ic, text="  \u25CF  Connecting...  ", font=("Segoe UI", 9, "bold"),
            bg=Theme.CONNECTING_BG, fg=Theme.CONNECTING, padx=4, pady=3
        )
        self.status_pill.pack(pady=(14, 0))

        # ---- Connect card (dynamic height) ----
        self.connect_card = RoundedCard(content, width=540, height=self.CONNECT_CARD_COLLAPSED_H, radius=18)
        self.connect_card.pack(pady=(0, 16))
        cc = self.connect_card.content

        tk.Label(cc, text="Connect to a remote computer", font=("Segoe UI", 12, "bold"),
                 bg=Theme.CARD_BG, fg=Theme.TEXT_PRIMARY).pack(pady=(22, 16), padx=28, anchor="w")

        self.remote_id_entry = self._add_input_row(cc, placeholder="SKY-XXXXXX")

        self.pin_toggle = tk.Label(
            cc, text="+ Use an access PIN", font=("Segoe UI", 9), bg=Theme.CARD_BG,
            fg=Theme.ACCENT, cursor="hand2"
        )
        self.pin_toggle.pack(padx=28, pady=(4, 0), anchor="w")
        self.pin_toggle.bind("<Button-1>", lambda e: self._toggle_pin_field())

        self.pin_wrap = tk.Frame(cc, bg=Theme.CARD_BG)
        self.pin_entry = self._add_input_row(self.pin_wrap, show="\u2022", label="Access PIN")

        self.connect_btn = tk.Button(
            cc, text="Connect", command=self.connect_request,
            bg=Theme.ACCENT, fg="white", font=("Segoe UI", 11, "bold"),
            relief="flat", bd=0, cursor="hand2", activebackground=Theme.ACCENT_HOVER,
            activeforeground="white"
        )
        self.connect_btn.pack(fill="x", padx=28, pady=(16, 20), ipady=11)
        self.connect_btn.bind("<Enter>", lambda e: self.connect_btn.config(bg=Theme.ACCENT_HOVER))
        self.connect_btn.bind("<Leave>", lambda e: self.connect_btn.config(bg=Theme.ACCENT))

        # ---- Actions row ----
        actions = tk.Frame(content, bg=Theme.BG)
        actions.pack(fill="x")

        pin_action = self._pill_button(actions, "\u2699  Access PIN", self.open_pin_dialog,
                                        fg=Theme.TEXT_PRIMARY, border=Theme.FIELD_BORDER, hover=Theme.FIELD_BG)
        pin_action.pack(side="left", expand=True, fill="x", padx=(0, 6), ipady=10)

        self.logout_btn = tk.Button(
            actions, text="\u2192  Logout", command=self.logout,
            bg=Theme.DANGER, fg="white", font=("Segoe UI", 10, "bold"),
            relief="flat", bd=0, cursor="hand2", activebackground="#c11842",
            activeforeground="white"
        )
        self.logout_btn.pack(side="left", expand=True, fill="x", padx=(6, 0), ipady=10)
        self.logout_btn.bind("<Enter>", lambda e: self.logout_btn.config(bg="#c11842"))
        self.logout_btn.bind("<Leave>", lambda e: self.logout_btn.config(bg=Theme.DANGER))

        self.ws_client = WSClient(self.token, self.handle_ws_message)
        self.ws_client.set_status_callback(self.update_connection_status)
        self.ws_client.connect()

    # ---------------------------------------------------------------
    # UI helpers
    # ---------------------------------------------------------------
    def _add_input_row(self, parent, placeholder=None, show=None, label=None):
        if label:
            tk.Label(parent, text=label, font=("Segoe UI", 8, "bold"), bg=Theme.CARD_BG,
                      fg=Theme.TEXT_MUTED).pack(padx=28, pady=(2, 4), anchor="w")
        wrap = tk.Frame(parent, bg=Theme.FIELD_BG, highlightthickness=1,
                         highlightbackground=Theme.FIELD_BORDER, highlightcolor=Theme.FIELD_FOCUS)
        wrap.pack(padx=28, fill="x")
        entry = tk.Entry(
            wrap, font=("Consolas", 12), relief="flat", bg=Theme.FIELD_BG,
            fg=Theme.TEXT_PRIMARY, insertbackground=Theme.TEXT_PRIMARY, bd=0, highlightthickness=0
        )
        if show:
            entry.config(show=show)
        entry.pack(fill="x", padx=12, ipady=9)
        entry.bind("<FocusIn>", lambda e: wrap.config(highlightbackground=Theme.FIELD_FOCUS))
        entry.bind("<FocusOut>", lambda e: wrap.config(highlightbackground=Theme.FIELD_BORDER))
        if placeholder:
            entry.insert(0, placeholder)
        return entry

    def _toggle_pin_field(self):
        self.pin_visible = not self.pin_visible
        if self.pin_visible:
            self.pin_wrap.pack(fill="x", pady=(10, 0), before=self.connect_btn)
            self.pin_toggle.config(text="\u2212 Hide access PIN")
            self.connect_card.resize(self.CONNECT_CARD_EXPANDED_H)
        else:
            self.pin_wrap.pack_forget()
            self.pin_toggle.config(text="+ Use an access PIN")
            self.connect_card.resize(self.CONNECT_CARD_COLLAPSED_H)

    def _pill_button(self, parent, text, command, fg, border, hover):
        btn = tk.Button(
            parent, text=text, command=command,
            bg=Theme.BG, fg=fg, font=("Segoe UI", 10, "bold"),
            relief="flat", bd=0, cursor="hand2",
            highlightbackground=border, highlightthickness=1,
            activebackground=hover, activeforeground=fg
        )
        btn.bind("<Enter>", lambda e: btn.config(bg=hover))
        btn.bind("<Leave>", lambda e: btn.config(bg=Theme.BG))
        return btn

    def _copy_remote_id(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.user_data["remote_id"])
        self.copy_btn.config(text="  Copied!", fg=Theme.ONLINE)
        self.root.after(1500, lambda: self.copy_btn.config(text="  Copy", fg=Theme.ACCENT_HOVER))

    # ---------------------------------------------------------------
    # Connection status
    # ---------------------------------------------------------------
    def update_connection_status(self, connected):
        if connected:
            self.status_pill.config(text="  \u25CF  Online  ", bg=Theme.ONLINE_BG, fg=Theme.ONLINE)
        else:
            self.status_pill.config(text="  \u25CF  Disconnected  ", bg=Theme.OFFLINE_BG, fg=Theme.OFFLINE)

    def connect_request(self):
        target_id = self.remote_id_entry.get().strip()
        if not target_id or target_id == "SKY-XXXXXX":
            messagebox.showwarning("Missing Remote ID", "Please enter a valid Remote ID.")
            return

        pin = self.pin_entry.get().strip() or None
        self.ws_client.send_connect_request(target_id, pin=pin)
        messagebox.showinfo("Request Sent", f"Connection request sent to {target_id}.")

    def open_pin_dialog(self):
        dialog = PinDialog(self.root)
        pin = dialog.result
        if pin is None:
            return  # Cancelled
        if pin and not pin.isdigit():
            messagebox.showerror("Invalid PIN", "The PIN must contain numbers only.")
            return
        self.ws_client.send_set_pin(pin)

    # ---------------------------------------------------------------
    # WebSocket message handling
    # ---------------------------------------------------------------
    def handle_ws_message(self, data):
        log(f"WS message received: {data.get('type')}")
        self.root.after(0, self._process_message_safe, data)

    def _process_message_safe(self, data):
        try:
            self._process_message(data)
        except Exception as e:
            import traceback
            log(f"ERROR in _process_message: {e}")
            log(traceback.format_exc())
            try:
                messagebox.showerror("SkyDesk Error", f"Something went wrong: {e}")
            except Exception:
                pass

    def _process_message(self, data):
        msg_type = data.get("type")

        if msg_type == "id_connect_request":
            from_id = data.get("from_remote_id")
            from_username = data.get("from_username")
            answer = messagebox.askyesno(
                "Connection Request",
                f"{from_username} ({from_id}) wants to connect. Accept?",
            )
            if answer:
                self.ws_client.send_accept(from_id)
            else:
                self.ws_client.send_reject(from_id)

        elif msg_type == "id_connect_accept":
            session_id = data.get("session_id")
            messagebox.showinfo(
                "Request Accepted",
                f"{data.get('from_remote_id')} accepted your request. Connecting to the screen...",
            )
            log(f"id_connect_accept received, session_id={session_id} - starting ScreenViewer")
            from screen_view import ScreenViewer

            viewer = ScreenViewer(
                session_id=session_id,
                my_username=self.user_data["username"]
            )
            viewer.start()

        elif msg_type == "id_connect_reject":
            messagebox.showinfo(
                "Request Declined", f"{data.get('from_remote_id')} declined your connection request."
            )
        elif msg_type == "session_start":
            session_id = data.get("session_id")
            log(f"session_start received, session_id={session_id} - starting ScreenSharer")
            from screen_share import ScreenSharer

            sharer = ScreenSharer(
                main_root=self.root, session_id=session_id,
                username=self.user_data["username"]
            )
            sharer.start()
            log("ScreenSharer.start() returned successfully")
            messagebox.showinfo("Sharing Started", "Your screen is now being shared.")

        elif msg_type == "pin_set_ok":
            if data.get("cleared"):
                messagebox.showinfo("PIN Removed", "Your access PIN has been removed.")
            else:
                messagebox.showinfo("PIN Saved", "Your access PIN has been saved.")

        elif msg_type == "pin_set_error":
            messagebox.showerror("PIN Error", data.get("message", "Failed to save the PIN."))

        elif msg_type == "error":
            messagebox.showerror("Error", data.get("message", "An unknown error occurred."))

    def logout(self):
        confirm = messagebox.askyesno("Logout", "Are you sure you want to log out?")
        if not confirm:
            return
        self.ws_client.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    dummy_user = {"username": "admin", "remote_id": "SKY-669561", "is_online": True}
    app = MainWindow(root, "dummy_token", dummy_user)
    root.mainloop()