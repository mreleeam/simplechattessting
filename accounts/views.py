import re

from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from chat.validators import RESERVED_USERNAMES, normalize_username
from .models import LoginRecord, get_profile

User = get_user_model()


def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def login_view(request):
    if request.method == "POST":
        username = normalize_username(request.POST.get("username", ""))
        password = request.POST.get("password", "")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            request.session.flush()
            login(request, user)
            LoginRecord.objects.create(
                user=user,
                ip=_client_ip(request),
                user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300]),
            )
            messages.success(request, "Welcome back!")
            return redirect("home")

        messages.error(request, "Invalid username or password.")

    return render(request, "accounts/login.html")


def register_view(request):
    if request.method == "POST":
        username = normalize_username(request.POST.get("username", ""))
        password = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if len(username) < 3 or len(username) > 32:
            messages.error(request, "Username must be between 3 and 32 characters.")
            return redirect("register")

        if not re.fullmatch(r"[a-z0-9_.-]+", username):
            messages.error(
                request, "Username may contain only letters, numbers, '.', '_' and '-'."
            )
            return redirect("register")

        if username in RESERVED_USERNAMES:
            messages.error(request, "That username is reserved.")
            return redirect("register")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return redirect("register")

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect("register")

        try:
            validate_password(password)
        except ValidationError as exc:
            for err in exc.messages:
                messages.error(request, err)
            return redirect("register")

        User.objects.create_user(username=username, password=password)
        messages.success(request, "Account created successfully.")
        return redirect("login")

    return render(request, "accounts/register.html")


@login_required(login_url="login")
def account_view(request):
    profile = get_profile(request.user)
    records = LoginRecord.objects.filter(user=request.user)[:5]
    return render(
        request,
        "accounts/account.html",
        {
            "title": "Account",
            "user": request.user,
            "profile": profile,
            "login_records": records,
        },
    )


@login_required(login_url="login")
@require_POST
def update_profile_view(request):
    profile = get_profile(request.user)
    bio = request.POST.get("bio", "").strip()
    age_raw = request.POST.get("age", "").strip()
    location = request.POST.get("location", "").strip()

    if len(bio) > 500:
        messages.error(request, "Bio must be 500 characters or fewer.")
        return redirect("account")

    if len(location) > 80:
        messages.error(request, "Location must be 80 characters or fewer.")
        return redirect("account")

    age = None
    if age_raw:
        try:
            age = int(age_raw)
        except ValueError:
            messages.error(request, "Age must be a number.")
            return redirect("account")
        if age < 13 or age > 120:
            messages.error(request, "Age must be between 13 and 120.")
            return redirect("account")

    profile.bio = bio
    profile.age = age
    profile.location = location
    profile.save()

    messages.success(request, "Profile updated.")
    return redirect("account")


@login_required(login_url="login")
@require_POST
def change_password_view(request):
    current_password = request.POST.get("current_password", "")
    new_password = request.POST.get("new_password", "")
    confirm_password = request.POST.get("confirm_password", "")

    if not request.user.check_password(current_password):
        messages.error(request, "Current password is incorrect.")
        return redirect("account")

    if new_password != confirm_password:
        messages.error(request, "Passwords do not match.")
        return redirect("account")

    try:
        validate_password(new_password, user=request.user)
    except ValidationError as exc:
        for err in exc.messages:
            messages.error(request, err)
        return redirect("account")

    request.user.set_password(new_password)
    request.user.save()
    update_session_auth_hash(request, request.user)

    messages.success(request, "Password changed successfully.")
    return redirect("account")


@login_required(login_url="login")
@require_POST
def logout_view(request):
    logout(request)
    messages.success(request, "Logged out successfully.")
    return redirect("home")


@login_required(login_url="login")
@require_POST
def delete_account_view(request):
    password = request.POST.get("password", "")
    confirmation = request.POST.get("confirmation", "").strip()

    if not request.user.check_password(password):
        messages.error(request, "Incorrect password.")
        return redirect("account")

    if confirmation != "DELETE":
        messages.error(request, "Type DELETE to confirm.")
        return redirect("account")

    user = request.user
    user.delete()
    logout(request)
    messages.success(request, "Your account has been deleted.")
    return redirect("home")
