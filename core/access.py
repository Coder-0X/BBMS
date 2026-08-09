"""Role-based access control.

Each app's CRUD views declare which staff roles may use them via
`allowed_roles` on RoleRequiredMixin. A Django superuser (or a staff
profile with role='Admin') always passes every check - everyone else
must have a StaffProfile whose role is in the view's allowed_roles list.

This is deliberately simple (no Django Groups/Permissions machinery)
because the whole app is already organised as "one role = one app", so
a flat role string is enough and is easy to reason about from the
templates too.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from core.choices import ROLE_ADMIN


def get_staff_role(user):
    """Return the role string for a logged-in user, or None if they
    have no staff profile (and aren't a superuser)."""
    if not getattr(user, 'is_authenticated', False):
        return None
    if user.is_superuser:
        return ROLE_ADMIN
    profile = getattr(user, 'staffprofile', None)
    return profile.role if profile else None


def user_has_role(user, allowed_roles):
    role = get_staff_role(user)
    if role == ROLE_ADMIN:
        return True
    return role in allowed_roles


class RoleRequiredMixin(LoginRequiredMixin):
    """Restrict a class-based view to specific staff roles.

    Set `allowed_roles = [ROLE_BOOTH, ...]` on the view. Admins and
    superusers always pass. Anyone else without a matching role gets a
    403 with a clear explanation instead of a confusing generic error.
    Not-logged-in users still get redirected to login as normal, since
    this builds on LoginRequiredMixin.
    """

    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not user_has_role(request.user, self.allowed_roles):
            raise PermissionDenied(
                'Your staff role does not have access to this section. '
                'Contact an administrator if you believe this is a mistake.'
            )
        return super(LoginRequiredMixin, self).dispatch(request, *args, **kwargs)
