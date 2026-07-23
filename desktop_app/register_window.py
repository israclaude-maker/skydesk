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


class RegisterWindow:
    def __init__(self, root, on_success):
        self.root = root
        self.on_success = on_success

        self.root.title("SkyDesk - Create Account")
        self.root.configure(bg="#eef1f8")
        self.root.resizable(False, False)
        center_window(self.root, 420, 580)

        card = tk.Frame(self.root, bg="white", highlightbackground="#dfe3ec", highlightthickness=1)
        card.place(relx=0.5, rely=0.5, anchor="center", width=360, height=520)

        tk.Label(card, text="Create Account", font=("Segoe UI", 18, "bold"), bg="white", fg="#1976D2").pack(pady=(34, 4))
        tk.Label(card, text="Join SkyDesk in seconds", font=("Segoe UI", 10), bg="white", fg="#888").pack(pady=(0, 22))

        self.username_entry = self._add_field(card, "Username")
        self.email_entry = self._add_field(card, "Email")
        self.password_entry = self._add_field(card, "Password", show="*")
        self.confirm_entry = self._add_field(card, "Confirm Password", show="*")

        tk.Button(
            card, text="Create Account", command=self.register,
            bg="#2196F3", fg="white", font=("Segoe UI", 11, "bold"),
            relief="flat", activebackground="#1976D2", activeforeground="white",
            cursor="hand2"
        ).pack(fill="x", padx=40, pady=(18, 10), ipady=8)

        tk.Button(
            card, text="Already have an account? Login", command=self.back_to_login,
            bg="white", fg="#2196F3", font=("Segoe UI", 9, "underline"),
            relief="flat", bd=0, cursor="hand2"
        ).pack()

        self.status_label = tk.Label(card, text="", fg="#e53935", bg="white", font=("Segoe UI", 9), wraplength=300)
        self.status_label.pack(pady=(12, 0))

    def _add_field(self, parent, label_text, show=None):
        tk.Label(parent, text=label_text, font=("Segoe UI", 9), bg="white", fg="#555", anchor="w").pack(fill="x", padx=40)
        entry = tk.Entry(
            parent, font=("Segoe UI", 11), relief="flat", bg="#f2f4f8",
            highlightthickness=1, highlightbackground="#ddd", highlightcolor="#2196F3"
        )
        if show:
            entry.config(show=show)
        entry.pack(fill="x", padx=40, pady=(3, 10), ipady=6)
        return entry

    def register(self):
        username = self.username_entry.get().strip()
        email = self.email_entry.get().strip()
        password = self.password_entry.get()
        confirm = self.confirm_entry.get()

        if not username or not password:
            self.status_label.config(text="Username/Password required")
            return
        if password != confirm:
            self.status_label.config(text="Passwords match nahi ho rahe")
            return

        try:
            response = requests.post(REGISTER_URL, json={
                "username": username,
                "email": email,
                "password": password
            })
            if response.status_code == 201:
                data = response.json()
                messagebox.showinfo("Success", "Account ban gaya! Ab login ho rahe hain...")
                self.root.destroy()
                self.on_success(data["token"], data["user"])
            else:
                try:
                    errors = response.json()
                    first_error = next(iter(errors.values()))
                    if isinstance(first_error, list):
                        first_error = first_error[0]
                    self.status_label.config(text=str(first_error))
                except Exception:
                    self.status_label.config(text="Registration failed")
        except requests.exceptions.ConnectionError:
            self.status_label.config(text="Server se connect nahi ho paya!")

    def back_to_login(self):
        self.root.destroy()
        from login_window import LoginWindow
        new_root = tk.Tk()
        LoginWindow(new_root)
        new_root.mainloop()