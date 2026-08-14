"""Renders a datetime so the *browser's* local time and offset are shown
instead of the server's (UTC). See the JS in templates/base.html that
rewrites every [data-utc] element on page load using the visitor's own
clock - so someone at GMT+5:45 sees +5:45, someone at GMT-4 sees -4,
without the server needing to know who's asking.
"""

from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def local_time(value, empty='-'):
    """Usage: {% local_time some_datetime %}
    Renders a <time> element with a UTC fallback (for no-JS/crawlers)
    that base.html's script rewrites into the visitor's local time."""
    if not value:
        return empty
    iso = value.isoformat()
    fallback = value.strftime('%Y-%m-%d %H:%M')
    return format_html('<time data-utc="{}">{}</time>', iso, fallback)
