"""Authentication backend enforcing the email allowlist (RF-01).

Even if a user row exists, login is refused unless the email is in
settings.AUTHORIZED_EMAILS. This is a second line of defense on top of
only creating accounts for authorized people.
"""
from django.conf import settings
from django.contrib.auth.backends import ModelBackend


class AllowlistModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        email = (username or kwargs.get("email") or "").lower()
        allowed = [e.lower() for e in getattr(settings, "AUTHORIZED_EMAILS", [])]
        if allowed and email not in allowed:
            return None
        return super().authenticate(request, username=username, password=password, **kwargs)
