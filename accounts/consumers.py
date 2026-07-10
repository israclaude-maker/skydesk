import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model

User = get_user_model()


class PresenceConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]

        if self.user.is_anonymous:
            await self.close()
            return

        # Personal group - taake is user ko directly messages bheje ja sakein
        self.group_name = f"user_{self.user.remote_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)

        await self.set_online_status(True)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "user") and not self.user.is_anonymous:
            await self.set_online_status(False)
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        message_type = data.get("type")

        if message_type == "id_connect_request":
            await self.handle_connect_request(data)
        elif message_type == "id_connect_accept":
            await self.handle_connect_response(data, accepted=True)
        elif message_type == "id_connect_reject":
            await self.handle_connect_response(data, accepted=False)

    async def handle_connect_request(self, data):
        target_remote_id = data.get("target_remote_id")

        target_exists = await self.check_user_exists(target_remote_id)
        if not target_exists:
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": "Remote ID not found"
            }))
            return

        # Target user ke group ko request bhejo
        await self.channel_layer.group_send(
            f"user_{target_remote_id}",
            {
                "type": "forward_message",
                "message": {
                    "type": "id_connect_request",
                    "from_remote_id": self.user.remote_id,
                    "from_username": self.user.username,
                }
            }
        )

    async def handle_connect_response(self, data, accepted):
        requester_remote_id = data.get("requester_remote_id")

        session_id = None
        if accepted:
            import uuid
            session_id = str(uuid.uuid4())[:8]

        # Requester ko batao
        await self.channel_layer.group_send(
            f"user_{requester_remote_id}",
            {
                "type": "forward_message",
                "message": {
                    "type": "id_connect_accept" if accepted else "id_connect_reject",
                    "from_remote_id": self.user.remote_id,
                    "session_id": session_id,
                    "role": "viewer"  # requester screen dekhega
                }
            }
        )

        # Accept karne wale (sharer) ko bhi bhejo
        if accepted:
            await self.send(text_data=json.dumps({
                "type": "session_start",
                "session_id": session_id,
                "role": "sharer"  # ye apni screen share karega
            }))

    async def forward_message(self, event):
        await self.send(text_data=json.dumps(event["message"]))

    @database_sync_to_async
    def set_online_status(self, status):
        self.user.is_online = status
        self.user.save()

    @database_sync_to_async
    def check_user_exists(self, remote_id):
        return User.objects.filter(remote_id=remote_id).exists()