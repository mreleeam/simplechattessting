from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
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
    PrivateRoomBan,
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


def _admin_required(room, user):
    if room.owner_id == user.pk:
        return True
    m = room.membership(user)
    return m is not None and m.is_admin


def _is_ajax(request):
    return request.META.get("HTTP_X_REQUESTED_WITH", "").lower() == "xmlhttprequest"


def _send(group, payload):
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(group, payload)


def _push_event(user_ids, event_type, slug="", name="", kind=""):
    if not user_ids:
        return
    payload = {
        "type": "room_event",
        "event_type": event_type,
        "slug": slug,
        "name": name,
        "kind": kind,
    }
    for uid in user_ids:
        _send(f"user_events_{uid}", payload)


def _push_chat_event(group_name, event_type, msg_id=None, extra=None):
    if not group_name:
        return
    payload = {
        "type": "chat_event",
        "event_type": event_type,
    }
    if msg_id is not None:
        payload["id"] = msg_id
    if extra:
        payload.update(extra)
    _send(group_name, payload)


def _notify_member_change(room):
    _push_chat_event(f"privateroom_{room.slug}", "member_change")


def _system_public(room, user, text):
    msg = Message.objects.create(
        room=room, sender=user, content=text, is_system=True,
    )
    _push_chat_event(
        f"chat_{room.slug}", "system",
        msg.id,
        {
            "username": user.username,
            "content": text,
            "created": msg.created.isoformat(),
            "timestamp": timezone.localtime(msg.created).strftime("%H:%M"),
            "full_timestamp": timezone.localtime(msg.created).strftime("%d %b %Y %H:%M"),
        },
    )


def _system_private_room(room, user, text):
    msg = PrivateRoomMessage.objects.create(
        room=room, sender=user, content=text, is_system=True,
    )
    _push_chat_event(
        f"privateroom_{room.slug}", "system",
        msg.id,
        {
            "username": user.username,
            "content": text,
            "created": msg.created.isoformat(),
            "timestamp": timezone.localtime(msg.created).strftime("%H:%M"),
            "full_timestamp": timezone.localtime(msg.created).strftime("%d %b %Y %H:%M"),
        },
    )


def _group_for_message(kind, obj):
    if kind == "room":
        return f"chat_{obj.room.slug}"
    if kind == "pr":
        return f"privateroom_{obj.room.slug}"
    if kind == "pc":
        return f"private_{obj.chat_id}"
    return None


def _room_snapshot(room, viewer):
    members = [
        {
            "username": m.user.username,
            "userId": m.user.pk,
            "isAdmin": m.is_admin,
            "isMuted": m.is_muted,
        }
        for m in room.members.select_related("user").order_by("user__username")
    ]
    banned = [
        {"username": b.user.username}
        for b in room.bans.select_related("user").order_by("user__username")
    ]
    return {
        "slug": room.slug,
        "name": room.name,
        "isOwner": room.owner_id == viewer.pk,
        "isLocked": room.is_locked,
        "ownerId": room.owner_id,
        "members": members,
        "banned": banned,
    }


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


def _cleared_public(room, user):
    m = ReadMarker.objects.filter(user=user, room=room).first()
    return m.cleared_at if m and m.cleared_at else None


def _cleared_private_room(room, user):
    m = ReadMarker.objects.filter(user=user, private_room=room).first()
    return m.cleared_at if m and m.cleared_at else None


def _cleared_private_chat(chat, user):
    m = ReadMarker.objects.filter(user=user, private_chat=chat).first()
    return m.cleared_at if m and m.cleared_at else None


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
        "is_system": getattr(m, "is_system", False),
    }


@login_required
def index(request):
    my_public_rooms = list(Room.objects.filter(members__user=request.user).distinct())
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
def room(request, slug):
    room = get_object_or_404(Room, slug=slug)
    PublicRoomMember.objects.get_or_create(room=room, user=request.user)
    _touch_public(room, request.user)
    cleared = _cleared_public(room, request.user)
    base = room.messages.select_related("sender").exclude(
        sender__in=Block.objects.filter(blocker=request.user).values("blocked")
    )
    if cleared:
        base = base.filter(created__gt=cleared)
    qs = _with_reactions(base.order_by("-id"))
    messages_page = list(qs[:PAGE_SIZE])
    messages_page.reverse()
    has_more = qs.count() > PAGE_SIZE
    my_reactions = dict(
        Reaction.objects.filter(
            user=request.user,
            room_message__in=[m.id for m in messages_page if not getattr(m, "is_system", False)],
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
def older_public_messages(request, slug):
    room = get_object_or_404(Room, slug=slug)
    cleared = _cleared_public(room, request.user)
    before = request.GET.get("before")
    qs = room.messages.select_related("sender").order_by("-id")
    if cleared:
        qs = qs.filter(created__gt=cleared)
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
def leave_public_room(request, slug):
    room = get_object_or_404(Room, slug=slug)
    PublicRoomMember.objects.filter(room=room, user=request.user).delete()
    _system_public(room, request.user, "left the room")
    _push_event([request.user.pk], "refresh_index")
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

    room = Room.objects.filter(name=name).first()
    created = False
    if not room:
        room = Room.objects.create(name=name)
        created = True

    _, joined = PublicRoomMember.objects.get_or_create(room=room, user=request.user)
    if joined:
        _system_public(room, request.user, "joined the room")
    _push_event([request.user.pk], "refresh_index")
    if created:
        messages.success(request, f"Public room #{name} created.")
    else:
        messages.success(request, f"Joined #{name}.")
    return redirect("chat:room", slug=room.slug)


@login_required
@require_POST
def delete_public_history(request, slug):
    room = get_object_or_404(Room, slug=slug)
    if not PublicRoomMember.objects.filter(room=room, user=request.user).exists():
        messages.error(request, "You are not a member of this room.")
        return redirect("chat:index")

    now = timezone.now()
    marker, _ = ReadMarker.objects.get_or_create(
        user=request.user, room=room, private_room=None, private_chat=None,
        defaults={"last_read_at": now},
    )
    marker.cleared_at = now
    marker.save(update_fields=["cleared_at"])

    _push_chat_event(f"chat_{room.slug}", "clear_all")
    messages.success(request, f"Cleared messages in #{room.name} for you.")
    return redirect("chat:room", slug=room.slug)


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
    _push_event([request.user.pk, target.pk], "refresh_index")
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

    cleared = _cleared_private_chat(chat, request.user)
    base = chat.messages.select_related("sender").exclude(
        sender__in=Block.objects.filter(blocker=request.user).values("blocked")
    )
    if cleared:
        base = base.filter(created__gt=cleared)
    qs = _with_reactions(base.order_by("-id"))
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
    cleared = _cleared_private_chat(chat, request.user)
    before = request.GET.get("before")
    qs = chat.messages.select_related("sender").order_by("-id")
    if cleared:
        qs = qs.filter(created__gt=cleared)
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
    _push_event([request.user.pk], "refresh_index")
    messages.success(request, f"Removed conversation with @{other_user.username}.")
    return redirect("chat:index")


@login_required
@require_POST
def block_user(request, username):
    target = get_object_or_404(User, username=username)
    if target == request.user:
        return redirect("chat:index")
    Block.objects.get_or_create(blocker=request.user, blocked=target)
    _push_event([request.user.pk, target.pk], "refresh_index")
    messages.success(request, f"Blocked @{target.username}.")
    return redirect("chat:profile", username=target.username)


@login_required
@require_POST
def unblock_user(request, username):
    target = get_object_or_404(User, username=username)
    Block.objects.filter(blocker=request.user, blocked=target).delete()
    _push_event([request.user.pk, target.pk], "refresh_index")
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

    now = timezone.now()
    marker, _ = ReadMarker.objects.get_or_create(
        user=request.user, private_chat=chat, room=None, private_room=None,
        defaults={"last_read_at": now},
    )
    marker.cleared_at = now
    marker.save(update_fields=["cleared_at"])

    _push_chat_event(f"private_{chat.id}", "clear_all")
    messages.success(request, f"Cleared messages with @{other_user.username} for you.")
    return redirect("chat:private_chat", username=other_user.username)


@login_required
@require_POST
def create_private_room(request):
    name, err = validate_room_name(request.POST.get("room_name", ""))
    if err:
        messages.error(request, err)
        return redirect("chat:index")

    room = PrivateRoom.objects.create(name=name, owner=request.user)
    PrivateRoomMember.objects.create(room=room, user=request.user)
    _push_event([request.user.pk], "refresh_index")
    messages.success(request, f"Private room #{name} created.")
    return redirect("chat:private_room", slug=room.slug)


@login_required
def private_room(request, slug):
    room = get_object_or_404(PrivateRoom, slug=slug)
    membership = room.membership(request.user)
    is_owner = room.owner_id == request.user.pk
    is_admin = is_owner or (membership is not None and membership.is_admin)

    if membership is None:
        return render(
            request,
            "chat/join_private_room.html",
            {"room": room},
        )

    _touch_private_room(room, request.user)

    cleared = _cleared_private_room(room, request.user)
    base = PrivateRoomMessage.objects.filter(room=room).select_related("sender").exclude(
        sender__in=Block.objects.filter(blocker=request.user).values("blocked")
    )
    if cleared:
        base = base.filter(created__gt=cleared)
    qs = _with_reactions(base.order_by("-id"))
    messages_page = list(qs[:PAGE_SIZE])
    messages_page.reverse()
    has_more = qs.count() > PAGE_SIZE
    my_reactions = dict(
        Reaction.objects.filter(
            user=request.user,
            private_room_message__in=[m.id for m in messages_page if not getattr(m, "is_system", False)],
        ).values_list("private_room_message_id", "value")
    )

    members = room.members.select_related("user").order_by("user__username")
    banned_users = room.bans.select_related("user").order_by("user__username")

    return render(
        request,
        "chat/private_room.html",
        {
            "room": room,
            "is_owner": is_owner,
            "is_admin": is_admin,
            "my_membership": membership,
            "members": members,
            "banned_users": banned_users,
            "chat_messages": messages_page,
            "has_more": has_more,
            "my_reactions": my_reactions,
        },
    )


@login_required
def older_private_room_messages(request, slug):
    room = get_object_or_404(PrivateRoom, slug=slug)
    if not PrivateRoomMember.objects.filter(room=room, user=request.user).exists():
        return JsonResponse({"messages": [], "has_more": False})
    cleared = _cleared_private_room(room, request.user)
    before = request.GET.get("before")
    qs = PrivateRoomMessage.objects.filter(room=room).select_related("sender").order_by("-id")
    if cleared:
        qs = qs.filter(created__gt=cleared)
    if before:
        qs = qs.filter(id__lt=int(before))
    page = list(qs[:PAGE_SIZE])
    page.reverse()
    return JsonResponse({
        "messages": [_serialize(m) for m in page],
        "has_more": len(page) == PAGE_SIZE,
    })


@login_required
def room_members_json(request, slug):
    room = get_object_or_404(PrivateRoom, slug=slug)
    if not room.membership(request.user):
        return JsonResponse({"error": "Not a member"}, status=403)
    return JsonResponse(_room_snapshot(room, request.user))


@login_required
@require_POST
def leave_private_room(request, slug):
    room = get_object_or_404(PrivateRoom, slug=slug)
    if room.owner_id == request.user.pk:
        messages.error(request, "Owner cannot leave. Delete the room first.")
        return redirect("chat:private_room", slug=room.slug)

    member = room.membership(request.user)
    if member:
        member.delete()
    _system_private_room(room, request.user, "left the room")
    _notify_member_change(room)
    _push_event([request.user.pk], "refresh_index")
    messages.success(request, f"Left #{room.name}.")
    return redirect("chat:index")


@login_required
@require_POST
def delete_private_room_history(request, slug):
    room = get_object_or_404(PrivateRoom, slug=slug)
    if not PrivateRoomMember.objects.filter(room=room, user=request.user).exists():
        messages.error(request, "You are not a member of this room.")
        return redirect("chat:index")

    now = timezone.now()
    marker, _ = ReadMarker.objects.get_or_create(
        user=request.user, private_room=room, room=None, private_chat=None,
        defaults={"last_read_at": now},
    )
    marker.cleared_at = now
    marker.save(update_fields=["cleared_at"])

    _push_chat_event(f"privateroom_{room.slug}", "clear_all")
    messages.success(request, f"Cleared messages in #{room.name} for you.")
    return redirect("chat:private_room", slug=room.slug)


@login_required
@require_POST
def delete_private_room(request, slug):
    room = get_object_or_404(PrivateRoom, slug=slug)
    if room.owner_id != request.user.pk:
        messages.error(request, "Only the room owner can delete it.")
        return redirect("chat:private_room", slug=room.slug)
    member_ids = list(room.members.values_list("user_id", flat=True))
    room_name = room.name
    room.delete()
    _push_event(member_ids, "refresh_index")
    messages.success(request, f"Deleted #{room_name}.")
    return redirect("chat:index")


@login_required
@require_POST
def rotate_invite(request, slug):
    room = get_object_or_404(PrivateRoom, slug=slug)
    if room.owner_id != request.user.pk:
        messages.error(request, "Only the room owner can rotate the invite token.")
        return redirect("chat:private_room", slug=room.slug)

    room.rotate_invite_token()
    messages.success(request, "Invite token rotated. Old token is dead.")
    return redirect("chat:private_room", slug=room.slug)


@login_required
@require_POST
def toggle_room_lock(request, slug):
    room = get_object_or_404(PrivateRoom, slug=slug)
    if not _admin_required(room, request.user):
        if _is_ajax(request):
            return JsonResponse({"error": "Only admins can do that."}, status=403)
        messages.error(request, "Only admins can do that.")
        return redirect("chat:private_room", slug=room.slug)

    room.is_locked = not room.is_locked
    room.save(update_fields=["is_locked"])
    _notify_member_change(room)

    if _is_ajax(request):
        return JsonResponse(_room_snapshot(room, request.user))

    messages.success(
        request,
        "Room locked. Only admins can send." if room.is_locked else "Room unlocked.",
    )
    return redirect("chat:private_room", slug=room.slug)


@login_required
@require_POST
def mute_member(request, slug, username):
    room = get_object_or_404(PrivateRoom, slug=slug)
    if not _admin_required(room, request.user):
        if _is_ajax(request):
            return JsonResponse({"error": "Only admins can do that."}, status=403)
        messages.error(request, "Only admins can do that.")
        return redirect("chat:private_room", slug=room.slug)

    target = get_object_or_404(User, username=username)
    if target.pk == room.owner_id:
        if _is_ajax(request):
            return JsonResponse({"error": "Cannot mute the owner."}, status=400)
        messages.error(request, "Cannot mute the owner.")
        return redirect("chat:private_room", slug=room.slug)

    target_m = room.membership(target)
    if not target_m:
        if _is_ajax(request):
            return JsonResponse({"error": "User is not a member."}, status=400)
        return redirect("chat:private_room", slug=room.slug)

    if target_m.is_admin and room.owner_id != request.user.pk:
        if _is_ajax(request):
            return JsonResponse({"error": "Only the owner can mute admins."}, status=403)
        messages.error(request, "Only the owner can mute admins.")
        return redirect("chat:private_room", slug=room.slug)

    target_m.is_muted = not target_m.is_muted
    target_m.save(update_fields=["is_muted"])
    _notify_member_change(room)

    if _is_ajax(request):
        return JsonResponse(_room_snapshot(room, request.user))

    messages.success(
        request,
        f"{'Muted' if target_m.is_muted else 'Unmuted'} @{target.username}.",
    )
    return redirect("chat:private_room", slug=room.slug)


@login_required
@require_POST
def remove_member(request, slug, username):
    room = get_object_or_404(PrivateRoom, slug=slug)
    if not _admin_required(room, request.user):
        if _is_ajax(request):
            return JsonResponse({"error": "Only admins can do that."}, status=403)
        messages.error(request, "Only admins can do that.")
        return redirect("chat:private_room", slug=room.slug)

    target = get_object_or_404(User, username=username)
    if target.pk == room.owner_id:
        if _is_ajax(request):
            return JsonResponse({"error": "Cannot remove the owner."}, status=400)
        messages.error(request, "Cannot remove the owner.")
        return redirect("chat:private_room", slug=room.slug)

    target_m = room.membership(target)
    if not target_m:
        if _is_ajax(request):
            return JsonResponse({"error": "User is not a member."}, status=400)
        return redirect("chat:private_room", slug=room.slug)

    if target_m.is_admin and room.owner_id != request.user.pk:
        if _is_ajax(request):
            return JsonResponse({"error": "Only the owner can remove admins."}, status=403)
        messages.error(request, "Only the owner can remove admins.")
        return redirect("chat:private_room", slug=room.slug)

    PrivateRoomBan.objects.get_or_create(
        room=room, user=target, defaults={"banned_by": request.user}
    )
    target_m.delete()
    _system_private_room(room, target, "was banned")
    _notify_member_change(room)
    _push_event([target.pk], "refresh_index")

    if _is_ajax(request):
        return JsonResponse(_room_snapshot(room, request.user))

    messages.success(request, f"Removed and banned @{target.username}.")
    return redirect("chat:private_room", slug=room.slug)


@login_required
@require_POST
def unban_member(request, slug, username):
    room = get_object_or_404(PrivateRoom, slug=slug)
    if not _admin_required(room, request.user):
        if _is_ajax(request):
            return JsonResponse({"error": "Only admins can do that."}, status=403)
        messages.error(request, "Only admins can do that.")
        return redirect("chat:private_room", slug=room.slug)

    target = get_object_or_404(User, username=username)
    PrivateRoomBan.objects.filter(room=room, user=target).delete()
    _notify_member_change(room)
    _push_event([target.pk], "refresh_index")

    if _is_ajax(request):
        return JsonResponse(_room_snapshot(room, request.user))

    messages.success(request, f"Unbanned @{target.username}.")
    return redirect("chat:private_room", slug=room.slug)


@login_required
@require_POST
def promote_member(request, slug, username):
    room = get_object_or_404(PrivateRoom, slug=slug)
    if room.owner_id != request.user.pk:
        if _is_ajax(request):
            return JsonResponse({"error": "Only the owner can promote."}, status=403)
        messages.error(request, "Only the owner can promote.")
        return redirect("chat:private_room", slug=room.slug)

    target = get_object_or_404(User, username=username)
    if target.pk == room.owner_id:
        if _is_ajax(request):
            return JsonResponse({"error": "Cannot promote the owner."}, status=400)
        return redirect("chat:private_room", slug=room.slug)

    target_m = room.membership(target)
    if not target_m:
        if _is_ajax(request):
            return JsonResponse({"error": "User is not a member."}, status=400)
        return redirect("chat:private_room", slug=room.slug)

    target_m.is_admin = True
    target_m.save(update_fields=["is_admin"])
    _notify_member_change(room)
    _push_event([target.pk], "refresh_room", slug=room.slug, name=room.name)

    if _is_ajax(request):
        return JsonResponse(_room_snapshot(room, request.user))

    messages.success(request, f"Promoted @{target.username} to admin.")
    return redirect("chat:private_room", slug=room.slug)


@login_required
@require_POST
def demote_member(request, slug, username):
    room = get_object_or_404(PrivateRoom, slug=slug)
    if room.owner_id != request.user.pk:
        if _is_ajax(request):
            return JsonResponse({"error": "Only the owner can demote admins."}, status=403)
        messages.error(request, "Only the owner can demote admins.")
        return redirect("chat:private_room", slug=room.slug)

    target = get_object_or_404(User, username=username)
    if target.pk == room.owner_id:
        if _is_ajax(request):
            return JsonResponse({"error": "Cannot demote the owner."}, status=400)
        return redirect("chat:private_room", slug=room.slug)

    target_m = room.membership(target)
    if not target_m:
        if _is_ajax(request):
            return JsonResponse({"error": "User is not a member."}, status=400)
        return redirect("chat:private_room", slug=room.slug)

    target_m.is_admin = False
    target_m.save(update_fields=["is_admin"])
    _notify_member_change(room)
    _push_event([target.pk], "refresh_room", slug=room.slug, name=room.name)

    if _is_ajax(request):
        return JsonResponse(_room_snapshot(room, request.user))

    messages.success(request, f"Demoted @{target.username}.")
    return redirect("chat:private_room", slug=room.slug)


@login_required
def join_via_invite(request, token):
    room = get_object_or_404(PrivateRoom, invite_token=token)
    if PrivateRoomBan.objects.filter(room=room, user=request.user).exists():
        messages.error(request, "You are banned from this room.")
        return redirect("chat:index")
    _, created = PrivateRoomMember.objects.get_or_create(
        room=room, user=request.user
    )
    if created:
        _system_private_room(room, request.user, "joined the room")
        _notify_member_change(room)
        _push_event([request.user.pk], "refresh_index")
        messages.success(request, f"Joined #{room.name}.")
    return redirect("chat:private_room", slug=room.slug)


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

    if PrivateRoomBan.objects.filter(room=room, user=request.user).exists():
        messages.error(request, "You are banned from this room.")
        return redirect("chat:index")

    _, created = PrivateRoomMember.objects.get_or_create(
        room=room, user=request.user
    )
    if created:
        _system_private_room(room, request.user, "joined the room")
        _notify_member_change(room)
        _push_event([request.user.pk], "refresh_index")
        messages.success(request, f"Joined #{room.name}.")
    return redirect("chat:private_room", slug=room.slug)


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

    if getattr(obj, "is_system", False):
        return JsonResponse({"error": "Cannot edit system messages"}, status=403)

    if timezone.now() - obj.created > EDIT_WINDOW:
        return JsonResponse(
            {"error": "Messages can only be edited within 24 hours."},
            status=403,
        )

    obj.content = new_content
    obj.edited_at = timezone.now()
    obj.save(update_fields=["content", "edited_at"])

    group = _group_for_message(kind, obj)
    _push_chat_event(group, "edit", obj.id, {"content": obj.content})

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

    if getattr(obj, "is_system", False):
        return JsonResponse({"error": "Cannot delete system messages"}, status=403)

    if timezone.now() - obj.created > EDIT_WINDOW:
        return JsonResponse(
            {"error": "Messages can only be deleted within 24 hours."},
            status=403,
        )

    group = _group_for_message(kind, obj)
    obj.delete()

    if group:
        _push_chat_event(group, "delete", int(msg_id))

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

    obj = model.objects.filter(id=msg_id).first()
    if not obj:
        return JsonResponse({"error": "Message not found"}, status=404)

    if getattr(obj, "is_system", False):
        return JsonResponse({"error": "Cannot react to system messages"}, status=403)

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
