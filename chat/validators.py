import re

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
ROOM_NAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")

RESERVED_USERNAMES = frozenset({
    "admin", "administrator", "root", "system", "support",
    "security", "securechat", "chat", "server", "api",
    "null", "test", "guest",
})

RESERVED_ROOM_NAMES = frozenset({
    "admin", "new", "join", "create", "index", "api", "system",
    "pub", "private", "p", "pr", "r",
})


def normalize_username(value):
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def normalize_room_name(value):
    if not isinstance(value, str):
        return ""
    return value.strip().lstrip("#").lower()


def validate_username(value):
    name = normalize_username(value)
    if not name:
        return None, "Username required."
    if name in RESERVED_USERNAMES:
        return None, "That username is reserved."
    if not USERNAME_RE.match(name):
        return None, "Username must be 3-32 chars: a-z, 0-9, '.', '_', '-'."
    return name, None


def validate_room_name(value):
    name = normalize_room_name(value)
    if not name:
        return None, "Room name required."
    if name in RESERVED_ROOM_NAMES:
        return None, "That room name is reserved."
    if not ROOM_NAME_RE.match(name):
        return None, "Room name must be 3-32 chars: a-z, 0-9, '.', '_', '-'."
    return name, None


def validate_message_body(value, max_length=4000):
    if not isinstance(value, str):
        return None, "Invalid message."
    body = value.strip()
    if not body:
        return None, "Empty message."
    if len(body) > max_length:
        return None, f"Message exceeds {max_length} characters."
    return body, None
