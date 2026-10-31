"""
Stores the current request's user in a thread-local so that audit helpers
can access it without needing the request object passed everywhere.
"""
import threading

_local = threading.local()


class AuditUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.current_user = request.user if request.user.is_authenticated else None
        _local.current_branch = getattr(request.user, 'branch', None)
        response = self.get_response(request)
        _local.current_user = None
        _local.current_branch = None
        return response


def get_current_user():
    return getattr(_local, 'current_user', None)


def get_current_branch():
    return getattr(_local, 'current_branch', None)
