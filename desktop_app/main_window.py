import tkinter as tk
from tkinter import messagebox, simpledialog
from ws_client import WSClient
from debug_log import log


class Theme:
    BG = "#eef1f8"
    CARD_BG = "#ffffff"
    ACCENT = "#2196F3"
    ACCENT_DARK = "#1565C0"
    ACCENT_HOVER = "#1E88E5"
    GREEN = "#43A047"
    GREEN_HOVER = "#388E3C"
    FIELD_BG = "#f4f6fa"
    FIELD_BORDER = "#e2e6ee"
    FIELD_FOCUS = "#2196F3"
    TEXT_MUTED = "#8b93a3"
    TEXT_LABEL = "#4a5061"
    ONLINE = "#2e7d32"
    OFFLINE = "#c62828"
    CONNECTING = "#f9a825"


class MainWindow:
    def __init__(self, root, token, user_data):
        self.root = root
        self.token = token
        self.user_data = user_data

        self.root.title("SkyDesk - Dashboard")
        self.root.configure(bg=Theme.BG)
        self.root.state("zoomed")

        # ---- Scrollable-ish centered container ----
        container = tk.Frame(self.root, bg=Theme.BG)
        container.pack(expand=True, fill="both")

        content = tk.Frame(container, bg=Theme.BG)
        content.place(relx=0.5, rely=0.5, anchor="center", width=520)

        # ---- Header ----
        tk.Label(
            content, text="SkyDesk", font=("Segoe UI", 26, "bold"),
            bg=Theme.BG, fg=Theme.ACCENT_DARK
        ).pack(pady=(0, 2))
        tk.Label(
            content, text=f"Welcome back, {user_data['username']}",
            font=("Segoe UI", 11), bg=Theme.BG, fg=Theme.TEXT_MUTED
        ).pack(pady=(0, 18))

        # ---- Remote ID card ----
        id_card = tk.Frame(content, bg=Theme.CARD_BG, highlightbackground=Theme.FIELD_BORDER, highlightthickness=1)
        id_card.pack(fill="x", pady=(0, 14))

        tk.Label(
            id_card, text="YOUR REMOTE ID", font=("Segoe UI", 9, "bold"),
            bg=Theme.CARD_BG, fg=Theme.TEXT_MUTED
        ).pack(pady=(18, 2))
        tk.Label(
            id_card, text=user_data["remote_id"], font=("Segoe UI", 22, "bold"),
            bg=Theme.CARD_BG, fg=Theme.ACCENT_DARK
        ).pack(pady=(0, 10))

        self.status_label = tk.Label(
            id_card, text="\u25CF Connecting...", font=("Segoe UI", 9, "bold"),
            bg=Theme.CARD_BG, fg=Theme.CONNECTING
        )
        self.status_label.pack(pady=(0, 16))

        # ---- Connect to remote ID card ----
        connect_card = tk.Frame(content, bg=Theme.CARD_BG, highlightbackground=Theme.FIELD_BORDER, highlightthickness=1)
        connect_card.pack(fill="x", pady=(0, 14))

        tk.Label(
            connect_card, text="Connect to a Remote ID", font=("Segoe UI", 12, "bold"),
            bg=Theme.CARD_BG, fg=Theme.TEXT_LABEL
        ).pack(pady=(20, 12))

        self.remote_id_entry = self._add_centered_field(connect_card, placeholder="SKY-XXXXXX")

        tk.Label(
            connect_card, text="Access PIN (optional - for unattended access)",
            font=("Segoe UI", 9), bg=Theme.CARD_BG, fg=Theme.TEXT_MUTED
        ).pack(pady=(4, 0))
        self.pin_entry = self._add_centered_field(connect_card, show="\u2022")

        self.connect_btn = tk.Button(
            connect_card, text="Connect", command=self.connect_request,
            bg=Theme.GREEN, fg="white", font=("Segoe UI", 11, "bold"),
            relief="flat", bd=0, cursor="hand2", activebackground=Theme.GREEN_HOVER,
            activeforeground="white"
        )
        self.connect_btn.pack(fill="x", padx=40, pady=(16, 20), ipady=10)
        self.connect_btn.bind("<Enter>", lambda e: self.connect_btn.config(bg=Theme.GREEN_HOVER))
        self.connect_btn.bind("<Leave>", lambda e: self.connect_btn.config(bg=Theme.GREEN))

        # ---- Actions ----
        actions = tk.Frame(content, bg=Theme.BG)
        actions.pack(fill="x", pady=(4, 0))

        self._secondary_button(actions, "Set / Change My Access PIN", self.open_pin_dialog).pack(fill="x", pady=(0, 8))
        self._secondary_button(actions, "Logout", self.logout, danger=True).pack(fill="x")

        self.ws_client = WSClient(self.token, self.handle_ws_message)
        self.ws_client.set_status_callback(self.update_connection_status)
        self.ws_client.connect()

    # ---------------------------------------------------------------
    # UI helpers
    # ---------------------------------------------------------------
    def _add_centered_field(self, parent, placeholder=None, show=None):
        wrap = tk.Frame(parent, bg=Theme.FIELD_BG, highlightthickness=1, highlightbackground=Theme.FIELD_BORDER, highlightcolor=Theme.FIELD_FOCUS)
        wrap.pack(padx=40, pady=6, fill="x")
        entry = tk.Entry(
            wrap, font=("Segoe UI", 12), justify="center", relief="flat",
            bg=Theme.FIELD_BG, bd=0, highlightthickness=0
        )
        if show:
            entry.config(show=show)
        entry.pack(fill="x", ipady=8)
        entry.bind("<FocusIn>", lambda e: wrap.config(highlightbackground=Theme.FIELD_FOCUS))
        entry.bind("<FocusOut>", lambda e: wrap.config(highlightbackground=Theme.FIELD_BORDER))
        if placeholder:
            entry.insert(0, placeholder)
        return entry

    def _secondary_button(self, parent, text, command, danger=False):
        fg = "#c62828" if danger else Theme.ACCENT_DARK
        btn = tk.Button(
            parent, text=text, command=command,
            bg=Theme.CARD_BG, fg=fg, font=("Segoe UI", 10, "bold"),
            relief="flat", bd=0, cursor="hand2",
            highlightbackground=Theme.FIELD_BORDER, highlightthickness=1
        )
        btn.pack_configure(ipady=9)
        return btn

    # ---------------------------------------------------------------
    # Connection status
    # ---------------------------------------------------------------
    def update_connection_status(self, connected):
        if connected:
            self.status_label.config(text="\u25CF Online", fg=Theme.ONLINE)
        else:
            self.status_label.config(text="\u25CF Disconnected", fg=Theme.OFFLINE)

    def connect_request(self):
        target_id = self.remote_id_entry.get().strip()
        if not target_id or target_id == "SKY-XXXXXX":
            messagebox.showwarning("Missing Remote ID", "Please enter a valid Remote ID.")
            return

        pin = self.pin_entry.get().strip() or None
        self.ws_client.send_connect_request(target_id, pin=pin)
        messagebox.showinfo("Request Sent", f"Connection request sent to {target_id}.")

    def open_pin_dialog(self):
        pin = simpledialog.askstring(
            "Set Access PIN",
            "Enter a new PIN (4+ digits, numbers only).\n"
            "Leave blank and click OK to remove the PIN:",
            show="\u2022",
        )
        if pin is None:
            return  # Cancelled
        pin = pin.strip()
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