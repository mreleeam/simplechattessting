from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.index, name="index"),
    path("r/<str:room_name>/", views.room, name="room"),
    # path("u/<str:username>/", views.private_chat, name="private"),
]
