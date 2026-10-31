from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone
from datetime import timedelta


class SessionTimeoutMiddleware:
    """
    Enforces idle and absolute session timeouts.
    Idle timeout: no activity for N minutes → logout.
    Absolute timeout: session older than N minutes → logout regardless of activity.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            now = timezone.now()
            idle_minutes = getattr(settings, 'SESSION_IDLE_TIMEOUT', 30)
            absolute_minutes = getattr(settings, 'SESSION_ABSOLUTE_TIMEOUT', 480)

            last_activity = request.session.get('last_activity')
            session_start = request.session.get('session_start')

            if last_activity:
                idle_limit = timezone.datetime.fromisoformat(last_activity) + timedelta(minutes=idle_minutes)
                if now > idle_limit:
                    logout(request)
                    return redirect(settings.LOGIN_URL + '?reason=idle')

            if session_start:
                absolute_limit = timezone.datetime.fromisoformat(session_start) + timedelta(minutes=absolute_minutes)
                if now > absolute_limit:
                    logout(request)
                    return redirect(settings.LOGIN_URL + '?reason=expired')

            request.session['last_activity'] = now.isoformat()
            if not session_start:
                request.session['session_start'] = now.isoformat()

        return self.get_response(request)
