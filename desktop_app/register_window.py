import tkinter as tk
from tkinter import messagebox
import requests
from config import REGISTER_URL


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


class RegisterWindow:
    def __init__(self, root, on_success):
        self.root = root
        self.on_success = on_success

        self.root.title("SkyDesk - Create Account")
        self.root.configure(bg=Theme.BG)
        self.root.state("zoomed")

        self.pw_visible = False
        self.confirm_visible = False

        outer = tk.Frame(self.root, bg=Theme.BG)
        outer.place(relx=0.5, rely=0.5, anchor="center")

        card_w, card_h = 420, 640
        self.canvas = tk.Canvas(
            outer, width=card_w + 16, height=card_h + 16,
            bg=Theme.BG, highlightthickness=0
        )
        self.canvas.pack()

        round_rect(self.canvas, 10, 12, card_w + 10, card_h + 12, radius=22, fill=Theme.SHADOW, outline="")
        round_rect(self.canvas, 4, 4, card_w + 4, card_h + 4, radius=22, fill=Theme.CARD_BG, outline=Theme.FIELD_BORDER)

        card = tk.Frame(self.canvas, bg=Theme.CARD_BG)
        self.canvas.create_window((card_w + 8) / 2, (card_h + 8) / 2, window=card, width=card_w - 20, height=card_h - 20)

        tk.Label(card, text="Create Account", font=("Segoe UI", 21, "bold"), bg=Theme.CARD_BG, fg=Theme.ACCENT_DARK).pack(pady=(36, 4))
        tk.Label(card, text="Join SkyDesk in seconds", font=("Segoe UI", 10), bg=Theme.CARD_BG, fg=Theme.TEXT_MUTED).pack(pady=(0, 26))

        self.username_entry = self._add_field(card, "Username")
        self.email_entry = self._add_field(card, "Email")
        self.password_entry, self.pw_toggle_btn = self._add_password_field(card, "Password", is_confirm=False)
        self.confirm_entry, self.confirm_toggle_btn = self._add_password_field(card, "Confirm Password", is_confirm=True)

        self.status_label = tk.Label(card, text="", fg=Theme.ERROR, bg=Theme.CARD_BG, font=("Segoe UI", 9), wraplength=340, justify="center")
        self.status_label.pack(pady=(4, 6))

        self.create_btn = tk.Button(
            card, text="Create Account", command=self.register,
            bg=Theme.ACCENT, fg="white", font=("Segoe UI", 11, "bold"),
            relief="flat", activebackground=Theme.ACCENT_DARK, activeforeground="white",
            cursor="hand2", bd=0
        )
        self.create_btn.pack(fill="x", padx=36, pady=(8, 14), ipady=11)
        self.create_btn.bind("<Enter>", lambda e: self.create_btn.config(bg=Theme.ACCENT_HOVER))
        self.create_btn.bind("<Leave>", lambda e: self.create_btn.config(bg=Theme.ACCENT))

        tk.Button(
            card, text="Already have an account? Sign In", command=self.back_to_login,
            bg=Theme.CARD_BG, fg=Theme.ACCENT, font=("Segoe UI", 9, "underline"),
            relief="flat", bd=0, cursor="hand2"
        ).pack()

    def _add_field(self, parent, label_text):
        tk.Label(parent, text=label_text, font=("Segoe UI", 9), bg=Theme.CARD_BG, fg=Theme.TEXT_LABEL, anchor="w").pack(fill="x", padx=36)
        wrap = tk.Frame(parent, bg=Theme.FIELD_BG, highlightthickness=1, highlightbackground=Theme.FIELD_BORDER, highlightcolor=Theme.FIELD_FOCUS)
        wrap.pack(fill="x", padx=36, pady=(3, 12))
        entry = tk.Entry(wrap, font=("Segoe UI", 11), relief="flat", bg=Theme.FIELD_BG, bd=0, highlightthickness=0)
        entry.pack(fill="x", padx=10, ipady=7)
        entry.bind("<FocusIn>", lambda e: wrap.config(highlightbackground=Theme.FIELD_FOCUS))
        entry.bind("<FocusOut>", lambda e: wrap.config(highlightbackground=Theme.FIELD_BORDER))
        return entry

    def _add_password_field(self, parent, label_text, is_confirm):
        tk.Label(parent, text=label_text, font=("Segoe UI", 9), bg=Theme.CARD_BG, fg=Theme.TEXT_LABEL, anchor="w").pack(fill="x", padx=36)
        wrap = tk.Frame(parent, bg=Theme.FIELD_BG, highlightthickness=1, highlightbackground=Theme.FIELD_BORDER, highlightcolor=Theme.FIELD_FOCUS)
        wrap.pack(fill="x", padx=36, pady=(3, 12))
        entry = tk.Entry(wrap, font=("Segoe UI", 11), relief="flat", bg=Theme.FIELD_BG, bd=0, highlightthickness=0, show="*")
        entry.pack(side="left", fill="x", expand=True, padx=(10, 0), ipady=7)
        toggle_btn = tk.Label(wrap, text="Show", font=("Segoe UI", 8, "bold"), bg=Theme.FIELD_BG, fg=Theme.ACCENT, cursor="hand2")
        toggle_btn.pack(side="right", padx=10)
        toggle_btn.bind("<Button-1>", lambda e: self._toggle_password(entry, toggle_btn, is_confirm))
        entry.bind("<FocusIn>", lambda e: wrap.config(highlightbackground=Theme.FIELD_FOCUS))
        entry.bind("<FocusOut>", lambda e: wrap.config(highlightbackground=Theme.FIELD_BORDER))
        return entry, toggle_btn

    def _toggle_password(self, entry, toggle_btn, is_confirm):
        if is_confirm:
            self.confirm_visible = not self.confirm_visible
            visible = self.confirm_visible
        else:
            self.pw_visible = not self.pw_visible
            visible = self.pw_visible
        entry.config(show="" if visible else "*")
        toggle_btn.config(text="Hide" if visible else "Show")

    def _set_status(self, text, is_error=True):
        self.status_label.config(text=text, fg=Theme.ERROR if is_error else Theme.SUCCESS)

    def register(self):
        username = self.username_entry.get().strip()
        email = self.email_entry.get().strip()
        password = self.password_entry.get()
        confirm = self.confirm_entry.get()

        if not username:
            self._set_status("Username is required.")
            return
        if not password:
            self._set_status("Password is required.")
            return
        if password != confirm:
            self._set_status("Passwords do not match.")
            return

        self.create_btn.config(state="disabled", text="Please wait...")
        self._set_status("Creating your account...", is_error=False)
        self.root.update_idletasks()

        try:
            response = requests.post(
                REGISTER_URL,
                json={"username": username, "email": email, "password": password},
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
            if response.status_code == 201:
                data = response.json()
                messagebox.showinfo("Success", "Your account has been created! Signing you in...")
                self.root.destroy()
                self.on_success(data["token"], data["user"])
                return
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
                        self._set_status(f"Registration failed (status {response.status_code}).")
                except ValueError:
                    self._set_status(f"Registration failed (status {response.status_code}): {response.text[:150]}")
        except Exception as e:
            self._set_status(f"Unexpected error while processing the response: {e}")

        self._reset_button()

    def _reset_button(self):
        self.create_btn.config(state="normal", text="Create Account")

    def back_to_login(self):
        self.root.destroy()
        from login_window import LoginWindow
        new_root = tk.Tk()
        LoginWindow(new_root)
        new_root.mainloop()


if __name__ == "__main__":
    root = tk.Tk()
    RegisterWindow(root, lambda token, user: print("Success:", token, user))
    root.mainloop()