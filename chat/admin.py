from django.contrib import admin

from .models import (
    Block,
    Message,
    PrivateChat,
    PrivateChatMessage,
    PrivateRoom,
    PrivateRoomBan,
    PrivateRoomMember,
    PrivateRoomMessage,
    PublicRoomMember,
    Reaction,
    Room,
)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created")
    search_fields = ("name", "slug")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("sender", "room", "created")
    list_filter = ("room",)


@admin.register(PrivateRoom)
class PrivateRoomAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "is_locked", "created")
    list_filter = ("is_locked",)
    search_fields = ("name", "slug")


@admin.register(PrivateRoomMember)
class PrivateRoomMemberAdmin(admin.ModelAdmin):
    list_display = ("room", "user", "is_admin", "is_muted", "joined")
    list_filter = ("is_admin", "is_muted")


@admin.register(PrivateRoomBan)
class PrivateRoomBanAdmin(admin.ModelAdmin):
    list_display = ("room", "user", "banned_by", "created")


@admin.register(PrivateRoomMessage)
class PrivateRoomMessageAdmin(admin.ModelAdmin):
    list_display = ("room", "sender", "created")
    list_filter = ("room",)


@admin.register(PrivateChat)
class PrivateChatAdmin(admin.ModelAdmin):
    list_display = ("user1", "user2", "created")


@admin.register(PrivateChatMessage)
class PrivateChatMessageAdmin(admin.ModelAdmin):
    list_display = ("chat", "sender", "created")


@admin.register(PublicRoomMember)
class PublicRoomMemberAdmin(admin.ModelAdmin):
    list_display = ("room", "user", "joined")


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ("blocker", "blocked", "created")


@admin.register(Reaction)
class ReactionAdmin(admin.ModelAdmin):
    list_display = ("user", "value", "created")
    list_filter = ("value",)
