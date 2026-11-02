import json
import time
from collections import defaultdict

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from .models import (
    Block,
    Message,
    PrivateChat,
    PrivateChatMessage,
    PrivateRoom,
    PrivateRoomMember,
    PrivateRoomMessage,
    PublicRoomMember,
    Room,
)
from .validators import validate_message_body


class RateLimiter:
    def __init__(self, max_events=10, window_seconds=10.0):
        self.max_events = max_events
        self.window = window_seconds
        self._hits = defaultdict(list)

    def allow(self, key):
        now = time.monotonic()
        self._hits[key] = [t for t in self._hits[key] if now - t < self.window]
        if len(self._hits[key]) >= self.max_events:
            return False
        self._hits[key].append(now)
        return True


rate_limiter = RateLimiter(max_events=10, window_seconds=10.0)

MAX_CONNECTIONS_PER_USER = 5
_active_connections = defaultdict(int)


def _ts(dt):
    return timezone.localtime(dt).strftime("%H:%M")


class BaseChatConsumer(AsyncWebsocketConsumer):
    group_prefix = None
    allow_connect = None

    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4001)
            return

        if _active_connections[user.pk] >= MAX_CONNECTIONS_PER_USER:
            await self.close(code=4029)
            return

        if not await self.allow_connect(user):
            await self.close(code=4003)
            return

        self.group_name = f"{self.group_prefix}_{self.identity}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        _active_connections[user.pk] += 1
        self._registered = True
        await self.accept()

    async def disconnect(self, close_code):
        if getattr(self, "_registered", False):
            user = self.scope["user"]
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name
            )
            if _active_connections[user.pk] > 0:
                _active_connections[user.pk] -= 1

    async def receive(self, text_data):
        user = self.scope["user"]
        if not user.is_authenticated:
            return

        if not rate_limiter.allow(f"user:{user.pk}"):
            await self.send_json({"error": "Rate limit exceeded. Slow down."})
            return

        try:
            data = json.loads(text_data)
        except (json.JSONDecodeError, TypeError):
            await self.send_json({"error": "Malformed frame."})
            return

        if not isinstance(data, dict):
            await self.send_json({"error": "Malformed frame."})
            return

        body, err = validate_message_body(data.get("message"))
        if err:
            await self.send_json({"error": err})
            return

        saved, save_err = await self.persist(user, body)
        if save_err:
            await self.send_json({"error": save_err})
            return

        await self.channel_layer.group_send(
            self.group_name,
            {"type": "broadcast", **saved},
        )

    async def broadcast(self, event):
        await self.send_json({
            "username": event["username"],
            "message": event["message"],
            "timestamp": event["timestamp"],
        })

    async def send_json(self, payload):
        await self.send(text_data=json.dumps(payload))


class ChatConsumer(BaseChatConsumer):
    group_prefix = "chat"

    async def connect(self):
        self.identity = self.scope["url_route"]["kwargs"]["room_name"]
        await super().connect()

    @database_sync_to_async
    def allow_connect(self, user):
        return Room.objects.filter(name=self.identity).exists()

    @database_sync_to_async
    def persist(self, user, body):
        try:
            room = Room.objects.get(name=self.identity)
        except Room.DoesNotExist:
            return None, "Room no longer exists."
        msg = Message.objects.create(room=room, sender=user, content=body)
        return {
            "username": user.username,
            "message": msg.content,
            "timestamp": _ts(msg.created),
        }, None


class PrivateChatConsumer(BaseChatConsumer):
    group_prefix = "private"

    async def connect(self):
        self.identity = self.scope["url_route"]["kwargs"]["chat_id"]
        await super().connect()

    @database_sync_to_async
    def allow_connect(self, user):
        chat = PrivateChat.objects.filter(pk=self.identity).first()
        if not chat:
            return False
        return user.pk in (chat.user1_id, chat.user2_id)

    @database_sync_to_async
    def persist(self, user, body):
        try:
            chat = PrivateChat.objects.get(pk=self.identity)
        except PrivateChat.DoesNotExist:
            return None, "Conversation no longer exists."
        if user.pk not in (chat.user1_id, chat.user2_id):
            return None, "You are not part of this conversation."
        other_id = chat.user2_id if chat.user1_id == user.pk else chat.user1_id
        if Block.objects.filter(blocker_id=user.pk, blocked_id=other_id).exists():
            return None, "You have blocked this user."
        if Block.objects.filter(blocker_id=other_id, blocked_id=user.pk).exists():
            return None, "You cannot message this user."
        msg = PrivateChatMessage.objects.create(
            chat=chat, sender=user, content=body
        )
        return {
            "username": user.username,
            "message": msg.content,
            "timestamp": _ts(msg.created),
        }, None


class PrivateRoomConsumer(BaseChatConsumer):
    group_prefix = "privateroom"

    async def connect(self):
        self.identity = self.scope["url_route"]["kwargs"]["room_name"]
        await super().connect()

    @database_sync_to_async
    def allow_connect(self, user):
        return PrivateRoomMember.objects.filter(
            room__name=self.identity, user=user
        ).exists()

    @database_sync_to_async
    def persist(self, user, body):
        try:
            room = PrivateRoom.objects.get(name=self.identity)
        except PrivateRoom.DoesNotExist:
            return None, "Room no longer exists."
        if not PrivateRoomMember.objects.filter(room=room, user=user).exists():
            return None, "You are no longer a member of this room."
        msg = PrivateRoomMessage.objects.create(
            room=room, sender=user, content=body
        )
        return {
            "username": user.username,
            "message": msg.content,
            "timestamp": _ts(msg.created),
        }, None
