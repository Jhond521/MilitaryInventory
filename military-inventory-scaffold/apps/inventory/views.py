"""Selección de compañía de trabajo (RF-02).

Es solo un contexto por defecto para los listados — no restringe qué
compañías puede ver un usuario (S-2): los 6 usuarios siguen viendo todas.
"""
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Compania

SESSION_KEY = "compania_actual_id"


@staff_member_required
def elegir_compania(request):
    companias = Compania.objects.order_by("nombre")

    next_url = request.POST.get("next") or request.GET.get("next") or reverse("admin:index")
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = reverse("admin:index")

    if request.method == "POST":
        compania_id = request.POST.get("compania")
        if compania_id and companias.filter(pk=compania_id).exists():
            request.session[SESSION_KEY] = int(compania_id)
            return redirect(next_url)

    context = {
        **admin.site.each_context(request),
        "title": "Elegir compañía de trabajo",
        "companias": companias,
        "actual_id": request.session.get(SESSION_KEY),
        "next": next_url,
    }
    return render(request, "inventory/elegir_compania.html", context)
