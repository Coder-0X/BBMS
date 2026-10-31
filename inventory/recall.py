# """
# Recall management — find all blood units linked to a donor or donation.

# Uses the UnitLineage DAG to traverse the full descendant tree.
# PostgreSQL recursive CTE for performance on large lineage graphs.
# """
# from django.db import connection
# from django.utils import timezone

# from inventory.state_machine import transition_unit
# from audit.utils import write_audit, create_signature


# def find_units_for_donation(donation_id: int) -> list[dict]:
#     """
#     Return all blood units derived from a donation, at any processing depth.
#     Uses recursive SQL for O(n) traversal instead of Python loops.
#     """
#     sql = """
#     WITH RECURSIVE lineage AS (
#         -- Seed: units directly from this donation
#         SELECT bu.id, bu.did, bu.status, bu.component_class, bu.abo_type, bu.rh_d_type,
#                bu.owner_branch_id, 1 AS depth
#         FROM inventory_bloodunit bu
#         WHERE bu.donation_id = %s

#         UNION ALL

#         -- Children derived from any unit in the lineage
#         SELECT bu.id, bu.did, bu.status, bu.component_class, bu.abo_type, bu.rh_d_type,
#                bu.owner_branch_id, l.depth + 1
#         FROM inventory_bloodunit bu
#         JOIN inventory_unitlineage ul ON ul.child_unit_id = bu.id
#         JOIN lineage l ON l.id = ul.parent_unit_id
#     )
#     SELECT DISTINCT id, did, status, component_class, abo_type, rh_d_type, owner_branch_id, depth
#     FROM lineage
#     ORDER BY depth, did
#     """
#     with connection.cursor() as cursor:
#         cursor.execute(sql, [donation_id])
#         cols = [d[0] for d in cursor.description]
#         return [dict(zip(cols, row)) for row in cursor.fetchall()]


# def find_units_for_donor(donor_id: int) -> list[dict]:
#     """Find all units from any donation by this donor."""
#     sql = """
#     WITH RECURSIVE lineage AS (
#         SELECT bu.id, bu.did, bu.status, bu.component_class, bu.abo_type, bu.rh_d_type,
#                bu.owner_branch_id, bu.donation_id, 1 AS depth
#         FROM inventory_bloodunit bu
#         JOIN donors_donation dd ON dd.id = bu.donation_id
#         WHERE dd.donor_id = %s

#         UNION ALL

#         SELECT bu.id, bu.did, bu.status, bu.component_class, bu.abo_type, bu.rh_d_type,
#                bu.owner_branch_id, bu.donation_id, l.depth + 1
#         FROM inventory_bloodunit bu
#         JOIN inventory_unitlineage ul ON ul.child_unit_id = bu.id
#         JOIN lineage l ON l.id = ul.parent_unit_id
#     )
#     SELECT DISTINCT id, did, status, component_class, abo_type, rh_d_type, owner_branch_id, donation_id, depth
#     FROM lineage
#     ORDER BY depth, did
#     """
#     with connection.cursor() as cursor:
#         cursor.execute(sql, [donor_id])
#         cols = [d[0] for d in cursor.description]
#         return [dict(zip(cols, row)) for row in cursor.fetchall()]


# def execute_recall(donation_id: int, actor, reason: str, reauth_at=None):
#     """
#     Recall all recallable units from a donation.
#     Units already transfused or destroyed are logged in the recall report but not touched.
#     Returns a summary dict.
#     """
#     from inventory.models import BloodUnit

#     units_data = find_units_for_donation(donation_id)
#     summary = {
#         'recalled': [],
#         'already_transfused': [],
#         'already_destroyed': [],
#         'already_recalled': [],
#         'errors': [],
#     }

#     esign = None
#     if reauth_at:
#         esign = create_signature(
#             signer=actor,
#             meaning='blood_recall',
#             payload_data={'donation_id': donation_id, 'reason': reason},
#             reauth_at=reauth_at,
#         )

#     for row in units_data:
#         unit_id = row['id']
#         try:
#             unit = BloodUnit.objects.select_for_update(nowait=True).get(pk=unit_id)
#         except Exception:
#             summary['errors'].append({'did': row['did'], 'error': 'Lock/fetch failed'})
#             continue

#         if unit.status in ('transfused',):
#             summary['already_transfused'].append(unit.did)
#             write_audit(actor=actor, action='recall.notify_transfused',
#                         entity_table='inventory_bloodunit', entity_id=unit.pk,
#                         after={'reason': reason})
#         elif unit.status == 'destroyed':
#             summary['already_destroyed'].append(unit.did)
#         elif unit.status == 'recalled':
#             summary['already_recalled'].append(unit.did)
#         else:
#             try:
#                 transition_unit(unit, 'recalled', actor, reason=f"RECALL: {reason}", esign=esign)
#                 summary['recalled'].append(unit.did)
#             except Exception as e:
#                 summary['errors'].append({'did': unit.did, 'error': str(e)})

#     write_audit(
#         actor=actor,
#         action='recall.execute',
#         entity_table='donors_donation',
#         entity_id=donation_id,
#         after=summary,
#         action_meaning=f"Recall of donation #{donation_id}: {len(summary['recalled'])} units recalled.",
#     )
#     return summary
"""
Recall management — find all blood units linked to a donor or donation.

Uses UnitLineage DAG + PostgreSQL recursive CTE for performance.
Ensures safe batch locking + atomic recall execution.
"""

from django.db import connection, transaction
from django.utils import timezone

from inventory.state_machine import transition_unit
from audit.utils import write_audit, create_signature


# -----------------------------
# LINEAGE QUERIES
# -----------------------------

def find_units_for_donation(donation_id: int) -> list[dict]:
    sql = """
    WITH RECURSIVE lineage AS (
        SELECT bu.id, bu.did, bu.status, bu.component_class, bu.abo_type, bu.rh_d_type,
               bu.owner_branch_id, 1 AS depth
        FROM inventory_bloodunit bu
        WHERE bu.donation_id = %s

        UNION ALL

        SELECT bu.id, bu.did, bu.status, bu.component_class, bu.abo_type, bu.rh_d_type,
               bu.owner_branch_id, l.depth + 1
        FROM inventory_bloodunit bu
        JOIN inventory_unitlineage ul ON ul.child_unit_id = bu.id
        JOIN lineage l ON l.id = ul.parent_unit_id
    )
    SELECT DISTINCT id, did, status, component_class, abo_type, rh_d_type, owner_branch_id, depth
    FROM lineage
    ORDER BY depth, did
    """

    with connection.cursor() as cursor:
        cursor.execute(sql, [donation_id])
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def find_units_for_donor(donor_id: int) -> list[dict]:
    sql = """
    WITH RECURSIVE lineage AS (
        SELECT bu.id, bu.did, bu.status, bu.component_class, bu.abo_type, bu.rh_d_type,
               bu.owner_branch_id, bu.donation_id, 1 AS depth
        FROM inventory_bloodunit bu
        JOIN donors_donation dd ON dd.id = bu.donation_id
        WHERE dd.donor_id = %s

        UNION ALL

        SELECT bu.id, bu.did, bu.status, bu.component_class, bu.abo_type, bu.rh_d_type,
               bu.owner_branch_id, bu.donation_id, l.depth + 1
        FROM inventory_bloodunit bu
        JOIN inventory_unitlineage ul ON ul.child_unit_id = bu.id
        JOIN lineage l ON l.id = ul.parent_unit_id
    )
    SELECT DISTINCT id, did, status, component_class, abo_type, rh_d_type, owner_branch_id, donation_id, depth
    FROM lineage
    ORDER BY depth, did
    """

    with connection.cursor() as cursor:
        cursor.execute(sql, [donor_id])
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


# -----------------------------
# CORE RECALL ENGINE
# -----------------------------

def execute_recall(donation_id: int, actor, reason: str, reauth_at=None):
    """
    Safe donor recall execution:
    - locks all affected units in batch
    - avoids per-row race conditions
    - handles partial states cleanly
    """

    from inventory.models import BloodUnit

    summary = {
        "recalled": [],
        "already_transfused": [],
        "already_destroyed": [],
        "already_recalled": [],
        "errors": [],
    }

    esign = None
    if reauth_at:
        esign = create_signature(
            signer=actor,
            meaning="blood_recall",
            payload_data={"donation_id": donation_id, "reason": reason},
            reauth_at=reauth_at,
        )

    with transaction.atomic():

        # 1. Get lineage (outside lock scope is OK)
        units_data = find_units_for_donation(donation_id)

        unit_ids = [u["id"] for u in units_data]

        # 2. Batch lock ALL units (fixes your Lock/fetch failure issue)
        locked_units = (
            BloodUnit.objects
            .select_for_update(skip_locked=True)
            .filter(id__in=unit_ids)
            .order_by("id")
        )

        unit_map = {u.id: u for u in locked_units}

        # 3. Process lineage rows safely
        for row in units_data:
            unit = unit_map.get(row["id"])

            # If unit couldn't be locked
            if not unit:
                summary["errors"].append({
                    "did": row["did"],
                    "error": "Unit currently locked by another process (skip_locked)"
                })
                continue

            # 4. Handle terminal / special states
            if unit.status == "transfused":
                summary["already_transfused"].append(unit.did)
                write_audit(
                    actor=actor,
                    action="recall.notify_transfused",
                    entity_table="inventory_bloodunit",
                    entity_id=unit.pk,
                    after={"reason": reason},
                )
                continue

            if unit.status == "destroyed":
                summary["already_destroyed"].append(unit.did)
                continue

            if unit.status == "recalled":
                summary["already_recalled"].append(unit.did)
                continue

            # 5. Perform recall transition (safe state machine)
            try:
                transition_unit(
                    unit,
                    "recalled",
                    actor,
                    reason=f"RECALL: {reason}",
                    esign=esign,
                )
                summary["recalled"].append(unit.did)

            except Exception as e:
                summary["errors"].append({
                    "did": unit.did,
                    "error": str(e)
                })

        # 6. Final audit log
        write_audit(
            actor=actor,
            action="recall.execute",
            entity_table="donors_donation",
            entity_id=donation_id,
            after=summary,
            action_meaning=(
                f"Recall of donation #{donation_id}: "
                f"{len(summary['recalled'])} units recalled."
            ),
        )

    return summary