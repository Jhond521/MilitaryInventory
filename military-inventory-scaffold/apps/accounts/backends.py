"""Authentication backend enforcing the email allowlist (RF-01).

Even if a user row exists, login is refused unless the email is in
settings.AUTHORIZED_EMAILS. This is a second line of defense on top of
only creating accounts for authorized people.

Exception (issue #35, RF-25): users with role CONSULTA (read-only) are not
subject to the allowlist — an ADMIN creates them in any number. The
exemption is decided by the role stored in the database, after the
password check, so it can't be claimed by the person logging in.
"""
from django.conf import settings
from django.contrib.auth.backends import ModelBackend


class AllowlistModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is None or user.is_consulta_role:
            return user
        allowed = [e.lower() for e in getattr(settings, "AUTHORIZED_EMAILS", [])]
        if allowed and user.email.lower() not in allowed:
            return None
        return user
