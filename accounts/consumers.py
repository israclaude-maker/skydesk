import json
import time
import uuid
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Q
from .models import ConnectionLog

User = get_user_model()

# In-memory tracking - single Daphne process assume karte hain
# (waiting dict wale relay_server pattern jaisa hi).
ONLINE_IPS = {}          # remote_id -> real client IP
FAILED_PIN_ATTEMPTS = {} # remote_id (target) -> [timestamp, timestamp, ...]

PIN_MAX_ATTEMPTS = 5
PIN_LOCKOUT_SECONDS = 60


class PresenceConsumer(AsyncWebsocketConsumer):
    def _get_real_client_ip(self):
        headers = dict(self.scope.get("headers", []))
        forwarded = headers.get(b"x-forwarded-for")
        if forwarded:
            return forwarded.decode().split(",")[0].strip()
        client = self.scope.get("client")
        return client[0] if client else None

    async def connect(self):
        self.user = self.scope["user"]

        if self.user.is_anonymous:
            await self.close()
            return

        self.group_name = f"user_{self.user.remote_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)

        ONLINE_IPS[self.user.remote_id] = self._get_real_client_ip()

        await self.set_online_status(True)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "user") and not self.user.is_anonymous:
            await self.set_online_status(False)
            await self.close_all_open_logs_for_user(self.user)
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            ONLINE_IPS.pop(self.user.remote_id, None)

    async def receive(self, text_data):
        data = json.loads(text_data)
        message_type = data.get("type")

        if message_type == "id_connect_request":
            await self.handle_connect_request(data)
        elif message_type == "id_connect_accept":
            await self.handle_connect_response(data, accepted=True)
        elif message_type == "id_connect_reject":
            await self.handle_connect_response(data, accepted=False)
        elif message_type == "set_access_pin":
            await self.handle_set_pin(data)
        elif message_type == "check_online_status":
            await self.handle_check_online_status(data)
        elif message_type == "session_ended":
            await self.handle_session_ended(data)

    # ---------- PIN set/change (apna khud ka PIN, apne liye) ----------
    async def handle_set_pin(self, data):
        raw_pin = (data.get("pin") or "").strip()

        if raw_pin and (not raw_pin.isdigit() or len(raw_pin) < 4):
            await self.send(text_data=json.dumps({
                "type": "pin_set_error",
                "message": "PIN kam se kam 4 digits ka hona chahiye (numbers only)."
            }))
            return

        await self.save_pin(raw_pin)
        await self.send(text_data=json.dumps({
            "type": "pin_set_ok",
            "cleared": raw_pin == "",
        }))

    # ---------- Connect request ----------
    def _pin_locked_out(self, target_remote_id):
        attempts = FAILED_PIN_ATTEMPTS.get(target_remote_id, [])
        now = time.time()
        attempts = [t for t in attempts if now - t < PIN_LOCKOUT_SECONDS]
        FAILED_PIN_ATTEMPTS[target_remote_id] = attempts
        return len(attempts) >= PIN_MAX_ATTEMPTS

    def _record_failed_pin(self, target_remote_id):
        FAILED_PIN_ATTEMPTS.setdefault(target_remote_id, []).append(time.time())

    async def handle_connect_request(self, data):
        target_remote_id = data.get("target_remote_id")
        submitted_pin = data.get("pin")

        target_user = await self.get_user_by_remote_id(target_remote_id)
        if target_user is None:
            await self.send(text_data=json.dumps(
                {"type": "error", "message": "Remote ID not found"}
            ))
            return

        # Agar PIN diya gaya hai aur match hota hai -> auto-accept (koi popup nahi)
        if submitted_pin and not self._pin_locked_out(target_remote_id):
            pin_ok = await self.verify_pin(target_user, submitted_pin)
            if pin_ok:
                await self.auto_accept(target_user)
                return
            else:
                self._record_failed_pin(target_remote_id)
                # Ghalat PIN pe koi specific error nahi dete (enumeration se bachne
                # ke liye) - bas normal manual request flow pe chale jate hain.

        # Normal flow: target ke paas popup jayega jaisa pehle hota tha
        await self.channel_layer.group_send(
            f"user_{target_remote_id}",
            {
                "type": "forward_message",
                "message": {
                    "type": "id_connect_request",
                    "from_remote_id": self.user.remote_id,
                    "from_username": self.user.username,
                },
            },
        )

    async def auto_accept(self, target_user):
        target_remote_id = target_user.remote_id
        session_id = str(uuid.uuid4())[:8]
        sharer_ip = ONLINE_IPS.get(target_remote_id)

        # Target (jiska screen share hoga) ko seedha session_start bhejo -
        # koi Accept/Reject popup nahi dikhega.
        await self.channel_layer.group_send(
            f"user_{target_remote_id}",
            {
                "type": "forward_message",
                "message": {
                    "type": "session_start",
                    "session_id": session_id,
                    "role": "sharer",
                },
            },
        )

        await self.create_connection_log(session_id, self.user, target_user, "pin")

        # Requester ko batao connection ready hai
        await self.send(text_data=json.dumps({
            "type": "id_connect_accept",
            "from_remote_id": target_remote_id,
            "from_username": target_user.username,
            "session_id": session_id,
            "role": "viewer",
            "host": sharer_ip,
            "local_host": None,
        }))

    async def handle_connect_response(self, data, accepted):
        requester_remote_id = data.get("requester_remote_id")

        session_id = None
        sharer_ip = None
        local_ip = None
        if accepted:
            session_id = str(uuid.uuid4())[:8]
            sharer_ip = self._get_real_client_ip()
            local_ip = data.get("local_ip")
            requester_user = await self.get_user_by_remote_id(requester_remote_id)
            await self.create_connection_log(session_id, requester_user, self.user, "manual")

        await self.channel_layer.group_send(
            f"user_{requester_remote_id}",
            {
                "type": "forward_message",
                "message": {
                    "type": "id_connect_accept" if accepted else "id_connect_reject",
                    "from_remote_id": self.user.remote_id,
                    "from_username": self.user.username if accepted else None,
                    "session_id": session_id,
                    "role": "viewer",
                    "host": sharer_ip,
                    "local_host": local_ip,
                },
            },
        )

        if accepted:
            await self.send(text_data=json.dumps({
                "type": "session_start",
                "session_id": session_id,
                "role": "sharer",
            }))

    async def forward_message(self, event):
        await self.send(text_data=json.dumps(event["message"]))

    async def handle_check_online_status(self, data):
        remote_ids = data.get("remote_ids") or []
        statuses = await self.get_online_statuses(remote_ids)
        await self.send(text_data=json.dumps({
            "type": "online_status_result",
            "statuses": statuses,
        }))

    @database_sync_to_async
    def get_online_statuses(self, remote_ids):
        users = User.objects.filter(remote_id__in=remote_ids).values("remote_id", "is_online")
        return {u["remote_id"]: u["is_online"] for u in users}

    @database_sync_to_async
    def set_online_status(self, status):
        self.user.is_online = status
        self.user.save()

    @database_sync_to_async
    def get_user_by_remote_id(self, remote_id):
        return User.objects.filter(remote_id=remote_id).first()

    @database_sync_to_async
    def verify_pin(self, user, raw_pin):
        return user.check_access_pin(raw_pin)

    @database_sync_to_async
    def save_pin(self, raw_pin):
        if raw_pin:
            self.user.set_access_pin(raw_pin)
        else:
            self.user.clear_access_pin()
        self.user.save()

    # ---------- Connection logging ----------
    async def handle_session_ended(self, data):
        session_id = data.get("session_id")
        if session_id:
            await self.close_connection_log(session_id)

    @database_sync_to_async
    def create_connection_log(self, session_id, requester_user, target_user, connect_via):
        ConnectionLog.objects.create(
            session_id=session_id,
            requester=requester_user,
            target=target_user,
            connect_via=connect_via,
            status="ongoing",
        )

    @database_sync_to_async
    def close_connection_log(self, session_id):
        log = ConnectionLog.objects.filter(session_id=session_id, status="ongoing").first()
        if log:
            log.ended_at = timezone.now()
            log.duration_seconds = int((log.ended_at - log.started_at).total_seconds())
            log.status = "ended"
            log.save()

    @database_sync_to_async
    def close_all_open_logs_for_user(self, user):
        now = timezone.now()
        logs = ConnectionLog.objects.filter(status="ongoing").filter(
            Q(requester=user) | Q(target=user)
        )
        for log in logs:
            log.ended_at = now
            log.duration_seconds = int((log.ended_at - log.started_at).total_seconds())
            log.status = "ended"
            log.save()