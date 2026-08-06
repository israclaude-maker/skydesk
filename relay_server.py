"""
SkyDesk Relay Server
=====================
Yeh VPS par ek ALAG standalone service ke roop mein chalti hai (Django se
bilkul separate). Kaam simple hai: dono taraf (sharer + viewer) isi VPS ko
OUTBOUND connect karte hain (session_id + channel batate hain), aur yeh
dono connections ko "pair" karke unke beech raw bytes relay kar deti hai.

Isse kisi bhi user ko apne router mein port-forwarding karne ki zaroorat
NAHI padti - dono taraf sirf bahar (VPS) ki taraf connect kar rahe hain,
jo har normal ghar/office ka router allow karta hai.

Run: python3 relay_server.py
Systemd service se background mein hamesha chalao (neeche instructions).
"""
import socket
import threading
import json
import logging

HOST = "0.0.0.0"
PORT = 9010

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("relay")

# Jo connection abhi apne partner ka wait kar raha hai: (session_id, channel) -> socket
waiting = {}
lock = threading.Lock()


def pipe(src, dst, label):
    """Ek direction mein bytes forward karta hai - jab tak connection zinda hai."""
    try:
        while True:
            data = src.recv(4096)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle_client(conn, addr):
    try:
        conn.settimeout(20)
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(1024)
            if not chunk:
                conn.close()
                return
            buf += chunk
        line, _rest = buf.split(b"\n", 1)
        handshake = json.loads(line.decode())
        session_id = handshake.get("session_id")
        channel = handshake.get("channel")  # "screen" ya "control"
        role = handshake.get("role", "?")

        if not session_id or not channel:
            log.warning(f"Bad handshake from {addr}: {handshake}")
            conn.close()
            return

        conn.settimeout(None)
        key = (session_id, channel)

        partner = None
        with lock:
            if key in waiting:
                partner = waiting.pop(key)
            else:
                waiting[key] = conn

        if partner is None:
            log.info(f"{role} ({addr}) waiting for partner: session={session_id} channel={channel}")
            return  # is thread ka kaam khatam - conn dict mein park hai

        log.info(f"Paired session={session_id} channel={channel} - relaying started")

        t1 = threading.Thread(target=pipe, args=(conn, partner, "a->b"), daemon=True)
        t2 = threading.Thread(target=pipe, args=(partner, conn, "b->a"), daemon=True)
        t1.start()
        t2.start()

    except Exception as e:
        log.error(f"Error handling client {addr}: {e}")
        try:
            conn.close()
        except OSError:
            pass


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(100)
    log.info(f"SkyDesk relay server listening on {HOST}:{PORT}")

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
