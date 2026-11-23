# Smoke checks against the DEPLOYED dev environment, run inside its container.
#
# Used by /probar-dev (see .claude/commands/probar-dev.md). Do not run it by hand
# against production.
#
# How it runs: the command prepends a line `SPEC = {...}` (JSON) to this file,
# base64-encodes the result and pipes it into `python manage.py shell` over
# `railway ssh --environment dev`. Every request goes through Django's test
# Client, authenticated as an existing ADMIN user, inside ONE transaction that
# is always rolled back. Dev data is left exactly as it was, even after POSTs.
#
# SPEC shape:
# {
#   "compania": "<nombre>" | null,   # session "compañía de trabajo" (null = first one)
#   "deposito": "<nombre>" | null,   # session "depósito de trabajo" (optional)
#   "setup": "<python code>",        # optional; runs before the checks (inside the
#                                    # rolled-back transaction) to create fixtures
#                                    # in `ctx`, e.g. ctx["e"] = Existencia.objects...
#   "checks": [
#     {
#       "name": "AC-1 filtro categoría",
#       "method": "get" | "post",            # default get
#       "path": "/municion/?tipo={ctx[t].pk}",   # formatted with ctx
#       "data": {"cantidad": "1"},            # POST body (values formatted with ctx)
#       "status": [200],                      # accepted status codes (default [200])
#       "contains": ["siga-kpi-row"],         # substrings that must be in the body
#       "not_contains": ["Traceback"],
#       "assert": "response.context is None or True",  # optional python expr; must be truthy
#       "files": {"archivo": "xlsx"},         # optional uploads: field -> ctx key holding
#                                             # bytes; or [ctx key, filename]
#       "save": "export",                     # optional: ctx[key] = response.content
#       "max_seconds": 20,                    # optional: the request must take less
#       "login_as": "enlace"                  # optional: force_login(ctx[key]) BEFORE the
#                                             # request (null/"" = log out)
#     }
#   ]
# }
#
# Output: one line per check, `QA_RESULT {"name":..., "ok":..., "detail":...}`,
# then `QA_SUMMARY {"passed": n, "failed": m}`.
# `SPEC` is defined by the line prepended by /probar-dev.
# ruff: noqa: F821
import json
import time
import traceback

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from django.test.utils import setup_test_environment

from apps.inventory import models as m
from apps.inventory.views import SESSION_KEY, SESSION_KEY_DEPOSITO


class _Rollback(Exception):
    pass


def _fmt(value, ctx):
    if isinstance(value, str):
        return value.format(ctx=ctx)
    if isinstance(value, dict):
        return {k: _fmt(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_fmt(v, ctx) for v in value]
    return value


def _run(spec):
    results = []
    host = next((h for h in settings.ALLOWED_HOSTS if h and not h.startswith(".")), "localhost")
    # Instruments template rendering so `response.context` is available to
    # `assert` expressions. Only affects this short-lived process, never the
    # running gunicorn workers.
    setup_test_environment()
    try:
        with transaction.atomic():
            user = (
                get_user_model()
                .objects.filter(role="ADMIN", is_active=True)
                .order_by("pk")
                .first()
            )
            if user is None:
                raise RuntimeError("No hay un usuario ADMIN activo en dev.")
            client = Client(HTTP_HOST=host)
            client.force_login(user)

            compania = (
                m.Compania.objects.filter(nombre=spec["compania"]).first()
                if spec.get("compania")
                else m.Compania.objects.order_by("pk").first()
            )
            deposito = (
                m.Deposito.objects.get(nombre=spec["deposito"]) if spec.get("deposito") else None
            )

            def _sesion_de_trabajo():
                session = client.session
                if compania:
                    session[SESSION_KEY] = compania.pk
                if deposito:
                    session[SESSION_KEY_DEPOSITO] = deposito.pk
                session.save()

            _sesion_de_trabajo()

            ctx = {"compania": compania, "user": user}
            if spec.get("setup"):
                exec(spec["setup"], {"m": m, "ctx": ctx, "user": user})  # noqa: S102 — spec setup is our own repo file

            for check in spec.get("checks", []):
                name = check.get("name", check.get("path"))
                try:
                    path = _fmt(check["path"], ctx)
                    method = check.get("method", "get").lower()
                    data = _fmt(check.get("data", {}), ctx)
                    if "login_as" in check:
                        client.logout()
                        if check["login_as"]:
                            client.force_login(ctx[check["login_as"]])
                            _sesion_de_trabajo()
                    for field, source in check.get("files", {}).items():
                        key, filename = source if isinstance(source, list) else (source, f"{source}.xlsx")
                        data[field] = SimpleUploadedFile(filename, ctx[key])
                    inicio = time.perf_counter()
                    response = getattr(client, method)(path, data, secure=True)
                    segundos = time.perf_counter() - inicio
                    body = response.content.decode("utf-8", "replace")
                    if check.get("save"):
                        ctx[check["save"]] = response.content
                    problems = []
                    if check.get("max_seconds") and segundos >= check["max_seconds"]:
                        problems.append(f"tardó {segundos:.1f} s (máx {check['max_seconds']} s)")
                    if response.status_code not in check.get("status", [200]):
                        problems.append(f"status {response.status_code}")
                    for text in _fmt(check.get("contains", []), ctx):
                        if text not in body:
                            problems.append(f"falta {text!r}")
                    for text in _fmt(check.get("not_contains", []), ctx):
                        if text in body:
                            problems.append(f"sobra {text!r}")
                    if check.get("assert"):
                        env = {"response": response, "body": body, "m": m, "ctx": ctx}
                        if not eval(check["assert"], env):
                            problems.append(f"assert falso: {check['assert']}")
                    detail = "; ".join(problems) or "ok"
                    if check.get("max_seconds"):
                        detail += f" ({segundos:.2f} s)"
                    results.append({"name": name, "ok": not problems, "detail": detail})
                except Exception as exc:  # noqa: BLE001 — report, never crash the run
                    results.append(
                        {"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}
                    )
            raise _Rollback
    except _Rollback:
        pass
    except Exception:  # noqa: BLE001
        results.append({"name": "setup", "ok": False, "detail": traceback.format_exc()[-800:]})
    return results


_results = _run(SPEC)
for _r in _results:
    print("QA_RESULT " + json.dumps(_r, ensure_ascii=False))
print(
    "QA_SUMMARY "
    + json.dumps(
        {"passed": sum(r["ok"] for r in _results), "failed": sum(not r["ok"] for r in _results)}
    )
)
