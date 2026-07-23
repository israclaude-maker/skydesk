import tkinter as tk
from tkinter import messagebox
from ws_client import WSClient


class MainWindow:
    def __init__(self, root, token, user_data):
        self.root = root
        self.token = token
        self.user_data = user_data

        self.root.title("SkyDesk - Dashboard")
        self.root.geometry("400x400")
        self.root.resizable(False, False)

        # Title
        tk.Label(root, text="SkyDesk", font=("Arial", 20, "bold")).pack(pady=15)

        # Welcome message
        tk.Label(
            root, text=f"Welcome, {user_data['username']}!", font=("Arial", 12)
        ).pack(pady=5)

        # Own Remote ID display box
        id_frame = tk.Frame(root, bg="#e3f2fd", relief="groove", bd=2)
        id_frame.pack(pady=20, padx=30, fill="x")

        tk.Label(
            id_frame, text="Your Remote ID", font=("Arial", 10), bg="#e3f2fd"
        ).pack(pady=(10, 0))
        tk.Label(
            id_frame,
            text=user_data["remote_id"],
            font=("Arial", 18, "bold"),
            bg="#e3f2fd",
            fg="#1976D2",
        ).pack(pady=(0, 10))

        # Online status
        self.status_label = tk.Label(root, text="🟡 Connecting...", font=("Arial", 10))
        self.status_label.pack(pady=5)

        # Separator
        tk.Label(root, text="─" * 40, fg="gray").pack(pady=10)

        # Connect to another user section
        tk.Label(root, text="Connect to Remote ID", font=("Arial", 11, "bold")).pack(
            pady=(5, 5)
        )

        self.remote_id_entry = tk.Entry(
            root, width=20, font=("Arial", 12), justify="center"
        )
        self.remote_id_entry.pack(pady=5)
        self.remote_id_entry.insert(0, "SKY-XXXXXX")

        tk.Button(
            root,
            text="Connect",
            command=self.connect_request,
            width=20,
            bg="#4CAF50",
            fg="white",
            font=("Arial", 10, "bold"),
        ).pack(pady=15)

        # Logout button
        tk.Button(root, text="Logout", command=self.logout, width=15).pack(pady=5)

        # WebSocket connect karo
        self.ws_client = WSClient(self.token, self.handle_ws_message)
        self.ws_client.set_status_callback(self.update_connection_status)
        self.ws_client.connect()

    def update_connection_status(self, connected):
        if connected:
            self.status_label.config(text="🟢 Online", fg="green")
        else:
            self.status_label.config(text="🔴 Disconnected", fg="red")

    def connect_request(self):
        target_id = self.remote_id_entry.get().strip()
        if not target_id or target_id == "SKY-XXXXXX":
            messagebox.showwarning("Warning", "Please enter a valid Remote ID")
            return

        self.ws_client.send_connect_request(target_id)
        messagebox.showinfo("Request Sent", f"Connection request sent to {target_id}")

    def handle_ws_message(self, data):
        self.root.after(0, self._process_message, data)

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
                "Accepted",
                f"{data.get('from_remote_id')} accepted! Connecting to screen...",
            )
            from screen_view import ScreenViewer

            viewer = ScreenViewer(
                host=data.get("host", "127.0.0.1"), screen_port=9001, control_port=9002,
                my_username=self.user_data["username"]
            )
            viewer.start()

        elif msg_type == "id_connect_reject":
            messagebox.showinfo(
                "Rejected", f"{data.get('from_remote_id')} rejected your request."
            )
        elif msg_type == "session_start":
            from screen_share import ScreenSharer

            sharer = ScreenSharer(main_root=self.root, screen_port=9001, control_port=9002)
            sharer.start()
            messagebox.showinfo("Sharing Started", "Your screen is now being shared!")

        elif msg_type == "error":
            messagebox.showerror("Error", data.get("message", "Unknown error"))

    def logout(self):
        self.ws_client.close()
        messagebox.showinfo("Logout", "Logout ho gaye!")
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    dummy_user = {"username": "admin", "remote_id": "SKY-669561", "is_online": True}
    app = MainWindow(root, "dummy_token", dummy_user)
    root.mainloop()