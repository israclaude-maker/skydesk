import tkinter as tk
from tkinter import messagebox
import requests
from config import LOGIN_URL
from main_window import MainWindow


def center_window(win, width, height):
    win.update_idletasks()
    screen_width = win.winfo_screenwidth()
    screen_height = win.winfo_screenheight()
    x = (screen_width - width) // 2
    y = (screen_height - height) // 2
    win.geometry(f"{width}x{height}+{x}+{y}")


class LoginWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("SkyDesk - Login")
        self.root.configure(bg="#eef1f8")
        self.root.state("zoomed")

        card = tk.Frame(self.root, bg="white", highlightbackground="#dfe3ec", highlightthickness=1)
        card.place(relx=0.5, rely=0.5, anchor="center", width=360, height=480)

        tk.Label(card, text="SkyDesk", font=("Segoe UI", 24, "bold"), bg="white", fg="#1976D2").pack(pady=(40, 4))
        tk.Label(card, text="Sign in to continue", font=("Segoe UI", 10), bg="white", fg="#888").pack(pady=(0, 26))

        self.username_entry = self._add_field(card, "Username")
        self.password_entry = self._add_field(card, "Password", show="*")

        tk.Button(
            card, text="Login", command=self.login,
            bg="#2196F3", fg="white", font=("Segoe UI", 11, "bold"),
            relief="flat", activebackground="#1976D2", activeforeground="white",
            cursor="hand2"
        ).pack(fill="x", padx=40, pady=(22, 10), ipady=8)

        tk.Button(
            card, text="Create Account", command=self.open_register,
            bg="white", fg="#2196F3", font=("Segoe UI", 9, "underline"),
            relief="flat", bd=0, cursor="hand2"
        ).pack()

        self.status_label = tk.Label(card, text="", fg="#e53935", bg="white", font=("Segoe UI", 9), wraplength=300)
        self.status_label.pack(pady=(14, 0))

    def _add_field(self, parent, label_text, show=None):
        tk.Label(parent, text=label_text, font=("Segoe UI", 9), bg="white", fg="#555", anchor="w").pack(fill="x", padx=40)
        entry = tk.Entry(
            parent, font=("Segoe UI", 11), relief="flat", bg="#f2f4f8",
            highlightthickness=1, highlightbackground="#ddd", highlightcolor="#2196F3"
        )
        if show:
            entry.config(show=show)
        entry.pack(fill="x", padx=40, pady=(3, 12), ipady=6)
        return entry

    def login(self):
        username = self.username_entry.get()
        password = self.password_entry.get()

        if not username or not password:
            self.status_label.config(text="Username/Password required")
            return

        try:
            response = requests.post(LOGIN_URL, json={
                "username": username,
                "password": password
            })

            if response.status_code == 200:
                data = response.json()
                token = data["token"]
                user = data["user"]
                self.root.destroy()  # Login window band karo
                self.open_main_window(token, user)
            else:
                self.status_label.config(text="Invalid username or password")

        except requests.exceptions.ConnectionError:
            self.status_label.config(text="Server se connect nahi ho paya!")

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