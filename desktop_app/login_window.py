import tkinter as tk
from tkinter import messagebox
import requests
from config import LOGIN_URL, ME_URL
from main_window import MainWindow
from session_store import (
    get_remember_me, save_remember_me,
    get_session, save_session, clear_session,
    get_recent_users,
)


def center_window(win, width, height):
    win.update_idletasks()
    screen_width = win.winfo_screenwidth()
    screen_height = win.winfo_screenheight()
    x = (screen_width - width) // 2
    y = (screen_height - height) // 2
    win.geometry(f"{width}x{height}+{x}+{y}")


def round_rect(canvas, x1, y1, x2, y2, radius=18, **kwargs):
    """Draw a rounded rectangle on a canvas."""
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
    BG = "#eef1f8"
    CARD_BG = "#ffffff"
    ACCENT = "#2196F3"
    ACCENT_DARK = "#1565C0"
    ACCENT_HOVER = "#1E88E5"
    FIELD_BG = "#f4f6fa"
    FIELD_BORDER = "#e2e6ee"
    FIELD_FOCUS = "#2196F3"
    TEXT_MUTED = "#8b93a3"
    TEXT_LABEL = "#4a5061"
    ERROR = "#e53935"
    SUCCESS = "#2e7d32"
    SHADOW = "#dde1ec"


class LoginWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("SkyDesk - Sign In")
        self.root.configure(bg=Theme.BG)
        self.root.state("zoomed")

        self.pw_visible = False

        # Try auto-login with a saved session token first.
        if self._try_auto_login():
            return

        self.recent_users = get_recent_users()

        outer = tk.Frame(self.root, bg=Theme.BG)
        outer.place(relx=0.5, rely=0.5, anchor="center")

        card_w, card_h = 400, 520

        if self.recent_users:
            self.recent_panel = self._build_recent_panel(outer, card_h)
            self.recent_panel.pack(side="left", padx=(0, 18), anchor="n")

        self.canvas = tk.Canvas(
            outer, width=card_w + 16, height=card_h + 16,
            bg=Theme.BG, highlightthickness=0
        )
        self.canvas.pack(side="left")

        round_rect(self.canvas, 10, 12, card_w + 10, card_h + 12, radius=22, fill=Theme.SHADOW, outline="")
        round_rect(self.canvas, 4, 4, card_w + 4, card_h + 4, radius=22, fill=Theme.CARD_BG, outline=Theme.FIELD_BORDER)

        card = tk.Frame(self.canvas, bg=Theme.CARD_BG)
        self.canvas.create_window((card_w + 8) / 2, (card_h + 8) / 2, window=card, width=card_w - 20, height=card_h - 20)

        tk.Label(card, text="SkyDesk", font=("Segoe UI", 25, "bold"), bg=Theme.CARD_BG, fg=Theme.ACCENT_DARK).pack(pady=(30, 4))
        tk.Label(card, text="Sign in to continue", font=("Segoe UI", 10), bg=Theme.CARD_BG, fg=Theme.TEXT_MUTED).pack(pady=(0, 20))

        self.username_entry = self._add_field(card, "Username")
        self.password_entry, self.pw_toggle_btn = self._add_password_field(card, "Password")

        self.remember_var = tk.BooleanVar(value=False)
        remember_row = tk.Frame(card, bg=Theme.CARD_BG)
        remember_row.pack(fill="x", padx=40, pady=(0, 4))
        tk.Checkbutton(
            remember_row, text="Remember me", variable=self.remember_var,
            bg=Theme.CARD_BG, fg=Theme.TEXT_LABEL, font=("Segoe UI", 9),
            activebackground=Theme.CARD_BG, selectcolor=Theme.CARD_BG,
            cursor="hand2"
        ).pack(anchor="w")

        self.status_label = tk.Label(card, text="", fg=Theme.ERROR, bg=Theme.CARD_BG, font=("Segoe UI", 9), wraplength=320, justify="center")
        self.status_label.pack(pady=(6, 4))

        self.login_btn = tk.Button(
            card, text="Sign In", command=self.login,
            bg=Theme.ACCENT, fg="white", font=("Segoe UI", 11, "bold"),
            relief="flat", activebackground=Theme.ACCENT_DARK, activeforeground="white",
            cursor="hand2", bd=0
        )
        self.login_btn.pack(fill="x", padx=40, pady=(10, 14), ipady=11)
        self.login_btn.bind("<Enter>", lambda e: self.login_btn.config(bg=Theme.ACCENT_HOVER))
        self.login_btn.bind("<Leave>", lambda e: self.login_btn.config(bg=Theme.ACCENT))

        tk.Button(
            card, text="Don't have an account? Create one", command=self.open_register,
            bg=Theme.CARD_BG, fg=Theme.ACCENT, font=("Segoe UI", 9, "underline"),
            relief="flat", bd=0, cursor="hand2"
        ).pack()

        # Prefill remembered credentials
        saved_username, saved_password = get_remember_me()
        if saved_username:
            self.username_entry.insert(0, saved_username)
            self.remember_var.set(True)
        if saved_password:
            self.password_entry.insert(0, saved_password)

        if saved_username:
            self.password_entry.focus_set()
        else:
            self.username_entry.focus_set()
        self.password_entry.bind("<Return>", lambda e: self.login())

    # ---------------------------------------------------------------
    # Auto-login using a saved session token
    # ---------------------------------------------------------------
    def _try_auto_login(self):
        token, user = get_session()
        if not token or not user:
            return False
        try:
            resp = requests.get(
                ME_URL, headers={"Authorization": f"Token {token}"}, timeout=8
            )
            if resp.status_code == 200:
                self.root.destroy()
                self.open_main_window(token, user)
                return True
        except requests.exceptions.RequestException:
            pass
        clear_session()
        return False

    # ---------------------------------------------------------------
    # Recent users side panel (AnyDesk-style)
    # ---------------------------------------------------------------
    def _build_recent_panel(self, parent, card_h):
        panel = tk.Frame(
            parent, bg=Theme.CARD_BG, width=200, height=card_h + 16,
            highlightthickness=1, highlightbackground=Theme.FIELD_BORDER
        )
        panel.pack_propagate(False)

        tk.Label(
            panel, text="Recent Users", font=("Segoe UI", 10, "bold"),
            bg=Theme.CARD_BG, fg=Theme.TEXT_LABEL
        ).pack(anchor="w", padx=16, pady=(18, 8))

        for user in self.recent_users:
            username = user.get("username", "")
            row = tk.Frame(panel, bg=Theme.CARD_BG, cursor="hand2")
            row.pack(fill="x", padx=10, pady=3)

            avatar = tk.Canvas(row, width=32, height=32, bg=Theme.CARD_BG, highlightthickness=0)
            avatar.pack(side="left", padx=(4, 8), pady=6)
            round_rect(avatar, 0, 0, 32, 32, radius=16, fill=Theme.ACCENT, outline="")
            initial = username[:1].upper() if username else "?"
            avatar.create_text(16, 16, text=initial, font=("Segoe UI", 11, "bold"), fill="white")

            text_col = tk.Frame(row, bg=Theme.CARD_BG)
            text_col.pack(side="left", fill="x", expand=True, pady=6)
            tk.Label(
                text_col, text=username, font=("Segoe UI", 9, "bold"),
                bg=Theme.CARD_BG, fg=Theme.TEXT_LABEL, anchor="w"
            ).pack(fill="x")
            if user.get("remote_id"):
                tk.Label(
                    text_col, text=user["remote_id"], font=("Segoe UI", 8),
                    bg=Theme.CARD_BG, fg=Theme.TEXT_MUTED, anchor="w"
                ).pack(fill="x")

            click_targets = [row, avatar, text_col] + text_col.winfo_children()
            for widget in click_targets:
                widget.bind("<Button-1>", lambda e, u=username: self._select_recent_user(u))

            row.bind("<Enter>", lambda e, r=row: r.config(bg=Theme.FIELD_BG))
            row.bind("<Leave>", lambda e, r=row: r.config(bg=Theme.CARD_BG))

        return panel

    def _select_recent_user(self, username):
        self.username_entry.delete(0, tk.END)
        self.username_entry.insert(0, username)
        self.password_entry.focus_set()

    # ---------------------------------------------------------------
    # Field builders (unchanged)
    # ---------------------------------------------------------------
    def _add_field(self, parent, label_text):
        tk.Label(parent, text=label_text, font=("Segoe UI", 9), bg=Theme.CARD_BG, fg=Theme.TEXT_LABEL, anchor="w").pack(fill="x", padx=40)
        wrap = tk.Frame(parent, bg=Theme.FIELD_BG, highlightthickness=1, highlightbackground=Theme.FIELD_BORDER, highlightcolor=Theme.FIELD_FOCUS)
        wrap.pack(fill="x", padx=40, pady=(3, 14))
        entry = tk.Entry(wrap, font=("Segoe UI", 11), relief="flat", bg=Theme.FIELD_BG, bd=0, highlightthickness=0)
        entry.pack(fill="x", padx=10, ipady=7)
        entry.bind("<FocusIn>", lambda e: wrap.config(highlightbackground=Theme.FIELD_FOCUS))
        entry.bind("<FocusOut>", lambda e: wrap.config(highlightbackground=Theme.FIELD_BORDER))
        return entry

    def _add_password_field(self, parent, label_text):
        tk.Label(parent, text=label_text, font=("Segoe UI", 9), bg=Theme.CARD_BG, fg=Theme.TEXT_LABEL, anchor="w").pack(fill="x", padx=40)
        wrap = tk.Frame(parent, bg=Theme.FIELD_BG, highlightthickness=1, highlightbackground=Theme.FIELD_BORDER, highlightcolor=Theme.FIELD_FOCUS)
        wrap.pack(fill="x", padx=40, pady=(3, 14))
        entry = tk.Entry(wrap, font=("Segoe UI", 11), relief="flat", bg=Theme.FIELD_BG, bd=0, highlightthickness=0, show="*")
        entry.pack(side="left", fill="x", expand=True, padx=(10, 0), ipady=7)
        toggle_btn = tk.Label(wrap, text="Show", font=("Segoe UI", 8, "bold"), bg=Theme.FIELD_BG, fg=Theme.ACCENT, cursor="hand2")
        toggle_btn.pack(side="right", padx=10)
        toggle_btn.bind("<Button-1>", lambda e: self._toggle_password(entry, toggle_btn))
        entry.bind("<FocusIn>", lambda e: wrap.config(highlightbackground=Theme.FIELD_FOCUS))
        entry.bind("<FocusOut>", lambda e: wrap.config(highlightbackground=Theme.FIELD_BORDER))
        return entry, toggle_btn

    def _toggle_password(self, entry, toggle_btn):
        self.pw_visible = not self.pw_visible
        entry.config(show="" if self.pw_visible else "*")
        toggle_btn.config(text="Hide" if self.pw_visible else "Show")

    def _set_status(self, text, is_error=True):
        self.status_label.config(text=text, fg=Theme.ERROR if is_error else Theme.SUCCESS)

    def login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get()

        if not username or not password:
            self._set_status("Username and password are required.")
            return

        self.login_btn.config(state="disabled", text="Signing in...")
        self._set_status("Signing in...", is_error=False)
        self.root.update_idletasks()

        try:
            response = requests.post(
                LOGIN_URL,
                json={"username": username, "password": password},
                timeout=15
            )
        except requests.exceptions.Timeout:
            self._set_status("No response from the server (timeout). Please check your internet connection.")
            self._reset_button()
            return
        except requests.exceptions.ConnectionError:
            self._set_status("Could not connect to the server. Please check your internet connection.")
            self._reset_button()
            return
        except requests.exceptions.RequestException as e:
            self._set_status(f"Network error: {e}")
            self._reset_button()
            return
        except Exception as e:
            self._set_status(f"Unexpected error: {e}")
            self._reset_button()
            return

        try:
            if response.status_code == 200:
                data = response.json()
                token = data["token"]
                user = data["user"]

                save_remember_me(username, password, self.remember_var.get())
                save_session(token, user)

                self.root.destroy()
                self.open_main_window(token, user)
                return
            elif response.status_code in (400, 401):
                self._set_status("Invalid username or password.")
            else:
                try:
                    errors = response.json()
                    if isinstance(errors, dict) and errors:
                        first_key = next(iter(errors))
                        first_error = errors[first_key]
                        if isinstance(first_error, list):
                            first_error = first_error[0]
                        self._set_status(f"{first_key}: {first_error}")
                    else:
                        self._set_status(f"Sign in failed (status {response.status_code}).")
                except ValueError:
                    self._set_status(f"Sign in failed (status {response.status_code}): {response.text[:150]}")
        except Exception as e:
            self._set_status(f"Unexpected error while processing the response: {e}")

        self._reset_button()

    def _reset_button(self):
        self.login_btn.config(state="normal", text="Sign In")

    def open_register(self):
        self.root.destroy()
        reg_root = tk.Tk()
        from register_window import RegisterWindow
        RegisterWindow(reg_root, self.open_main_window)
        reg_root.mainloop()

    def open_main_window(self, token, user_data):
        new_root = tk.Tk()
        MainWindow(new_root, token, user_data)
        new_root.mainloop()


if __name__ == "__main__":
    root = tk.Tk()
    app = LoginWindow(root)
    root.mainloop()