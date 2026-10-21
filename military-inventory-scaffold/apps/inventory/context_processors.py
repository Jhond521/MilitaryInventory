from .models import Compania, Deposito
from .views import SESSION_KEY, SESSION_KEY_DEPOSITO


def compania_actual(request):
    """Exposes the working company and depósito (session-scoped, RF-02,
    issue #25) to every template. Either may be `None`: the selection only
    requires one of the two."""
    session = getattr(request, "session", {})
    compania_id = session.get(SESSION_KEY)
    deposito_id = session.get(SESSION_KEY_DEPOSITO)
    return {
        "compania_actual": Compania.objects.filter(pk=compania_id).first() if compania_id else None,
        "deposito_actual": Deposito.objects.filter(pk=deposito_id).first() if deposito_id else None,
    }
