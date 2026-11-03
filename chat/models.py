import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone
from django_cryptography.fields import encrypt


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
    user1_hidden = models.BooleanField(default=False)
    user2_hidden = models.BooleanField(default=False)
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

    def is_hidden_for(self, user):
        if self.user1_id == user.pk:
            return self.user1_hidden
        if self.user2_id == user.pk:
            return self.user2_hidden
        return False

    def unhide_for(self, user):
        if self.user1_id == user.pk and self.user1_hidden:
            self.user1_hidden = False
            self.save(update_fields=["user1_hidden"])
        elif self.user2_id == user.pk and self.user2_hidden:
            self.user2_hidden = False
            self.save(update_fields=["user2_hidden"])

    def hide_for(self, user):
        if self.user1_id == user.pk:
            self.user1_hidden = True
            self.save(update_fields=["user1_hidden"])
        elif self.user2_id == user.pk:
            self.user2_hidden = True
            self.save(update_fields=["user2_hidden"])

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


class ReadMarker(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="read_markers",
    )
    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    private_room = models.ForeignKey(
        PrivateRoom,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    private_chat = models.ForeignKey(
        PrivateChat,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    last_read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "room"),
                name="unique_read_public_room",
                condition=models.Q(room__isnull=False),
            ),
            models.UniqueConstraint(
                fields=("user", "private_room"),
                name="unique_read_private_room",
                condition=models.Q(private_room__isnull=False),
            ),
            models.UniqueConstraint(
                fields=("user", "private_chat"),
                name="unique_read_private_chat",
                condition=models.Q(private_chat__isnull=False),
            ),
        ]


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
    content = encrypt(models.TextField(max_length=4000))
    created = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)

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
    content = encrypt(models.TextField(max_length=4000))
    created = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)

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
    content = encrypt(models.TextField(max_length=4000))
    created = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created"]
        indexes = [models.Index(fields=["room", "-created"])]

    def __str__(self):
        return f"{self.sender} @ #{self.room}"


class Reaction(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reactions",
    )
    value = models.SmallIntegerField()
    room_message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reactions",
    )
    private_room_message = models.ForeignKey(
        PrivateRoomMessage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reactions",
    )
    private_chat_message = models.ForeignKey(
        PrivateChatMessage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reactions",
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(value__in=[1, -1]),
                name="reaction_value_valid",
            ),
            models.UniqueConstraint(
                fields=("user", "room_message"),
                name="unique_reaction_room_msg",
                condition=models.Q(room_message__isnull=False),
            ),
            models.UniqueConstraint(
                fields=("user", "private_room_message"),
                name="unique_reaction_private_room_msg",
                condition=models.Q(private_room_message__isnull=False),
            ),
            models.UniqueConstraint(
                fields=("user", "private_chat_message"),
                name="unique_reaction_private_chat_msg",
                condition=models.Q(private_chat_message__isnull=False),
            ),
        ]

    def __str__(self):
        return f"{self.user} {'+' if self.value == 1 else '-'} on reaction {self.id}"
