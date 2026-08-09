from core.access import get_staff_role
from core.choices import (
    ROLE_ADMIN,
    ROLE_BOOTH,
    ROLE_INVENTORY,
    ROLE_LAB,
    ROLE_TRANSFUSION,
)


def staff_role(request):
    """Expose the logged-in user's role to every template, plus simple
    per-section booleans so the nav (and any screen) can hide links the
    current user has no access to instead of dead-ending in a 403."""
    user = getattr(request, 'user', None)
    role = get_staff_role(user) if user else None
    is_admin = role == ROLE_ADMIN
    return {
        'staff_role': role,
        'staff_role_display': dict(
            [
                (ROLE_BOOTH, 'Booth Staff'),
                (ROLE_LAB, 'Lab Staff'),
                (ROLE_INVENTORY, 'Inventory Staff'),
                (ROLE_TRANSFUSION, 'Transfusion Staff'),
                (ROLE_ADMIN, 'Admin'),
            ]
        ).get(role),
        'can_access_booth': is_admin or role == ROLE_BOOTH,
        'can_access_lab': is_admin or role == ROLE_LAB,
        'can_access_inventory': is_admin or role == ROLE_INVENTORY,
        'can_access_transfusion': is_admin or role == ROLE_TRANSFUSION,
        'can_view_crossmatches': is_admin or role in (ROLE_LAB, ROLE_TRANSFUSION),
        'can_access_staff': is_admin,
    }
