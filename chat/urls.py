from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.index, name="index"),
    path("r/<str:room_name>/", views.room, name="room"),
    path("r/<str:room_name>/leave/", views.leave_public_room, name="leave_public_room"),
    path("r/<str:room_name>/clear/", views.delete_public_history, name="delete_public_history"),
    path("r/<str:room_name>/older/", views.older_public_messages, name="older_public_messages"),
    path("pub/join/", views.join_or_create_public_room, name="join_or_create_public_room"),
    path("private/new/", views.create_private_chat, name="create_private_chat"),
    path("p/@<str:username>/", views.private_chat, name="private_chat"),
    path("p/@<str:username>/remove/", views.remove_private_chat, name="remove_private_chat"),
    path("p/@<str:username>/older/", views.older_private_chat_messages, name="older_private_chat_messages"),
    path("u/@<str:username>/", views.profile, name="profile"),
    path("p/@<str:username>/block/", views.block_user, name="block_user"),
    path("p/@<str:username>/unblock/", views.unblock_user, name="unblock_user"),
    path("p/@<str:username>/clear/", views.delete_private_history, name="delete_private_history"),
    path("pr/new/", views.create_private_room, name="create_private_room"),
    path("pr/<str:room_name>/", views.private_room, name="private_room"),
    path("pr/<str:room_name>/leave/", views.leave_private_room, name="leave_private_room"),
    path("pr/<str:room_name>/clear/", views.delete_private_room_history, name="delete_private_room_history"),
    path("pr/<str:room_name>/delete/", views.delete_private_room, name="delete_private_room"),
    path("pr/<str:room_name>/older/", views.older_private_room_messages, name="older_private_room_messages"),
    path("pr/<str:room_name>/rotate/", views.rotate_invite, name="rotate_invite"),
    path("join/", views.join_by_link, name="join_by_link"),
    path("join/<str:token>/", views.join_via_invite, name="join_via_invite"),
    path("msg/edit/", views.edit_message, name="edit_message"),
    path("msg/delete/", views.delete_message, name="delete_message"),
    path("msg/react/", views.react_message, name="react_message"),
    path("msg/reactions/", views.message_reactions, name="message_reactions"),
]
