from django import template

register = template.Library()


@register.filter
def valor_campo(obj, nombre):
    """Lee `obj.nombre`, o `obj.get_<nombre>_display()` si es un campo de
    choices — usado por las plantillas genéricas de datos maestros
    (`master_list.html`) para mostrar columnas arbitrarias sin una plantilla
    a mano por modelo."""
    display_fn = getattr(obj, f"get_{nombre}_display", None)
    if callable(display_fn):
        return display_fn()
    return getattr(obj, nombre, "")
