"""Sends an authenticated user without a compañía de trabajo picked to the
selector before letting them into the rest of the app (RF-02)."""
from django.shortcuts import redirect

from .views import SESSION_KEY

EXEMPT_PATH_PREFIXES = (
    "/cuenta/login/",
    "/cuenta/logout/",
    "/compania/",
    "/manifest.json",
    "/sw.js",
    "/health/",
    "/static/",
)


class CompaniaContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and SESSION_KEY not in request.session
            and not request.path.startswith(EXEMPT_PATH_PREFIXES)
        ):
            return redirect(f"/compania/?next={request.path}")
        return self.get_response(request)
