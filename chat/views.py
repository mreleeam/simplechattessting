from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import Room


@login_required
def index(request):
    rooms = Room.objects.all()

    return render(
        request,
        "chat/index.html",
        {
            "rooms": rooms,
        },
    )


@login_required
def room(request, room_name):
    room = get_object_or_404(Room, name=room_name)

    return render(
        request,
        "chat/room.html",
        {
            "room": room,
            "messages": room.messages.all(),
        },
    )
