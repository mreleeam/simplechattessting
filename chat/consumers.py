import json
import time
from collections import defaultdict

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from .colors import color_for
from .models import (
    Block,
    Message,
    PrivateChat,
    PrivateChatMessage,
    PrivateRoom,
    PrivateRoomMember,
    PrivateRoomMessage,
    Reaction,
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

_presence_group = "presence_global"
_online_users = defaultdict(int)


def _ts(dt):
    return timezone.localtime(dt).strftime("%H:%M")


def _full_ts(dt):
    return timezone.localtime(dt).strftime("%d %b %Y %H:%M")


def user_group(user_id):
    return f"user_events_{user_id}"


class PresenceConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4001)
            return
        self.user = user
        await self.channel_layer.group_add(_presence_group, self.channel_name)
        _online_users[user.pk] += 1
        if _online_users[user.pk] == 1:
            await self.channel_layer.group_send(
                _presence_group,
                {"type": "presence_event", "username": user.username, "online": True},
            )
        await self.accept()
        await self.send(text_data=json.dumps({
            "type": "online_list",
            "usernames": list(_online_users.keys()),
        }))

    async def disconnect(self, close_code):
        if not hasattr(self, "user"):
            return
        await self.channel_layer.group_discard(_presence_group, self.channel_name)
        _online_users[self.user.pk] -= 1
        if _online_users[self.user.pk] <= 0:
            del _online_users[self.user.pk]
            await self.channel_layer.group_send(
                _presence_group,
                {"type": "presence_event", "username": self.user.username, "online": False},
            )

    async def receive(self, text_data):
        pass

    async def presence_event(self, event):
        await self.send(text_data=json.dumps({
            "type": "presence",
            "username": event["username"],
            "online": event["online"],
        }))


class RoomEventConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4001)
            return
        self.user = user
        self.group_name = user_group(user.pk)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        pass

    async def room_event(self, event):
        await self.send(text_data=json.dumps({
            "type": event.get("event_type", "room_event"),
            "slug": event.get("slug", ""),
            "name": event.get("name", ""),
            "kind": event.get("kind", ""),
        }))


class BaseChatConsumer(AsyncWebsocketConsumer):
    group_prefix = None
    msg_kind = None
    typing_enabled = False
    reaction_field = None

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

        msg_type = data.get("type", "message")

        if msg_type == "typing":
            if self.typing_enabled:
                await self.channel_layer.group_send(
                    self.group_name,
                    {"type": "typing_broadcast", "username": user.username},
                )
            return

        if msg_type == "reaction":
            msg_id = data.get("id")
            value = data.get("value")
            if not msg_id or value not in (1, -1):
                return
            result = await self._apply_reaction(user, msg_id, value)
            if result:
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "reaction_broadcast",
                        "id": msg_id,
                        "kind": self.msg_kind,
                        "up": result["up"],
                        "down": result["down"],
                    },
                )
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

    @database_sync_to_async
    def _apply_reaction(self, user, msg_id, value):
        if not self.reaction_field:
            return None
        filter_kwargs = {"user": user, self.reaction_field + "_id": msg_id}
        existing = Reaction.objects.filter(**filter_kwargs).first()
        if existing:
            if existing.value == value:
                existing.delete()
            else:
                existing.value = value
                existing.save(update_fields=["value"])
        else:
            Reaction.objects.create(
                user=user,
                value=value,
                **{self.reaction_field + "_id": msg_id},
            )
        up = Reaction.objects.filter(
            value=1, **{self.reaction_field + "_id": msg_id}
        ).count()
        down = Reaction.objects.filter(
            value=-1, **{self.reaction_field + "_id": msg_id}
        ).count()
        return {"up": up, "down": down}

    async def broadcast(self, event):
        await self.send_json({
            "type": "message",
            "id": event.get("id"),
            "kind": self.msg_kind,
            "username": event["username"],
            "message": event["message"],
            "timestamp": event["timestamp"],
            "full_timestamp": event.get("full_timestamp", ""),
            "created": event.get("created", ""),
            "user_color": event.get("user_color", "#58a6ff"),
            "up": event.get("up", 0),
            "down": event.get("down", 0),
            "mine": event.get("mine", 0),
        })

    async def typing_broadcast(self, event):
        await self.send_json({
            "type": "typing",
            "username": event["username"],
        })

    async def reaction_broadcast(self, event):
        await self.send_json({
            "type": "reaction",
            "id": event["id"],
            "kind": event["kind"],
            "up": event["up"],
            "down": event["down"],
        })

    async def send_json(self, payload):
        await self.send(text_data=json.dumps(payload))


class ChatConsumer(BaseChatConsumer):
    group_prefix = "chat"
    msg_kind = "room"
    reaction_field = "room_message"

    async def connect(self):
        self.identity = self.scope["url_route"]["kwargs"]["slug"]
        await super().connect()

    @database_sync_to_async
    def allow_connect(self, user):
        return Room.objects.filter(slug=self.identity).exists()

    @database_sync_to_async
    def persist(self, user, body):
        try:
            room = Room.objects.get(slug=self.identity)
        except Room.DoesNotExist:
            return None, "Room no longer exists."
        msg = Message.objects.create(room=room, sender=user, content=body)
        up = Reaction.objects.filter(room_message=msg, value=1).count()
        down = Reaction.objects.filter(room_message=msg, value=-1).count()
        return {
            "id": msg.id,
            "username": user.username,
            "message": msg.content,
            "timestamp": _ts(msg.created),
            "full_timestamp": _full_ts(msg.created),
            "created": msg.created.isoformat(),
            "user_color": color_for(user),
            "up": up,
            "down": down,
            "mine": 0,
        }, None


class PrivateChatConsumer(BaseChatConsumer):
    group_prefix = "private"
    msg_kind = "pc"
    typing_enabled = True
    reaction_field = "private_chat_message"

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
        recipient = chat.user2 if chat.user1_id == user.pk else chat.user1
        chat.unhide_for(recipient)
        up = Reaction.objects.filter(private_chat_message=msg, value=1).count()
        down = Reaction.objects.filter(private_chat_message=msg, value=-1).count()
        return {
            "id": msg.id,
            "username": user.username,
            "message": msg.content,
            "timestamp": _ts(msg.created),
            "full_timestamp": _full_ts(msg.created),
            "created": msg.created.isoformat(),
            "user_color": color_for(user),
            "up": up,
            "down": down,
            "mine": 0,
        }, None


class PrivateRoomConsumer(BaseChatConsumer):
    group_prefix = "privateroom"
    msg_kind = "pr"
    reaction_field = "private_room_message"

    async def connect(self):
        self.identity = self.scope["url_route"]["kwargs"]["slug"]
        await super().connect()

    @database_sync_to_async
    def allow_connect(self, user):
        return PrivateRoomMember.objects.filter(
            room__slug=self.identity, user=user
        ).exists()

    @database_sync_to_async
    def persist(self, user, body):
        try:
            room = PrivateRoom.objects.get(slug=self.identity)
        except PrivateRoom.DoesNotExist:
            return None, "Room no longer exists."

        membership = PrivateRoomMember.objects.filter(
            room=room, user=user
        ).first()
        if not membership:
            return None, "You are no longer a member of this room."

        is_owner = room.owner_id == user.pk
        is_admin = is_owner or membership.is_admin

        if membership.is_muted and not is_admin:
            return None, "You are muted in this room."

        if room.is_locked and not is_admin:
            return None, "Room is locked. Only admins can send messages."

        msg = PrivateRoomMessage.objects.create(
            room=room, sender=user, content=body
        )
        up = Reaction.objects.filter(private_room_message=msg, value=1).count()
        down = Reaction.objects.filter(private_room_message=msg, value=-1).count()
        return {
            "id": msg.id,
            "username": user.username,
            "message": msg.content,
            "timestamp": _ts(msg.created),
            "full_timestamp": _full_ts(msg.created),
            "created": msg.created.isoformat(),
            "user_color": color_for(user),
            "up": up,
            "down": down,
            "mine": 0,
        }, None
