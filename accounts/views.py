import re

from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages

RESERVED_USERNAMES = {
    "admin",
    "administrator",
    "root",
    "system",
    "support",
    "security",
    "securechat",
    "chat",
    "server",
    "api",
    "null",
    "test",
    "guest",
}


def login_view(request):

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is not None:
            login(request, user)

            messages.success(request, "Welcome back!")

            return redirect("home")

        else:
            messages.error(request, "Invalid username or password.")

    return render(request, "accounts/login.html")


def register_view(request):

    if request.method == "POST":
        username = request.POST.get("username").strip()
        username = username.lower()

        if username in RESERVED_USERNAMES:
            messages.error(request, "That username is reserved.")
            return redirect("register")

        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        if len(username) < 3 or len(username) > 32:
            messages.error(request, "Username must be between 3 and 32 characters.")
            return redirect("register")

        if not re.fullmatch(r"[A-Za-z0-9_.-]+", username):
            messages.error(
                request, "Username may contain only letters, numbers, '.', '_' and '-'."
            )
            return redirect("register")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return redirect("register")

        if len(password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return redirect("register")

        if len(password) > 128:
            messages.error(request, "Password is too long.")
            return redirect("register")

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect("register")

        User.objects.create_user(username=username, password=password)

        messages.success(request, "Account created successfully.")

        return redirect("login")

    return render(request, "accounts/register.html")
