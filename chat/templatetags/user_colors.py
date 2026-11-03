from django import template

from chat.colors import color_for

register = template.Library()


@register.filter
def user_color(user):
    return color_for(user)


@register.filter
def id_color(user_id):
    try:
        return color_for(int(user_id))
    except (TypeError, ValueError):
        return "#58a6ff"


@register.filter
def dict_get(d, key):
    if not isinstance(d, dict):
        return None
    return d.get(key)
