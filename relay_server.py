"""
SkyDesk Relay Server - WebSocket Version
==========================================
Purani relay raw TCP socket pe thi (port 8443/8444 wagera) - jo bohot se
restrictive networks (jo sirf real HTTPS traffic allow karte hain) block
kar dete the.

Ab ye relay sirf LOCALHOST (127.0.0.1:8765) pe chalti hai - kisi ko bhi
seedha internet se yahan connect nahi karna. Nginx already-configured
HTTPS (port 443, skydesk.skyfinancia.com) ke through /relay/ path pe
isko proxy karta hai. Isliye client ki taraf se ye traffic bilkul normal
website HTTPS traffic jaisa dikhta hai, aur har network isko pass hone
deta hai - jo bhi network already skydesk.skyfinancia.com khol sakta hai
(matlab browser use kar sakta hai), wo isay bhi allow karega.

Run: python3 relay_server.py
Systemd service (skydesk-relay) se background mein hamesha chalao.

VPS pe pehli dafa chalane se pehle: pip3 install websockets
"""
import asyncio
import json
import logging
import websockets

HOST = "127.0.0.1"
PORT = 8765

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("relay")


class Waiter:
    """Ek connection jo abhi apne partner ka wait kar raha hai."""

    def __init__(self, ws):
        self.ws = ws
        self.partner = None
        self.event = asyncio.Event()


# (session_id, channel) -> Waiter
waiting = {}
lock = asyncio.Lock()


# Websockets jo currently kisi pipe mein active hain - taake koi connection
# galti se do dafa pair na ho jaye (race condition guard).
active_conns = set()


async def pipe(src, dst):
    """Ek direction mein messages forward karta hai - jab tak connection zinda hai."""
    try:
        async for message in src:
            await dst.send(message)
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        log.error(f"Pipe error: {e}")


async def handle_client(ws):
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=20)
        handshake = json.loads(raw)
        session_id = handshake.get("session_id")
        channel = handshake.get("channel")  # "screen" ya "control"
        role = handshake.get("role", "?")

        if not session_id or not channel:
            log.warning(f"Bad handshake: {handshake}")
            await ws.close()
            return

        key = (session_id, channel)

        partner = None
        my_waiter = None
        async with lock:
            existing = waiting.get(key)
            if existing is not None and existing.ws.close_code is None:
                # Partner already waiting - claim it and wake it up
                partner = existing.ws
                del waiting[key]
                existing.partner = ws
                existing.event.set()
            else:
                my_waiter = Waiter(ws)
                waiting[key] = my_waiter

        if partner is None:
            log.info(f"{role} waiting for partner: session={session_id} channel={channel}")
            closed_task = asyncio.ensure_future(ws.wait_closed())
            event_task = asyncio.ensure_future(my_waiter.event.wait())
            done, pending = await asyncio.wait(
                {closed_task, event_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            async with lock:
                if waiting.get(key) is my_waiter:
                    del waiting[key]
            if my_waiter.partner is None:
                return  # connection closed before a partner showed up
            partner = my_waiter.partner

        # Safety guard: agar ye connection (ya iska partner) kisi wajah se
        # PEHLE se kisi aur pipe mein active hai, tou dobara relay start
        # mat karo - warna dono taraf recv() do dafa call ho jayega aur
        # crash ho jayega (jo pehle ho raha tha).
        async with lock:
            if ws in active_conns or partner in active_conns:
                log.warning(f"Duplicate pairing detected for session={session_id} channel={channel} - closing extra connection")
                await ws.close()
                return
            active_conns.add(ws)
            active_conns.add(partner)

        log.info(f"Paired session={session_id} channel={channel} - relaying started")
        try:
            await asyncio.gather(
                pipe(ws, partner),
                pipe(partner, ws),
                return_exceptions=True,
            )
        finally:
            async with lock:
                active_conns.discard(ws)
                active_conns.discard(partner)

    except asyncio.TimeoutError:
        log.warning("Handshake timeout - closing connection")
        try:
            await ws.close()
        except Exception:
            pass
    except Exception as e:
        log.error(f"Error handling client: {e}")


async def main():
    log.info(f"SkyDesk relay (WebSocket) listening on {HOST}:{PORT}")
    async with websockets.serve(
        handle_client,
        HOST,
        PORT,
        max_size=None,       # screen frames can be larger than default 1MB limit
        ping_interval=None,  # let nginx/TCP handle keepalive; avoids issues with
                              # the sharer's screen channel which never calls recv()
    ):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())