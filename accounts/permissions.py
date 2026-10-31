"""
Check whether a user holds a given permission code at a given branch.
Usage: has_permission(request.user, 'unit.release', branch)
"""
from django.core.cache import cache
from .models import UserRole, SoDConflict


def _branch_id(branch):
    """Normalise branch to an integer PK (accepts Branch object or int or None)."""
    if branch is None:
        return None
    if isinstance(branch, int):
        return branch
    return branch.pk


def get_user_permissions(user, branch=None) -> set[str]:
    """
    Return the set of permission codes a user has at the given branch.
    `branch` may be a Branch model instance, an integer PK, or None (all-branch grants).
    Caches per user+branch for 60 seconds to avoid hammering the DB on every request.
    """
    bid = _branch_id(branch)
    cache_key = f"perms:{user.pk}:{bid if bid is not None else 'all'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    grants = UserRole.objects.filter(
        user=user,
        revoked_at__isnull=True,
        branch_id=bid,
    ) | UserRole.objects.filter(
        user=user,
        revoked_at__isnull=True,
        branch__isnull=True,
    )

    codes = set()
    for grant in grants.prefetch_related('role__permissions'):
        for perm in grant.role.permissions.all():
            codes.add(perm.code)

    cache.set(cache_key, codes, 60)
    return codes


def has_permission(user, code: str, branch=None) -> bool:
    if not user or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return code in get_user_permissions(user, branch)


def invalidate_permission_cache(user, branch=None):
    bid = _branch_id(branch)
    cache_key = f"perms:{user.pk}:{bid if bid is not None else 'all'}"
    cache.delete(cache_key)


def check_sod_violation(user, new_permission_code: str, branch=None) -> str | None:
    """
    Returns a human-readable conflict description if granting new_permission_code
    to this user would violate a SoD rule. Returns None if it's fine.
    """
    current_perms = get_user_permissions(user, branch)
    conflicts = SoDConflict.objects.filter(
        permission_a__code=new_permission_code
    ) | SoDConflict.objects.filter(
        permission_b__code=new_permission_code
    )
    for conflict in conflicts:
        other = (
            conflict.permission_b.code
            if conflict.permission_a.code == new_permission_code
            else conflict.permission_a.code
        )
        if other in current_perms:
            return conflict.reason
    return None
