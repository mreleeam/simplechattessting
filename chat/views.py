from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import (
    Block,
    PrivateChat,
    PrivateChatMessage,
    PrivateRoom,
    PrivateRoomMember,
    PrivateRoomMessage,
    Message,
    PublicRoomMember,
    Room,
)
from .validators import normalize_username, validate_room_name

User = get_user_model()

MESSAGE_PAGE_SIZE = 200


@login_required
def index(request):
    my_public_rooms = Room.objects.filter(members__user=request.user).distinct()
    private_chats = (
        PrivateChat.objects.filter(Q(user1=request.user) | Q(user2=request.user))
        .select_related("user1", "user2")
        .distinct()
    )
    private_rooms = (
        PrivateRoom.objects.filter(members__user=request.user)
        .distinct()
        .order_by("name")
    )
    blocked_ids = Block.objects.filter(blocker=request.user).values_list(
        "blocked_id", flat=True
    )
    return render(
        request,
        "chat/index.html",
        {
            "my_public_rooms": my_public_rooms,
            "private_chats": private_chats,
            "private_rooms": private_rooms,
            "blocked_ids": set(blocked_ids),
        },
    )


@login_required
def room(request, room_name):
    room = get_object_or_404(Room, name=room_name)
    PublicRoomMember.objects.get_or_create(room=room, user=request.user)
    chat_messages = (
        room.messages.select_related("sender")
        .exclude(
            sender__in=Block.objects.filter(blocker=request.user).values("blocked")
        )
        .order_by("-created")[:MESSAGE_PAGE_SIZE][::-1]
    )
    return render(
        request,
        "chat/room.html",
        {"room": room, "chat_messages": chat_messages},
    )


@login_required
@require_POST
def leave_public_room(request, room_name):
    room = get_object_or_404(Room, name=room_name)
    PublicRoomMember.objects.filter(room=room, user=request.user).delete()
    messages.success(request, f"Left #{room.name}.")
    return redirect("chat:index")


@login_required
@require_POST
def join_or_create_public_room(request):
    raw = request.POST.get("room_name", "")
    name, err = validate_room_name(raw)
    if err:
        messages.error(request, err)
        return redirect("chat:index")

    room, created = Room.objects.get_or_create(name=name)
    PublicRoomMember.objects.get_or_create(room=room, user=request.user)
    if created:
        messages.success(request, f"Public room #{name} created.")
    else:
        messages.success(request, f"Joined #{name}.")
    return redirect("chat:room", room_name=room.name)


@login_required
@require_POST
def delete_public_history(request, room_name):
    room = get_object_or_404(Room, name=room_name)
    if not PublicRoomMember.objects.filter(room=room, user=request.user).exists():
        messages.error(request, "You are not a member of this room.")
        return redirect("chat:index")
    Message.objects.filter(room=room, sender=request.user).delete()
    messages.success(request, f"Deleted your messages in #{room.name}.")
    return redirect("chat:room", room_name=room.name)


@login_required
@require_POST
def create_private_chat(request):
    username = normalize_username(request.POST.get("username", ""))
    if not username:
        messages.error(request, "Username required.")
        return redirect("chat:index")

    target = User.objects.filter(username=username).first()
    if not target:
        messages.error(request, "User not found.")
        return redirect("chat:index")

    if target == request.user:
        messages.error(request, "You cannot chat with yourself.")
        return redirect("chat:index")

    if Block.objects.filter(blocker=target, blocked=request.user).exists():
        messages.error(request, "You cannot start this conversation.")
        return redirect("chat:index")

    PrivateChat.between(request.user, target)
    return redirect("chat:private_chat", username=target.username)


@login_required
def private_chat(request, username):
    other_user = get_object_or_404(User, username=username)

    if other_user == request.user:
        return redirect("chat:index")

    low, high = (
        (request.user, other_user)
        if request.user.pk < other_user.pk
        else (other_user, request.user)
    )
    chat = PrivateChat.objects.filter(user1=low, user2=high).first()

    if not chat:
        messages.error(request, "Conversation not found.")
        return redirect("chat:index")

    is_blocked = Block.objects.filter(blocker=request.user, blocked=other_user).exists()
    blocked_by_them = Block.objects.filter(
        blocker=other_user, blocked=request.user
    ).exists()

    chat_messages = (
        chat.messages.select_related("sender")
        .exclude(
            sender__in=Block.objects.filter(blocker=request.user).values("blocked")
        )
        .order_by("-created")[:MESSAGE_PAGE_SIZE][::-1]
    )
    return render(
        request,
        "chat/private_chat.html",
        {
            "chat": chat,
            "other_user": other_user,
            "chat_messages": chat_messages,
            "is_blocked": is_blocked,
            "blocked_by_them": blocked_by_them,
        },
    )


@login_required
@require_POST
def block_user(request, username):
    target = get_object_or_404(User, username=username)
    if target == request.user:
        return redirect("chat:index")
    Block.objects.get_or_create(blocker=request.user, blocked=target)
    messages.success(request, f"Blocked @{target.username}.")
    return redirect("chat:private_chat", username=target.username)


@login_required
@require_POST
def unblock_user(request, username):
    target = get_object_or_404(User, username=username)
    Block.objects.filter(blocker=request.user, blocked=target).delete()
    messages.success(request, f"Unblocked @{target.username}.")
    return redirect("chat:private_chat", username=target.username)


@login_required
@require_POST
def delete_private_history(request, username):
    other_user = get_object_or_404(User, username=username)
    low, high = (
        (request.user, other_user)
        if request.user.pk < other_user.pk
        else (other_user, request.user)
    )
    chat = PrivateChat.objects.filter(user1=low, user2=high).first()
    if not chat:
        return redirect("chat:index")
    PrivateChatMessage.objects.filter(chat=chat, sender=request.user).delete()
    messages.success(request, f"Deleted your messages with @{other_user.username}.")
    return redirect("chat:private_chat", username=other_user.username)


@login_required
@require_POST
def delete_private_room(request, room_name):
    room = get_object_or_404(PrivateRoom, name=room_name)
    if room.owner_id != request.user.pk:
        messages.error(request, "Only the room owner can delete it.")
        return redirect("chat:private_room", room_name=room.name)
    room.delete()
    messages.success(request, f"Deleted #{room_name}.")
    return redirect("chat:index")


@login_required
@require_POST
def create_private_room(request):
    name, err = validate_room_name(request.POST.get("room_name", ""))
    if err:
        messages.error(request, err)
        return redirect("chat:index")

    if PrivateRoom.objects.filter(name=name).exists():
        messages.error(request, "Room already exists.")
        return redirect("chat:index")

    room = PrivateRoom.objects.create(name=name, owner=request.user)
    PrivateRoomMember.objects.create(room=room, user=request.user)
    messages.success(request, f"Private room #{name} created.")
    return redirect("chat:private_room", room_name=name)


@login_required
def private_room(request, room_name):
    room = get_object_or_404(PrivateRoom, name=room_name)
    is_member = room.is_member(request.user)
    is_owner = room.owner_id == request.user.pk

    if not is_member:
        return render(
            request,
            "chat/join_private_room.html",
            {"room": room},
        )

    chat_messages = (
        PrivateRoomMessage.objects.filter(room=room)
        .select_related("sender")
        .exclude(
            sender__in=Block.objects.filter(blocker=request.user).values("blocked")
        )
        .order_by("-created")[:MESSAGE_PAGE_SIZE][::-1]
    )
    return render(
        request,
        "chat/private_room.html",
        {
            "room": room,
            "is_owner": is_owner,
            "chat_messages": chat_messages,
        },
    )


@login_required
@require_POST
def leave_private_room(request, room_name):
    room = get_object_or_404(PrivateRoom, name=room_name)
    if room.owner_id == request.user.pk:
        messages.error(request, "Owner cannot leave. Delete the room first.")
        return redirect("chat:private_room", room_name=room.name)
    PrivateRoomMember.objects.filter(room=room, user=request.user).delete()
    messages.success(request, f"Left #{room.name}.")
    return redirect("chat:index")


@login_required
@require_POST
def delete_private_room_history(request, room_name):
    room = get_object_or_404(PrivateRoom, name=room_name)
    if not PrivateRoomMember.objects.filter(room=room, user=request.user).exists():
        messages.error(request, "You are not a member of this room.")
        return redirect("chat:index")
    PrivateRoomMessage.objects.filter(room=room, sender=request.user).delete()
    messages.success(request, f"Deleted your messages in #{room.name}.")
    return redirect("chat:private_room", room_name=room.name)


@login_required
def join_via_invite(request, token):
    room = get_object_or_404(PrivateRoom, invite_token=token)
    _, created = PrivateRoomMember.objects.get_or_create(room=room, user=request.user)
    if created:
        messages.success(request, f"Joined #{room.name}.")
    return redirect("chat:private_room", room_name=room.name)


@login_required
@require_POST
def join_by_link(request):
    raw = (request.POST.get("invite_link") or "").strip()
    if not raw:
        messages.error(request, "Paste an invite token.")
        return redirect("chat:index")

    token = raw.rstrip("/").rsplit("/", 1)[-1]
    room = PrivateRoom.objects.filter(invite_token=token).first()
    if not room:
        messages.error(request, "Invalid or expired invite token.")
        return redirect("chat:index")

    _, created = PrivateRoomMember.objects.get_or_create(room=room, user=request.user)
    if created:
        messages.success(request, f"Joined #{room.name}.")
    return redirect("chat:private_room", room_name=room.name)


@login_required
@require_POST
def rotate_invite(request, room_name):
    room = get_object_or_404(PrivateRoom, name=room_name)
    if room.owner_id != request.user.pk:
        messages.error(request, "Only the room owner can rotate the invite token.")
        return redirect("chat:private_room", room_name=room.name)

    room.rotate_invite_token()
    messages.success(request, "Invite token rotated. Old token is dead.")
    return redirect("chat:private_room", room_name=room.name)
