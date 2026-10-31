from django import template

register = template.Library()


@register.filter
def getattr_filter(obj, attr_name):
    """{{ obj|getattr_filter:"field_name" }} — get a named attribute dynamically."""
    return getattr(obj, attr_name, None)


# Register as 'getattr' so templates can use {{ existing|getattr:antigen }}
register.filter('getattr', getattr_filter)


@register.filter
def mul(value, arg):
    """{{ value|mul:arg }} — multiply value by arg."""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def div(value, arg):
    """{{ value|div:arg }} — divide value by arg, return 0 on error."""
    try:
        return float(value) / float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0


@register.filter
def pct(value, total):
    """{{ value|pct:total }} — percentage of total, 0 if total is 0."""
    try:
        return round(float(value) / float(total) * 100, 1)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0


@register.filter
def abs_filter(value):
    """{{ value|abs_filter }} — absolute value."""
    try:
        return abs(value)
    except (TypeError, ValueError):
        return value

register.filter('abs', abs_filter)
