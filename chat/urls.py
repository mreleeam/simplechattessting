from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.index, name="index"),
    path("r/<str:slug>/", views.room, name="room"),
    path("r/<str:slug>/leave/", views.leave_public_room, name="leave_public_room"),
    path("r/<str:slug>/clear/", views.delete_public_history, name="delete_public_history"),
    path("r/<str:slug>/older/", views.older_public_messages, name="older_public_messages"),
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
    path("pr/<str:slug>/", views.private_room, name="private_room"),
    path("pr/<str:slug>/leave/", views.leave_private_room, name="leave_private_room"),
    path("pr/<str:slug>/clear/", views.delete_private_room_history, name="delete_private_room_history"),
    path("pr/<str:slug>/delete/", views.delete_private_room, name="delete_private_room"),
    path("pr/<str:slug>/older/", views.older_private_room_messages, name="older_private_room_messages"),
    path("pr/<str:slug>/rotate/", views.rotate_invite, name="rotate_invite"),
    path("pr/<str:slug>/lock/", views.toggle_room_lock, name="toggle_room_lock"),
    path("pr/<str:slug>/mute/<str:username>/", views.mute_member, name="mute_member"),
    path("pr/<str:slug>/remove/<str:username>/", views.remove_member, name="remove_member"),
    path("pr/<str:slug>/unban/<str:username>/", views.unban_member, name="unban_member"),
    path("pr/<str:slug>/promote/<str:username>/", views.promote_member, name="promote_member"),
    path("pr/<str:slug>/demote/<str:username>/", views.demote_member, name="demote_member"),
    path("pr/<str:slug>/members/", views.room_members_json, name="room_members_json"),
    path("join/", views.join_by_link, name="join_by_link"),
    path("join/<str:token>/", views.join_via_invite, name="join_via_invite"),
    path("msg/edit/", views.edit_message, name="edit_message"),
    path("msg/delete/", views.delete_message, name="delete_message"),
    path("msg/react/", views.react_message, name="react_message"),
]
