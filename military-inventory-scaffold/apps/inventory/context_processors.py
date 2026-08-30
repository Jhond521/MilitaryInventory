from .models import Compania
from .views import SESSION_KEY


def compania_actual(request):
    """Exposes the working company (session-scoped, RF-02) to every template."""
    compania_id = getattr(request, "session", {}).get(SESSION_KEY)
    if not compania_id:
        return {"compania_actual": None}
    return {"compania_actual": Compania.objects.filter(pk=compania_id).first()}
