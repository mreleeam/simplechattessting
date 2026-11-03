import time
from collections import defaultdict

from django.http import HttpResponse


class LoginRateLimitMiddleware:
    WINDOW = 300
    MAX_ATTEMPTS = 10

    def __init__(self, get_response):
        self.get_response = get_response
        self._attempts = defaultdict(list)

    def __call__(self, request):
        if request.method == "POST" and request.path.rstrip("/").endswith("/login"):
            ip = self._client_ip(request)
            now = time.monotonic()
            hits = [t for t in self._attempts[ip] if now - t < self.WINDOW]
            if len(hits) >= self.MAX_ATTEMPTS:
                return HttpResponse(
                    "Too many login attempts. Try again in a few minutes.",
                    status=429,
                )
            hits.append(now)
            self._attempts[ip] = hits

        return self.get_response(request)

    def _client_ip(self, request):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")
