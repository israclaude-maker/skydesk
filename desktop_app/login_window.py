import tkinter as tk
from tkinter import messagebox
import requests
from config import LOGIN_URL, REGISTER_URL
from main_window import MainWindow


class LoginWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("SkyDesk - Login")
        self.root.geometry("350x300")
        self.root.resizable(False, False)

        # Title
        tk.Label(root, text="SkyDesk", font=("Arial", 20, "bold")).pack(pady=20)

        # Username field
        tk.Label(root, text="Username").pack()
        self.username_entry = tk.Entry(root, width=30)
        self.username_entry.pack(pady=5)

        # Password field
        tk.Label(root, text="Password").pack()
        self.password_entry = tk.Entry(root, width=30, show="*")
        self.password_entry.pack(pady=5)

        # Login button
        tk.Button(root, text="Login", command=self.login, width=20, bg="#2196F3", fg="white").pack(pady=15)

        # Register button
        tk.Button(root, text="Create Account", command=self.open_register, width=20).pack()

        # Status label
        self.status_label = tk.Label(root, text="", fg="red")
        self.status_label.pack(pady=10)

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
        messagebox.showinfo("Info", "Register screen abhi banayenge")

    def open_main_window(self, token, user_data):
        new_root = tk.Tk()
        MainWindow(new_root, token, user_data)
        new_root.mainloop()


if __name__ == "__main__":
    root = tk.Tk()
    app = LoginWindow(root)
    root.mainloop()