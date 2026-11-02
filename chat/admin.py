from django.contrib import admin

from .models import (
    Room,
    Message,
    PrivateChat,
    PrivateRoom,
    PrivateChatMessage,
    PrivateRoomMessage,
)

admin.site.register(PrivateChat)
admin.site.register(PrivateRoom)
admin.site.register(PrivateChatMessage)
admin.site.register(PrivateRoomMessage)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "is_private", "created")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("sender", "room", "created")
    list_filter = ("room",)
