import secrets

from django.conf import settings
from django.db import models


class PrivateChat(models.Model):
    user1 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="private_chats_as_user1",
    )
    user2 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="private_chats_as_user2",
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user1", "user2"),
                name="unique_private_chat_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(user1__lt=models.F("user2")),
                name="private_chat_canonical_order",
            ),
        ]

    @classmethod
    def between(cls, a, b):
        if a.pk == b.pk:
            raise ValueError("Cannot create a chat between the same user.")
        low, high = (a, b) if a.pk < b.pk else (b, a)
        obj, _ = cls.objects.get_or_create(user1=low, user2=high)
        return obj

    def other_user(self, user):
        return self.user2 if self.user1_id == user.pk else self.user1

    def __str__(self):
        return f"{self.user1} <-> {self.user2}"


def _new_token():
    return secrets.token_urlsafe(24)


class PrivateRoom(models.Model):
    name = models.CharField(max_length=64, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    invite_token = models.CharField(
        max_length=64, unique=True, default=_new_token, editable=False
    )
    created = models.DateTimeField(auto_now_add=True)

    def rotate_invite_token(self):
        self.invite_token = _new_token()
        self.save(update_fields=["invite_token"])
        return self.invite_token

    def is_member(self, user):
        return self.members.filter(user=user).exists()

    def __str__(self):
        return f"#{self.name}"


class PrivateRoomMember(models.Model):
    room = models.ForeignKey(
        PrivateRoom,
        on_delete=models.CASCADE,
        related_name="members",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    joined = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("room", "user"),
                name="unique_private_room_member",
            ),
        ]

    def __str__(self):
        return f"{self.user} in {self.room}"


class Room(models.Model):
    name = models.CharField(max_length=64, unique=True)
    is_private = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def is_member(self, user):
        return self.members.filter(user=user).exists()

    def __str__(self):
        return self.name


class PublicRoomMember(models.Model):
    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="members",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    joined = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("room", "user"),
                name="unique_public_room_member",
            ),
        ]

    def __str__(self):
        return f"{self.user} in {self.room}"


class Block(models.Model):
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocks_made",
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocks_received",
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("blocker", "blocked"),
                name="unique_block_pair",
            ),
            models.CheckConstraint(
                condition=~models.Q(blocker=models.F("blocked")),
                name="block_no_self",
            ),
        ]

    def __str__(self):
        return f"{self.blocker} blocked {self.blocked}"


class PrivateChatMessage(models.Model):
    chat = models.ForeignKey(
        PrivateChat,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    content = models.TextField(max_length=4000)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created"]
        indexes = [models.Index(fields=["chat", "-created"])]

    def __str__(self):
        return f"{self.sender} -> {self.chat}"


class Message(models.Model):
    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    content = models.TextField(max_length=4000)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created"]
        indexes = [models.Index(fields=["room", "-created"])]

    def __str__(self):
        return f"{self.sender} @ {self.room}"


class PrivateRoomMessage(models.Model):
    room = models.ForeignKey(
        PrivateRoom,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    content = models.TextField(max_length=4000)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created"]
        indexes = [models.Index(fields=["room", "-created"])]

    def __str__(self):
        return f"{self.sender} @ #{self.room}"
