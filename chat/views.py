from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    Block,
    Message,
    PrivateChat,
    PrivateChatMessage,
    PrivateRoom,
    PrivateRoomMember,
    PrivateRoomMessage,
    PublicRoomMember,
    Reaction,
    ReadMarker,
    Room,
)
from .validators import normalize_username, validate_room_name

User = get_user_model()

PAGE_SIZE = 50
EDIT_WINDOW = timedelta(hours=24)


def _with_reactions(qs):
    return qs.annotate(
        up=Count("reactions", filter=Q(reactions__value=1)),
        down=Count("reactions", filter=Q(reactions__value=-1)),
    )


def _touch_public(room, user):
    ReadMarker.objects.update_or_create(
        user=user, room=room, private_room=None, private_chat=None,
        defaults={"last_read_at": timezone.now()},
    )


def _touch_private_room(room, user):
    ReadMarker.objects.update_or_create(
        user=user, private_room=room, room=None, private_chat=None,
        defaults={"last_read_at": timezone.now()},
    )


def _touch_private_chat(chat, user):
    ReadMarker.objects.update_or_create(
        user=user, private_chat=chat, room=None, private_room=None,
        defaults={"last_read_at": timezone.now()},
    )


def _unread_count_public(room, user):
    marker = ReadMarker.objects.filter(user=user, room=room).first()
    qs = Message.objects.filter(room=room).exclude(sender=user)
    if marker:
        qs = qs.filter(created__gt=marker.last_read_at)
    return qs.count()


def _unread_count_private_room(room, user):
    marker = ReadMarker.objects.filter(user=user, private_room=room).first()
    qs = PrivateRoomMessage.objects.filter(room=room).exclude(sender=user)
    if marker:
        qs = qs.filter(created__gt=marker.last_read_at)
    return qs.count()


def _unread_count_private_chat(chat, user):
    marker = ReadMarker.objects.filter(user=user, private_chat=chat).first()
    qs = PrivateChatMessage.objects.filter(chat=chat).exclude(sender=user)
    if marker:
        qs = qs.filter(created__gt=marker.last_read_at)
    return qs.count()


def _serialize(m):
    kind_map = {
        Message: "room_message",
        PrivateRoomMessage: "private_room_message",
        PrivateChatMessage: "private_chat_message",
    }
    field = kind_map.get(type(m))
    up = down = 0
    if field:
        up = Reaction.objects.filter(value=1, **{field: m}).count()
        down = Reaction.objects.filter(value=-1, **{field: m}).count()
    return {
        "id": m.id,
        "username": m.sender.username,
        "content": m.content,
        "timestamp": timezone.localtime(m.created).strftime("%H:%M"),
        "full_timestamp": timezone.localtime(m.created).strftime("%d %b %Y %H:%M"),
        "created": m.created.isoformat(),
        "edited": bool(m.edited_at),
        "up": up,
        "down": down,
    }


@login_required
def index(request):
    my_public_rooms = list(
        Room.objects.filter(members__user=request.user).distinct()
    )
    for r in my_public_rooms:
        r.unread = _unread_count_public(r, request.user)

    private_chats = list(
        PrivateChat.objects.filter(Q(user1=request.user) | Q(user2=request.user))
        .filter(
            Q(user1=request.user, user1_hidden=False)
            | Q(user2=request.user, user2_hidden=False)
        )
        .select_related("user1", "user2")
        .distinct()
    )
    for c in private_chats:
        c.unread = _unread_count_private_chat(c, request.user)
        c.peer = c.user2 if c.user1_id == request.user.pk else c.user1

    private_rooms = list(
        PrivateRoom.objects.filter(members__user=request.user)
        .distinct()
        .order_by("name")
    )
    for r in private_rooms:
        r.unread = _unread_count_private_room(r, request.user)

    return render(
        request,
        "chat/index.html",
        {
            "my_public_rooms": my_public_rooms,
            "private_chats": private_chats,
            "private_rooms": private_rooms,
        },
    )


@login_required
def room(request, room_name):
    room = get_object_or_404(Room, name=room_name)
    PublicRoomMember.objects.get_or_create(room=room, user=request.user)
    _touch_public(room, request.user)
    qs = _with_reactions(
        room.messages.select_related("sender")
        .exclude(sender__in=Block.objects.filter(blocker=request.user).values("blocked"))
        .order_by("-id")
    )
    messages_page = list(qs[:PAGE_SIZE])
    messages_page.reverse()
    has_more = qs.count() > PAGE_SIZE
    my_reactions = dict(
        Reaction.objects.filter(
            user=request.user,
            room_message__in=[m.id for m in messages_page],
        ).values_list("room_message_id", "value")
    )
    return render(
        request,
        "chat/room.html",
        {
            "room": room,
            "chat_messages": messages_page,
            "has_more": has_more,
            "my_reactions": my_reactions,
        },
    )


@login_required
def older_public_messages(request, room_name):
    room = get_object_or_404(Room, name=room_name)
    before = request.GET.get("before")
    qs = room.messages.select_related("sender").order_by("-id")
    if before:
        qs = qs.filter(id__lt=int(before))
    page = list(qs[:PAGE_SIZE])
    page.reverse()
    return JsonResponse({
        "messages": [_serialize(m) for m in page],
        "has_more": len(page) == PAGE_SIZE,
    })


@login_required
def older_private_room_messages(request, room_name):
    room = get_object_or_404(PrivateRoom, name=room_name)
    if not PrivateRoomMember.objects.filter(room=room, user=request.user).exists():
        return JsonResponse({"messages": [], "has_more": False})
    before = request.GET.get("before")
    qs = PrivateRoomMessage.objects.filter(room=room).select_related("sender").order_by("-id")
    if before:
        qs = qs.filter(id__lt=int(before))
    page = list(qs[:PAGE_SIZE])
    page.reverse()
    return JsonResponse({
        "messages": [_serialize(m) for m in page],
        "has_more": len(page) == PAGE_SIZE,
    })


@login_required
def older_private_chat_messages(request, username):
    other_user = get_object_or_404(User, username=username)
    low, high = (
        (request.user, other_user)
        if request.user.pk < other_user.pk
        else (other_user, request.user)
    )
    chat = PrivateChat.objects.filter(user1=low, user2=high).first()
    if not chat:
        return JsonResponse({"messages": [], "has_more": False})
    before = request.GET.get("before")
    qs = chat.messages.select_related("sender").order_by("-id")
    if before:
        qs = qs.filter(id__lt=int(before))
    page = list(qs[:PAGE_SIZE])
    page.reverse()
    return JsonResponse({
        "messages": [_serialize(m) for m in page],
        "has_more": len(page) == PAGE_SIZE,
    })


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

    chat = PrivateChat.between(request.user, target)
    chat.unhide_for(request.user)
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

    chat.unhide_for(request.user)
    _touch_private_chat(chat, request.user)

    is_blocked = Block.objects.filter(
        blocker=request.user, blocked=other_user
    ).exists()
    blocked_by_them = Block.objects.filter(
        blocker=other_user, blocked=request.user
    ).exists()

    qs = _with_reactions(
        chat.messages.select_related("sender")
        .exclude(sender__in=Block.objects.filter(blocker=request.user).values("blocked"))
        .order_by("-id")
    )
    messages_page = list(qs[:PAGE_SIZE])
    messages_page.reverse()
    has_more = qs.count() > PAGE_SIZE
    my_reactions = dict(
        Reaction.objects.filter(
            user=request.user,
            private_chat_message__in=[m.id for m in messages_page],
        ).values_list("private_chat_message_id", "value")
    )

    return render(
        request,
        "chat/private_chat.html",
        {
            "chat": chat,
            "other_user": other_user,
            "chat_messages": messages_page,
            "has_more": has_more,
            "is_blocked": is_blocked,
            "blocked_by_them": blocked_by_them,
            "my_reactions": my_reactions,
        },
    )


@login_required
@require_POST
def remove_private_chat(request, username):
    other_user = get_object_or_404(User, username=username)
    low, high = (
        (request.user, other_user)
        if request.user.pk < other_user.pk
        else (other_user, request.user)
    )
    chat = PrivateChat.objects.filter(user1=low, user2=high).first()
    if chat:
        chat.hide_for(request.user)
    messages.success(request, f"Removed conversation with @{other_user.username}.")
    return redirect("chat:index")


@login_required
def profile(request, username):
    target = get_object_or_404(User, username=username)
    is_self = target.pk == request.user.pk
    is_blocked = Block.objects.filter(
        blocker=request.user, blocked=target
    ).exists()
    try:
        profile_obj = target.profile
    except Exception:
        profile_obj = None
    return render(
        request,
        "chat/profile.html",
        {
            "target": target,
            "is_self": is_self,
            "is_blocked": is_blocked,
            "profile": profile_obj,
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
    return redirect("chat:profile", username=target.username)


@login_required
@require_POST
def unblock_user(request, username):
    target = get_object_or_404(User, username=username)
    Block.objects.filter(blocker=request.user, blocked=target).delete()
    messages.success(request, f"Unblocked @{target.username}.")
    return redirect("chat:profile", username=target.username)


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

    _touch_private_room(room, request.user)

    qs = _with_reactions(
        PrivateRoomMessage.objects.filter(room=room)
        .select_related("sender")
        .exclude(sender__in=Block.objects.filter(blocker=request.user).values("blocked"))
        .order_by("-id")
    )
    messages_page = list(qs[:PAGE_SIZE])
    messages_page.reverse()
    has_more = qs.count() > PAGE_SIZE
    my_reactions = dict(
        Reaction.objects.filter(
            user=request.user,
            private_room_message__in=[m.id for m in messages_page],
        ).values_list("private_room_message_id", "value")
    )

    return render(
        request,
        "chat/private_room.html",
        {
            "room": room,
            "is_owner": is_owner,
            "chat_messages": messages_page,
            "has_more": has_more,
            "my_reactions": my_reactions,
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
def edit_message(request):
    msg_id = request.POST.get("id")
    kind = request.POST.get("kind")
    new_content = (request.POST.get("content") or "").strip()
    if not msg_id or not new_content or len(new_content) > 4000:
        return JsonResponse({"error": "Invalid"}, status=400)

    model = {"room": Message, "pr": PrivateRoomMessage, "pc": PrivateChatMessage}.get(kind)
    if not model:
        return JsonResponse({"error": "Invalid kind"}, status=400)

    obj = model.objects.filter(id=msg_id, sender=request.user).first()
    if not obj:
        return JsonResponse({"error": "Not found"}, status=403)

    if timezone.now() - obj.created > EDIT_WINDOW:
        return JsonResponse(
            {"error": "Messages can only be edited within 24 hours."},
            status=403,
        )

    obj.content = new_content
    obj.edited_at = timezone.now()
    obj.save(update_fields=["content", "edited_at"])
    return JsonResponse({"ok": True, "content": obj.content})


@login_required
@require_POST
def delete_message(request):
    msg_id = request.POST.get("id")
    kind = request.POST.get("kind")

    model = {"room": Message, "pr": PrivateRoomMessage, "pc": PrivateChatMessage}.get(kind)
    if not model:
        return JsonResponse({"error": "Invalid kind"}, status=400)

    obj = model.objects.filter(id=msg_id, sender=request.user).first()
    if not obj:
        return JsonResponse({"error": "Not found"}, status=403)

    if timezone.now() - obj.created > EDIT_WINDOW:
        return JsonResponse(
            {"error": "Messages can only be deleted within 24 hours."},
            status=403,
        )

    obj.delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def react_message(request):
    msg_id = request.POST.get("id")
    kind = request.POST.get("kind")
    value_raw = request.POST.get("value")

    try:
        value = int(value_raw)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid value"}, status=400)

    if value not in (1, -1):
        return JsonResponse({"error": "Value must be 1 or -1"}, status=400)

    field_map = {
        "room": "room_message",
        "pr": "private_room_message",
        "pc": "private_chat_message",
    }
    model_map = {
        "room": Message,
        "pr": PrivateRoomMessage,
        "pc": PrivateChatMessage,
    }
    field = field_map.get(kind)
    model = model_map.get(kind)
    if not field or not model:
        return JsonResponse({"error": "Invalid kind"}, status=400)

    if not model.objects.filter(id=msg_id).exists():
        return JsonResponse({"error": "Message not found"}, status=404)

    filter_kwargs = {"user": request.user, field + "_id": msg_id}
    existing = Reaction.objects.filter(**filter_kwargs).first()

    if existing:
        if existing.value == value:
            existing.delete()
            action = "removed"
        else:
            existing.value = value
            existing.save(update_fields=["value"])
            action = "swapped"
    else:
        Reaction.objects.create(
            user=request.user,
            value=value,
            **{field + "_id": msg_id},
        )
        action = "added"

    up = Reaction.objects.filter(value=1, **{field + "_id": msg_id}).count()
    down = Reaction.objects.filter(value=-1, **{field + "_id": msg_id}).count()

    return JsonResponse({
        "ok": True,
        "action": action,
        "value": value,
        "up": up,
        "down": down,
    })


@login_required
def message_reactions(request):
    msg_id = request.GET.get("id")
    kind = request.GET.get("kind")
    field = {
        "room": "room_message",
        "pr": "private_room_message",
        "pc": "private_chat_message",
    }.get(kind)
    if not field:
        return JsonResponse({"error": "Invalid kind"}, status=400)

    up = Reaction.objects.filter(value=1, **{field + "_id": msg_id}).count()
    down = Reaction.objects.filter(value=-1, **{field + "_id": msg_id}).count()
    mine = (
        Reaction.objects.filter(user=request.user, **{field + "_id": msg_id})
        .values_list("value", flat=True)
        .first()
    )
    return JsonResponse({"up": up, "down": down, "mine": mine or 0})


@login_required
def join_via_invite(request, token):
    room = get_object_or_404(PrivateRoom, invite_token=token)
    _, created = PrivateRoomMember.objects.get_or_create(
        room=room, user=request.user
    )
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

    _, created = PrivateRoomMember.objects.get_or_create(
        room=room, user=request.user
    )
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
