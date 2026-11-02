from django.urls import path

from . import consumers


websocket_urlpatterns = [
    path("ws/chat/r/<str:room_name>/", consumers.ChatConsumer.as_asgi()),
    path("ws/chat/u/<int:chat_id>/", consumers.PrivateChatConsumer.as_asgi()),
    path("ws/chat/pr/<str:room_name>/", consumers.PrivateRoomConsumer.as_asgi()),
]
