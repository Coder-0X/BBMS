def alert_count(request):
    """Inject unread alert count into every template context."""
    if not request.user.is_authenticated:
        return {'unread_alert_count': 0}
    from core.models import Alert
    branch_id = request.session.get('branch_id')
    if not branch_id:
        return {'unread_alert_count': 0}
    count = Alert.objects.filter(
        branch_id=branch_id,
        acknowledged_at__isnull=True,
    ).count()
    return {'unread_alert_count': count}
