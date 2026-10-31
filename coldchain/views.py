from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.core.paginator import Paginator

from .models import StorageEquipment, TemperatureExcursion, UnitReturnCheck, EquipmentAlarm
from audit.utils import write_audit, create_signature
from inventory.state_machine import transition_unit


@login_required
def equipment_list(request):
    branch_id = request.session.get('branch_id')
    equipment = StorageEquipment.objects.filter(
        branch_id=branch_id,
    ).select_related('sensor_health').exclude(status='decommissioned').order_by('name')
    return render(request, 'coldchain/equipment_list.html', {'equipment': equipment})


@login_required
def equipment_detail(request, pk):
    equip = get_object_or_404(StorageEquipment, pk=pk)
    recent_logs = equip.temperature_logs.order_by('-recorded_at')[:48]
    active_excursions = equip.excursions.filter(ended_at__isnull=True)
    active_alarms = equip.alarms.filter(cleared_at__isnull=True)
    return render(request, 'coldchain/equipment_detail.html', {
        'equip': equip,
        'recent_logs': recent_logs,
        'active_excursions': active_excursions,
        'active_alarms': active_alarms,
    })


@login_required
def excursion_list(request):
    branch_id = request.session.get('branch_id')
    qs = TemperatureExcursion.objects.filter(
        equipment__branch_id=branch_id,
    ).select_related('equipment', 'disposition_by').order_by('-started_at')

    status_filter = request.GET.get('status', '')
    if status_filter == 'ongoing':
        qs = qs.filter(ended_at__isnull=True)
    elif status_filter == 'resolved':
        qs = qs.filter(ended_at__isnull=False)

    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'coldchain/excursion_list.html', {
        'page_obj': page,
        'status_filter': status_filter,
    })


@login_required
def excursion_resolve(request, pk):
    """Mark an ongoing temperature excursion as resolved, record disposition."""
    excursion = get_object_or_404(TemperatureExcursion, pk=pk)
    if request.method == 'POST':
        disposition = request.POST.get('disposition', 'quarantine')
        justification = request.POST.get('justification', '').strip()

        excursion.ended_at      = timezone.now()
        excursion.disposition   = disposition
        excursion.disposition_by = request.user
        excursion.disposition_at = timezone.now()
        excursion.justification = justification
        excursion.save(update_fields=[
            'ended_at', 'disposition', 'disposition_by',
            'disposition_at', 'justification',
        ])

        # Close active alarms for this excursion
        EquipmentAlarm.objects.filter(
            excursion=excursion, cleared_at__isnull=True,
        ).update(cleared_at=timezone.now())

        write_audit(
            actor=request.user,
            action='excursion.resolve',
            entity_table='coldchain_temperatureexcursion',
            entity_id=excursion.pk,
            after={'disposition': disposition, 'justification': justification},
            branch=excursion.equipment.branch,
        )

        # Auto-quarantine or auto-discard affected units when disposition requires it
        if disposition in ('quarantine', 'discard'):
            from inventory.models import BloodUnit
            new_status = 'quarantined_holdback' if disposition == 'quarantine' else 'wasted'
            quarantined_count = 0
            for link in excursion.unit_links.select_related('blood_unit').all():
                unit = link.blood_unit
                if unit.status in ('available', 'reserved'):
                    try:
                        transition_unit(
                            unit, new_status, request.user,
                            reason=f"Temperature excursion #{excursion.pk} — disposition: {disposition}",
                        )
                        link.auto_quarantined = True
                        link.save(update_fields=['auto_quarantined'])
                        quarantined_count += 1
                    except Exception:
                        pass
            if quarantined_count:
                messages.warning(request,
                    f"{quarantined_count} unit(s) moved to '{new_status}' due to temperature excursion.")

        messages.success(request, f"Excursion resolved — disposition: {excursion.get_disposition_display()}.")
        return redirect('coldchain:excursion_list')

    affected_units = excursion.unit_links.select_related('blood_unit').all()
    return render(request, 'coldchain/excursion_resolve.html', {
        'excursion': excursion,
        'affected_units': affected_units,
        'dispositions': TemperatureExcursion.DISPOSITIONS,
    })


@login_required
def unit_return_check(request, issue_pk):
    """Record whether a blood unit returned from the ward can go back to stock."""
    from transfusion.models import IssueTransaction
    from inventory.models import BloodUnit

    issue = get_object_or_404(IssueTransaction, pk=issue_pk)
    unit  = issue.blood_unit

    # Check if already evaluated
    existing = UnitReturnCheck.objects.filter(issue=issue).first()

    if request.method == 'POST':
        returned_at_str = request.POST.get('returned_at', '').strip()
        try:
            returned_at = timezone.datetime.fromisoformat(returned_at_str.replace('T', ' '))
            returned_at = timezone.make_aware(returned_at) if timezone.is_naive(returned_at) else returned_at
        except (ValueError, TypeError):
            returned_at = timezone.now()

        minutes_out = int((returned_at - issue.issued_at).total_seconds() / 60)
        rule_applied = request.POST.get('rule_applied', '30_minute_rule')
        temp_str = request.POST.get('measured_return_temp_c', '').strip()
        measured_temp = temp_str if temp_str else None

        # Auto-determine decision based on 30-minute rule
        if rule_applied == '30_minute_rule':
            decision = 'return_to_stock' if minutes_out <= 30 else 'discard'
        else:
            # Validated temperature: must be 1–6 °C for RBC
            if measured_temp:
                try:
                    t = float(measured_temp)
                    component = unit.component_type if hasattr(unit, 'component_type') else ''
                    decision = 'return_to_stock' if 1.0 <= t <= 6.0 else 'discard'
                except ValueError:
                    decision = 'discard'
            else:
                decision = 'discard'

        # Allow manual override
        if 'override_decision' in request.POST:
            decision = request.POST['override_decision']

        esign = create_signature(
            signer=request.user,
            meaning='unit_return_check',
            payload_data={'issue_pk': issue_pk, 'unit_did': unit.did},
        )

        check = UnitReturnCheck.objects.create(
            blood_unit=unit,
            issue=issue,
            issued_at=issue.issued_at,
            returned_at=returned_at,
            minutes_out=minutes_out,
            measured_return_temp_c=measured_temp,
            rule_applied=rule_applied,
            decision=decision,
            decided_by=request.user,
            esign=esign,
        )

        # Transition the unit accordingly
        if decision == 'return_to_stock':
            try:
                transition_unit(unit, 'available', request.user, reason=f"Return check #{check.pk} — passed 30-min rule")
                messages.success(request, f"Unit {unit.did} cleared for return to stock ({minutes_out} min out).")
            except Exception as e:
                messages.warning(request, f"Unit status not updated automatically: {e}")
        else:
            try:
                transition_unit(unit, 'destroyed', request.user, reason=f"Return check #{check.pk} — {minutes_out} min out, exceeds 30 min rule / temp out of range")
                messages.warning(request, f"Unit {unit.did} must be DISCARDED — {minutes_out} min out of controlled storage.")
            except Exception as e:
                messages.warning(request, f"Unit discarded but status not updated automatically: {e}")

        write_audit(
            actor=request.user,
            action='unit.return_check',
            entity_table='coldchain_unitreturncheck',
            entity_id=check.pk,
            after={'unit_did': unit.did, 'minutes_out': minutes_out, 'decision': decision},
        )

        return redirect('transfusion:request_detail', pk=issue.request_id)

    return render(request, 'coldchain/unit_return_check.html', {
        'issue': issue,
        'unit':  unit,
        'existing': existing,
        'rules': UnitReturnCheck.RULES,
        'decisions': UnitReturnCheck.DECISIONS,
    })


@login_required
def return_check_list(request):
    """List recent unit return checks at this branch."""
    branch_id = request.session.get('branch_id')
    checks = UnitReturnCheck.objects.filter(
        issue__intended_branch_id=branch_id,
    ).select_related('blood_unit', 'decided_by', 'issue__request').order_by('-created_at')

    paginator = Paginator(checks, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'coldchain/return_check_list.html', {'page_obj': page})
