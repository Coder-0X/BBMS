import threading

_thread_locals = threading.local()


def get_current_user():
    return getattr(_thread_locals, 'user', None)


def get_current_ip():
    return getattr(_thread_locals, 'ip_address', None)


def set_current_user(user):
    _thread_locals.user = user


def set_current_ip(ip):
    _thread_locals.ip_address = ip


class AuditMiddleware:
    """Middleware that stores the authenticated user and remote IP in
    thread-local storage so that model post_save/post_delete signals can
    automatically attribute audit log entries to the user who triggered them.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        if settings.DEBUG and request.GET.get('as_user'):
            from django.contrib.auth import login
            from django.contrib.auth.models import User
            try:
                target_user = User.objects.get(username=request.GET['as_user'])
                login(request, target_user)
            except Exception:
                pass

        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            set_current_user(user)
        else:
            set_current_user(None)

        # Extract client IP address
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        set_current_ip(ip)

        try:
            response = self.get_response(request)
        finally:
            set_current_user(None)
            set_current_ip(None)

        return response
