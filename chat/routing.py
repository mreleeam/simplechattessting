from django.urls import path

from . import consumers


websocket_urlpatterns = [
    path("ws/presence/", consumers.PresenceConsumer.as_asgi()),
    path("ws/events/", consumers.RoomEventConsumer.as_asgi()),
    path("ws/chat/r/<str:slug>/", consumers.ChatConsumer.as_asgi()),
    path("ws/chat/u/<int:chat_id>/", consumers.PrivateChatConsumer.as_asgi()),
    path("ws/chat/pr/<str:slug>/", consumers.PrivateRoomConsumer.as_asgi()),
]
