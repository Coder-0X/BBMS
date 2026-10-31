from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone
from django.http import HttpResponse

from .models import BloodUnit, ComponentType, ProcessingEvent, Transfer, COMPONENT_CLASSES, WastageRecord, UnitLineage
from .state_machine import transition_unit
from .create_units import create_units_from_whole_blood, create_apheresis_units
from .labels import print_label
from accounts.permissions import has_permission
from audit.utils import write_audit
from core.models import RefFacility


@login_required
def unit_detail(request, did):
    unit = get_object_or_404(BloodUnit, did=did)
    return render(request, 'inventory/unit_detail.html', {
        'unit': unit,
        'events': unit.status_events.order_by('-occurred_at')[:20],
        'crossmatches': unit.crossmatches.all(),
    })


@login_required
def unit_list(request):
    branch_id = request.session.get('branch_id')
    units = BloodUnit.objects.filter(owner_branch_id=branch_id).order_by('-created_at')

    status_filter    = request.GET.get('status', '')
    abo_filter       = request.GET.get('abo', '')
    rh_filter        = request.GET.get('rh', '')
    component_filter = request.GET.get('component', '')
    near_expiry      = request.GET.get('near_expiry', '')
    q = request.GET.get('q', '').strip()

    if status_filter:
        units = units.filter(status=status_filter)
    if abo_filter:
        units = units.filter(abo_type=abo_filter)
    if rh_filter:
        units = units.filter(rh_d_type=rh_filter)
    if component_filter:
        units = units.filter(component_class=component_filter)
    if near_expiry:
        try:
            near_expiry_hours = int(near_expiry)
        except (ValueError, TypeError):
            near_expiry_hours = 72
        from datetime import timedelta as _td
        cutoff = timezone.now() + _td(hours=near_expiry_hours)
        units = units.filter(expiry_datetime__lte=cutoff, status='available')
    if q:
        units = units.filter(did__icontains=q)
    ungrouped_filter = request.GET.get('ungrouped', '')
    if ungrouped_filter:
        units = units.filter(abo_type='')

    paginator = Paginator(units, 30)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'inventory/unit_list.html', {
        'page_obj': page,
        'units': page.object_list,
        'status_filter': status_filter,
        'abo_filter': abo_filter,
        'rh_filter': rh_filter,
        'component_filter': component_filter,
        'near_expiry': near_expiry,
        'q': q,
        'ungrouped_filter': ungrouped_filter,
        'component_classes': COMPONENT_CLASSES,
    })


@login_required
def record_processing(request, did):
    unit = get_object_or_404(BloodUnit, did=did)
    if not has_permission(request.user, 'unit.process', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('inventory:unit_detail', did=did)

    if request.method == 'POST':
        proc_type = request.POST['processing_type']
        ProcessingEvent.objects.create(
            event_type=proc_type,
            performed_by=request.user,
            performed_at=timezone.now(),
            branch_id=request.session.get('branch_id'),
            blood_unit=unit,
            sop_version=request.POST.get('sop_version', '1.0'),
            notes=request.POST.get('notes', ''),
        )
        # Update unit attributes based on processing type
        fields_to_update = []
        if proc_type == 'leukoreduction':
            unit.is_leukoreduced = True
            fields_to_update.append('is_leukoreduced')
        elif proc_type == 'irradiation':
            unit.is_irradiated = True
            fields_to_update.append('is_irradiated')
        elif proc_type == 'washing':
            unit.is_washed = True
            fields_to_update.append('is_washed')
        elif proc_type == 'cmv_testing':
            unit.is_cmv_negative = request.POST.get('cmv_result') == 'negative'
            fields_to_update.append('is_cmv_negative')
        if fields_to_update:
            unit.save(update_fields=fields_to_update)
        write_audit(
            actor=request.user,
            action='unit.processing',
            entity_table='inventory_bloodunit',
            entity_id=unit.pk,
            after={'processing_type': proc_type, 'unit_did': unit.did,
                   'sop_version': request.POST.get('sop_version', '1.0')},
            branch=unit.owner_branch,
        )
        messages.success(request, f"Processing event '{proc_type}' recorded.")
        return redirect('inventory:unit_detail', did=did)
    return render(request, 'inventory/record_processing.html', {'unit': unit})


@login_required
def change_unit_status(request, did):
    unit = get_object_or_404(BloodUnit, did=did)
    if not has_permission(request.user, 'unit.reserve', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('inventory:unit_detail', did=did)

    if request.method == 'POST':
        new_status = request.POST['new_status']
        reason = request.POST.get('reason', '')
        try:
            transition_unit(unit, new_status, request.user, reason=reason)
            messages.success(request, f"Unit status changed to {new_status}.")
        except Exception as e:
            messages.error(request, str(e))
        return redirect('inventory:unit_detail', did=did)
    return render(request, 'inventory/change_status.html', {'unit': unit})


@login_required
def initiate_transfer(request, did):
    unit = get_object_or_404(BloodUnit, did=did)
    if not has_permission(request.user, 'transfer.send', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('inventory:unit_detail', did=did)

    if request.method == 'POST':
        from core.models import Branch
        try:
            to_branch_id_val = int(request.POST.get('to_branch_id', ''))
        except (ValueError, TypeError):
            messages.error(request, "Invalid branch selection.")
            return redirect('inventory:unit_detail', did=did)
        to_branch = get_object_or_404(Branch, pk=to_branch_id_val)
        transfer = Transfer.objects.create(
            blood_unit=unit,
            from_branch=unit.owner_branch,
            to_branch=to_branch,
            initiated_by=request.user,
            status='requested',
            reason=request.POST.get('notes', ''),
        )
        transition_unit(unit, 'transferred_out', request.user,
                        reason=f"Transfer #{transfer.pk} to {to_branch.name}")
        write_audit(
            actor=request.user,
            action='transfer.initiate',
            entity_table='inventory_transfer',
            entity_id=transfer.pk,
            after={'unit_did': unit.did, 'to_branch': to_branch.name, 'reason': transfer.reason},
            branch=unit.owner_branch,
        )
        messages.success(request, f"Transfer #{transfer.pk} initiated.")
        return redirect('inventory:unit_detail', did=did)
    from core.models import Branch
    branches = Branch.objects.exclude(pk=unit.owner_branch_id)
    return render(request, 'inventory/initiate_transfer.html', {'unit': unit, 'branches': branches})


@login_required
def separate_components(request, donation_id):
    """
    Create blood units from a donation.

    Whole blood: two mutually exclusive paths —
      (A) Store intact as fresh whole blood (WB-FRH) — one unit, or
      (B) Separate into up to 3 primary components: RBC + FFP + PLT.
          Platelets are optional (requires platelet-rich plasma method).
          Cryoprecipitate is derived from FFP — select only if cryo processing is planned.
    Apheresis: yields exactly the component(s) collected by the apheresis machine.
    """
    from donors.models import Donation
    from core.models import Branch
    donation = get_object_or_404(Donation, pk=donation_id)

    if donation.units.exists():
        messages.warning(request,
            f"Components have already been separated from Donation #{donation.pk}. "
            f"{donation.units.count()} unit(s) exist.")
        return redirect('donors:detail', pk=donation.donor_id)

    if request.method == 'POST':
        branch = get_object_or_404(Branch, pk=request.session.get('branch_id'))
        component_codes = request.POST.getlist('component_codes')
        donation_type = donation.donation_type

        if not component_codes:
            messages.error(request, "Select at least one component type.")
            return redirect('inventory:separate_components', donation_id=donation_id)

        # Enforce whole-blood mutual exclusivity: WB vs separated components
        if donation_type == 'whole_blood':
            wb_codes = {c for c in component_codes if c.startswith('WB-')}
            non_wb_codes = {c for c in component_codes if not c.startswith('WB-')}
            if wb_codes and non_wb_codes:
                messages.error(request,
                    "Whole blood (WB) storage and component separation are mutually exclusive. "
                    "Either store the donation as whole blood OR separate into components — not both.")
                return redirect('inventory:separate_components', donation_id=donation_id)

            # Validate allowed classes for separated path
            if non_wb_codes:
                components_qs = ComponentType.objects.filter(code__in=non_wb_codes)
                for comp in components_qs:
                    if comp.component_class not in ('RBC', 'FFP', 'PLT', 'CRYO'):
                        messages.error(request,
                            f"{comp.code} ({comp.component_class}) cannot be derived from a whole blood donation.")
                        return redirect('inventory:separate_components', donation_id=donation_id)
                # CRYO requires FFP to also be selected (derived from it)
                cryo_codes = [c for c in non_wb_codes if c.startswith('CRYO')]
                ffp_codes  = [c for c in non_wb_codes if c.startswith('FFP')]
                if cryo_codes and not ffp_codes:
                    messages.error(request,
                        "Cryoprecipitate (CRYO) is derived from Fresh Frozen Plasma. "
                        "Please also select an FFP component, or select only CRYO if plasma has already been processed.")

        try:
            if donation_type == 'whole_blood':
                units = create_units_from_whole_blood(donation, component_codes, request.user, branch)
            else:
                units = create_apheresis_units(donation, component_codes, request.user, branch)
        except RefFacility.DoesNotExist:
            messages.error(request, "This branch has no facility code configured. Contact your administrator before separating components.")
            return redirect('inventory:separate_components', donation_id=donation_id)

        messages.success(request, f"{len(units)} blood unit(s) created: {', '.join(u.did for u in units)}")
        return redirect('donors:detail', pk=donation.donor_id)

    # Build component lists per donation type
    if donation.donation_type == 'whole_blood':
        # Primary separation path: RBC, FFP, PLT, CRYO
        separated_components = ComponentType.objects.filter(
            component_class__in=['RBC', 'FFP', 'PLT', 'CRYO']
        ).order_by('component_class', 'code')
        # Whole blood storage path
        whole_blood_components = ComponentType.objects.filter(
            component_class='WB'
        ).order_by('code')
    else:
        separated_components = ComponentType.objects.filter(
            component_class__in=['PLT', 'FFP', 'GRAN', 'RBC']
        ).order_by('component_class', 'code')
        whole_blood_components = ComponentType.objects.none()

    return render(request, 'inventory/separate_components.html', {
        'donation': donation,
        'separated_components': separated_components,
        'whole_blood_components': whole_blood_components,
        'is_whole_blood': donation.donation_type == 'whole_blood',
    })


@login_required
def print_label_view(request, did):
    unit = get_object_or_404(BloodUnit, did=did)
    label_data = print_label(unit, request.user)
    return render(request, 'inventory/label.html', {'unit': unit, 'label': label_data})


@login_required
def cross_site_request(request):
    """Request blood units from another branch."""
    from .cross_site import create_cross_site_request, CrossSiteRequestError
    from core.models import Branch
    branch_id = request.session.get('branch_id')
    my_branch = get_object_or_404(Branch, pk=branch_id)
    other_branches = Branch.objects.filter(active=True).exclude(pk=branch_id)

    if request.method == 'POST':
        try:
            units_needed = int(request.POST.get('units_needed', 1))
        except (ValueError, TypeError):
            units_needed = 1
        try:
            try:
                fulfilling_branch_id_val = int(request.POST.get('fulfilling_branch_id', ''))
            except (ValueError, TypeError):
                messages.error(request, "Invalid branch selection.")
                return redirect('inventory:pending_transfers')
            fulfilling_branch = get_object_or_404(Branch, pk=fulfilling_branch_id_val)
            transfers = create_cross_site_request(
                requesting_branch=my_branch,
                fulfilling_branch=fulfilling_branch,
                component_class=request.POST['component_class'],
                abo_type=request.POST['abo_type'],
                rh_d_type=request.POST['rh_d_type'],
                units_needed=units_needed,
                reason=request.POST['reason'],
                actor=request.user,
            )
            messages.success(request, f"{len(transfers)} unit(s) arranged for transfer from {fulfilling_branch.name}.")
        except CrossSiteRequestError as e:
            messages.error(request, str(e))
        return redirect('inventory:pending_transfers')

    return render(request, 'inventory/cross_site_request.html', {
        'my_branch': my_branch,
        'branches': other_branches,
        'component_classes': COMPONENT_CLASSES,
    })


@login_required
def export_unit_pil(request, did):
    """Generate and download a Product Information Leaflet PDF for a blood unit."""
    from django.http import HttpResponse
    from core.pdf_reports import render_unit_pil_pdf
    unit = get_object_or_404(BloodUnit, did=did)
    branch_name = unit.owner_branch.name if unit.owner_branch else 'Unknown'
    pdf_bytes = render_unit_pil_pdf(unit, branch_name)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="PIL_{unit.did}.pdf"'
    return response


@login_required
def pending_transfers(request):
    """List incoming transfers awaiting acceptance at this branch."""
    branch_id = request.session.get('branch_id')
    transfers = Transfer.objects.filter(
        to_branch_id=branch_id, status='requested'
    ).select_related('blood_unit', 'from_branch', 'initiated_by').order_by('-initiated_at')

    paginator = Paginator(transfers, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'inventory/pending_transfers.html', {'page_obj': page})


@login_required
def receive_transfer(request, transfer_pk):
    """Accept or reject an incoming transfer."""
    branch_id = request.session.get('branch_id')
    transfer = get_object_or_404(Transfer, pk=transfer_pk, to_branch_id=branch_id, status='requested')

    if not has_permission(request.user, 'transfer.receive', branch_id):
        messages.error(request, "Permission denied.")
        return redirect('inventory:pending_transfers')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'accept':
            transfer.status = 'received'
            transfer.received_by = request.user
            transfer.received_at = timezone.now()
            transfer.save(update_fields=['status', 'received_by', 'received_at'])

            unit = transfer.blood_unit
            unit.owner_branch = transfer.to_branch
            unit.save(update_fields=['owner_branch'])
            transition_unit(unit, 'available', request.user,
                            reason=f"Transfer #{transfer.pk} received from {transfer.from_branch.name}")

            write_audit(
                actor=request.user,
                action='transfer.received',
                entity_table='inventory_transfer',
                entity_id=transfer.pk,
                after={'status': 'received', 'unit_did': unit.did},
            )
            messages.success(request, f"Transfer received — unit {unit.did} is now in your inventory.")
        elif action == 'reject':
            reason = request.POST.get('reason', 'Rejected at destination')
            transfer.status = 'rejected'
            transfer.save(update_fields=['status'])
            transition_unit(transfer.blood_unit, 'available', request.user,
                            reason=f"Transfer #{transfer.pk} rejected: {reason}")
            write_audit(
                actor=request.user,
                action='transfer.rejected',
                entity_table='inventory_transfer',
                entity_id=transfer.pk,
                after={'status': 'rejected', 'reason': reason},
            )
            messages.warning(request, "Transfer rejected. Unit returned to available at origin branch.")
        return redirect('inventory:pending_transfers')

    return render(request, 'inventory/receive_transfer.html', {'transfer': transfer})


@login_required
def record_wastage(request, did):
    """Mark a blood unit as wasted and optionally proceed to destroyed."""
    unit = get_object_or_404(BloodUnit, did=did)
    branch_id = request.session.get('branch_id')

    WASTAGE_REASONS = [
        ('expired_unused', 'Expired — unused'),
        ('damaged_container', 'Damaged / container breach'),
        ('temperature_excursion', 'Temperature excursion'),
        ('positive_tti', 'Reactive TTI result (post-issue)'),
        ('returned_contaminated', 'Returned — suspected contamination'),
        ('segment_mismatch', 'Segment mismatch'),
        ('other', 'Other (specify in notes)'),
    ]

    # Allow wasting from: available, reserved, crossmatched, returned_to_stock
    wasteable_statuses = {'available', 'reserved', 'crossmatched', 'returned_to_stock', 'issued'}
    if unit.status not in wasteable_statuses:
        messages.error(request, f"Unit {unit.did} cannot be wasted from status '{unit.status}'.")
        return redirect('inventory:unit_detail', did=did)

    if request.method == 'POST':
        reason_code  = request.POST.get('reason_code', 'other')
        notes        = request.POST.get('notes', '').strip()
        also_destroy = request.POST.get('also_destroy') == '1'
        avoidable    = request.POST.get('avoidable', '')
        value_str    = request.POST.get('value_gbp', '').strip()

        reason_label = dict(WastageRecord.REASONS).get(reason_code, reason_code)
        full_reason  = f"Wastage: {reason_label}. {notes}".strip('. ')

        from django.db import transaction as db_tx
        with db_tx.atomic():
            transition_unit(unit, 'wasted', request.user, reason=full_reason)
            final_status = 'wasted'
            if also_destroy:
                transition_unit(unit, 'destroyed', request.user, reason='Disposed after wastage.')
                final_status = 'destroyed'

            wastage = WastageRecord.objects.create(
                blood_unit=unit,
                reason_code=reason_code,
                final_status=final_status,
                notes=notes,
                avoidable=True if avoidable == 'yes' else (False if avoidable == 'no' else None),
                value_gbp=value_str if value_str else None,
                recorded_by=request.user,
                branch_id=branch_id,
            )
            write_audit(
                actor=request.user,
                action='unit.wasted',
                entity_table='inventory_wastagerecord',
                entity_id=wastage.pk,
                after={'unit_did': unit.did, 'reason_code': reason_code,
                       'final_status': final_status, 'value_gbp': value_str or None},
                branch=unit.owner_branch,
            )

        messages.success(
            request,
            f"Unit {unit.did} marked as {'destroyed' if also_destroy else 'wasted'}. Wastage record created."
        )
        return redirect('inventory:unit_detail', did=did)

    return render(request, 'inventory/record_wastage.html', {
        'unit':           unit,
        'wastage_reasons': WastageRecord.REASONS,
    })


@login_required
def wastage_report(request):
    """Wastage analytics — reason breakdown, avoidability, value loss."""
    from django.db.models import Count, Sum, Q
    from datetime import timedelta

    branch_id = request.session.get('branch_id')
    try:
        days = int(request.GET.get('days', 30))
    except (ValueError, TypeError):
        days = 30
    cutoff = timezone.now() - timedelta(days=days)

    qs = WastageRecord.objects.filter(
        branch_id=branch_id,
        recorded_at__gte=cutoff,
    )

    total   = qs.count()
    by_reason = list(qs.values('reason_code').annotate(count=Count('pk'), value=Sum('value_gbp')).order_by('-count'))
    avoidable_count = qs.filter(avoidable=True).count()
    total_value = qs.aggregate(v=Sum('value_gbp'))['v'] or 0

    reason_labels = dict(WastageRecord.REASONS)
    for row in by_reason:
        row['label'] = reason_labels.get(row['reason_code'], row['reason_code'])

    recent = qs.select_related('blood_unit', 'recorded_by').order_by('-recorded_at')[:20]

    return render(request, 'inventory/wastage_report.html', {
        'days':             days,
        'total':            total,
        'by_reason':        by_reason,
        'avoidable_count':  avoidable_count,
        'total_value':      total_value,
        'recent':           recent,
    })


@login_required
def irradiate_unit(request, did):
    """
    Record irradiation of a blood unit.

    Creates a ProcessingEvent(type='irradiation') and sets:
      - unit.is_irradiated = True
      - unit.irradiation_datetime = now

    BCSH / JPAC requirements:
      - Dose 25–50 Gy (minimum 25 Gy, maximum 50 Gy to any point)
      - Equipment must be validated; dose checked with dosimetry card
      - Unit re-labelled with irradiation date and expiry (reduced to 14 days for RBC post-irradiation)
      - Mandatory for immunocompromised, neonates, directed donations from relatives, HLA-matched products
    """
    unit = get_object_or_404(BloodUnit, did=did)
    branch_id = request.session.get('branch_id')

    if unit.is_irradiated:
        messages.warning(request, f"Unit {did} is already irradiated (irradiated at {unit.irradiation_datetime:%Y-%m-%d %H:%M}).")
        return redirect('inventory:unit_detail', did=did)

    if unit.status not in ('available', 'quarantined', 'reserved'):
        messages.error(request, f"Cannot irradiate a unit with status '{unit.status}'.")
        return redirect('inventory:unit_detail', did=did)

    if request.method == 'POST':
        dose_gy_str  = request.POST.get('dose_gy', '').strip()
        equipment_id = request.POST.get('equipment_id', '').strip()
        dosimetry_card_ok = request.POST.get('dosimetry_card_ok') == '1'
        sop_version  = request.POST.get('sop_version', '').strip()
        notes        = request.POST.get('notes', '').strip()

        errors = []
        if not dose_gy_str:
            errors.append("Dose (Gy) is required.")
        else:
            try:
                dose_gy = float(dose_gy_str)
                if dose_gy < 25:
                    errors.append("Dose must be ≥ 25 Gy (BCSH minimum).")
                elif dose_gy > 50:
                    errors.append("Dose must not exceed 50 Gy (BCSH maximum).")
            except ValueError:
                errors.append("Dose must be a number.")
                dose_gy = None
        if not dosimetry_card_ok:
            errors.append("Dosimetry card check must be confirmed.")
        if not sop_version:
            errors.append("SOP version is required.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'inventory/irradiate_unit.html', {
                'unit': unit,
                'dose_gy': dose_gy_str,
                'equipment_id': equipment_id,
                'sop_version': sop_version,
                'notes': notes,
            })

        from audit.utils import create_signature
        from core.models import Branch
        branch = Branch.objects.filter(pk=branch_id).first() if branch_id else Branch.objects.first()
        if not branch:
            messages.error(request, "Branch not found. Please re-select your branch.")
            return redirect('core:select_branch')

        now = timezone.now()

        # Create the processing event record
        event = ProcessingEvent.objects.create(
            event_type='irradiation',
            performed_at=now,
            performed_by=request.user,
            branch=branch,
            sop_version=sop_version,
            notes=f"Dose: {dose_gy} Gy. Equipment: {equipment_id or 'not recorded'}. {notes}".strip(),
        )

        # Sign the irradiation event
        esign = create_signature(
            signer=request.user,
            meaning='irradiation_record',
            payload_data={
                'unit_did': unit.did,
                'dose_gy': dose_gy,
                'equipment_id': equipment_id,
                'processing_event_pk': event.pk,
                'sop_version': sop_version,
            },
        )
        event.esign = esign
        event.save(update_fields=['esign'])

        # Update the unit
        unit.is_irradiated = True
        unit.irradiation_datetime = now

        # BCSH: irradiated RBC must be transfused within 14 days of irradiation OR original expiry, whichever is sooner
        if unit.component_class == 'RBC' and unit.expiry_datetime:
            from datetime import timedelta as _td
            irrad_expiry = now + _td(days=14)
            if irrad_expiry < unit.expiry_datetime:
                unit.expiry_datetime = irrad_expiry
                messages.info(request, "Expiry reduced to 14 days post-irradiation (BCSH RBC rule).")

        unit.save(update_fields=['is_irradiated', 'irradiation_datetime', 'expiry_datetime'])

        write_audit(
            actor=request.user,
            action='unit.irradiated',
            entity_table='inventory_bloodunit',
            entity_id=unit.pk,
            after={
                'dose_gy': dose_gy,
                'equipment_id': equipment_id,
                'irradiation_datetime': str(now),
                'sop_version': sop_version,
                'processing_event_pk': event.pk,
            },
            branch=branch,
        )

        messages.success(request, f"Unit {did} irradiated ({dose_gy} Gy). Event recorded and signed.")
        return redirect('inventory:unit_detail', did=did)

    return render(request, 'inventory/irradiate_unit.html', {
        'unit': unit,
        'dose_gy': '',
        'equipment_id': '',
        'sop_version': '',
        'notes': '',
    })


@login_required
def antigen_match_search(request):
    """
    Find ABO-compatible, antigen-negative units for a patient with
    known antibodies and/or an extended phenotype on file.

    Priority algorithm (BCSH 2016):
      1. ABO/Rh compatible (hard filter)
      2. Unit satisfies all required-negative antigens from phenotype + antibodies
      3. Sort FEFO then most-antigens-matched first
    """
    from patients.models import Patient, PatientAntibody
    from django.db.models import Q

    branch_id = request.session.get('branch_id')
    patient = None
    matched_units = []
    required_antigens = {}
    antibodies = []
    has_phenotype = False
    abo_compatible_types = []

    ANTIBODY_TO_ANTIGEN = {
        'anti-C': 'C', 'anti-c': 'c', 'anti-E': 'E', 'anti-e': 'e',
        'anti-K': 'K', 'anti-k': 'k',
        'anti-Fya': 'Fya', 'anti-Fyb': 'Fyb',
        'anti-Jka': 'Jka', 'anti-Jkb': 'Jkb',
        'anti-M': 'M', 'anti-N': 'N', 'anti-S': 'S', 'anti-s': 's',
        'anti-Lea': 'Lea', 'anti-Leb': 'Leb',
    }

    ABO_COMPAT = {
        'A':  ['A', 'O'],
        'B':  ['B', 'O'],
        'AB': ['A', 'B', 'AB', 'O'],
        'O':  ['O'],
    }

    patient_id = request.GET.get('patient_id', '').strip()
    component_filter = request.GET.get('component', 'RBC')

    if patient_id:
        try:
            patient = Patient.objects.select_related('phenotype').prefetch_related(
                'antibodies', 'blood_groups'
            ).get(pk=int(patient_id))
        except (Patient.DoesNotExist, ValueError):
            messages.error(request, "Patient not found.")

    if patient:
        # Collect required negative antigens from phenotype
        try:
            phenotype = patient.phenotype
            has_phenotype = True
            pheno_required = phenotype.required_negative_antigens()
            for ag in pheno_required:
                required_antigens[ag] = True
        except Exception:
            has_phenotype = False

        # Also add antigens from significant antibodies directly (no phenotype needed)
        antibodies = list(PatientAntibody.objects.filter(
            patient=patient,
            clinical_significance='significant',
            status__in=['identified', 'historical_only'],
        ))
        for ab in antibodies:
            ag = ANTIBODY_TO_ANTIGEN.get(ab.specificity)
            if ag:
                required_antigens[ag] = True

        # Determine ABO compatible donor types for this patient
        bg = patient.effective_blood_group()
        if bg and bg.abo in ABO_COMPAT:
            abo_compatible_types = ABO_COMPAT[bg.abo]
            rh_patient = getattr(bg, 'rh_d', 'unknown')

            # Base queryset: available units at this branch matching component
            qs = BloodUnit.objects.filter(
                status='available',
                owner_branch_id=branch_id,
                abo_type__in=abo_compatible_types,
                component_class=component_filter,
            ).order_by('expiry_datetime')

            # Apply antigen-negative filtering in Python (JSONField)
            if required_antigens:
                passing = []
                for unit in qs.select_related('parent_donation__donor'):
                    if unit.satisfies_antigen_requirements(required_antigens):
                        passing.append(unit)
                matched_units = passing[:50]
            else:
                matched_units = list(qs[:50])
        else:
            messages.warning(request, "Patient has no confirmed blood group — ABO matching unavailable.")

    all_patients = Patient.objects.filter(record_status='active').order_by('pk')[:200]
    component_choices = [('RBC', 'Red Cells'), ('PLT', 'Platelets'), ('FFP', 'FFP'), ('CRYO', 'Cryoprecipitate')]

    return render(request, 'inventory/antigen_match.html', {
        'patient': patient,
        'matched_units': matched_units,
        'required_antigens': required_antigens,
        'antibodies': antibodies,
        'has_phenotype': has_phenotype,
        'abo_compatible_types': abo_compatible_types,
        'all_patients': all_patients,
        'component_filter': component_filter,
        'component_choices': component_choices,
        'patient_id': patient_id,
    })


@login_required
def near_expiry_units(request):
    """
    Units expiring within a configurable window — for proactive management.
    Default: 72 hours.  Supports 24 / 48 / 72 / 168 h windows.
    """
    from datetime import timedelta
    branch_id = request.session.get('branch_id')

    try:
        hours = int(request.GET.get('hours', 72))
    except (ValueError, TypeError):
        hours = 72
    if hours not in (24, 48, 72, 168):
        hours = 72
    cutoff = timezone.now() + timedelta(hours=hours)

    units = BloodUnit.objects.filter(
        status__in=['available', 'reserved', 'crossmatched'],
        owner_branch_id=branch_id,
        expiry_datetime__lte=cutoff,
        expiry_datetime__gt=timezone.now(),
    ).order_by('expiry_datetime')

    component_filter = request.GET.get('component', '')
    if component_filter:
        units = units.filter(component_class=component_filter)

    paginator = Paginator(units, 30)
    page = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'inventory/near_expiry.html', {
        'page': page,
        'hours': hours,
        'component_filter': component_filter,
        'total_count': paginator.count,
        'component_classes': COMPONENT_CLASSES,
    })


# ─── Guided Component Modification Workflows ──────────────────────────────────

@login_required
def leukoreduction_unit(request, did):
    """
    Guided leukoreduction — records filter lot, residual counts, SOP, e-sign.
    BCSH / JPAC: residual leukocyte count must be < 5×10^6/unit.
    """
    unit = get_object_or_404(BloodUnit, did=did)
    branch_id = request.session.get('branch_id')

    if unit.is_leukoreduced:
        messages.warning(request, f"Unit {did} is already leukoreduced.")
        return redirect('inventory:unit_detail', did=did)
    if unit.status not in ('available', 'quarantined', 'reserved'):
        messages.error(request, f"Cannot leukoreduced a unit with status '{unit.status}'.")
        return redirect('inventory:unit_detail', did=did)

    if request.method == 'POST':
        filter_lot     = request.POST.get('filter_lot', '').strip()
        sop_version    = request.POST.get('sop_version', '').strip()
        pre_count_str  = request.POST.get('pre_leukocyte_count', '').strip()
        post_count_str = request.POST.get('post_leukocyte_count', '').strip()
        notes          = request.POST.get('notes', '').strip()

        errors = []
        if not filter_lot:
            errors.append("Filter lot number is required.")
        if not sop_version:
            errors.append("SOP version is required.")
        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'inventory/leukoreduction_unit.html', {'unit': unit})

        from audit.utils import create_signature
        from core.models import Branch
        branch = Branch.objects.filter(pk=branch_id).first() if branch_id else unit.owner_branch
        if not branch:
            messages.error(request, "Branch not found. Please re-select your branch.")
            return redirect('core:select_branch')
        now = timezone.now()

        note_parts = [f"Filter lot: {filter_lot}"]
        if pre_count_str:
            note_parts.append(f"Pre-count: {pre_count_str} x10^6/unit")
        if post_count_str:
            note_parts.append(f"Post-count: {post_count_str} x10^6/unit")
        if notes:
            note_parts.append(notes)

        event = ProcessingEvent.objects.create(
            event_type='leukoreduction',
            performed_at=now,
            performed_by=request.user,
            branch=branch,
            blood_unit=unit,
            sop_version=sop_version,
            notes='. '.join(note_parts),
        )
        esign = create_signature(
            signer=request.user,
            meaning='verified',
            payload_data={
                'unit_did': unit.did, 'filter_lot': filter_lot,
                'processing_event_pk': event.pk, 'sop_version': sop_version,
            },
        )
        event.esign = esign
        event.save(update_fields=['esign'])

        unit.is_leukoreduced = True
        unit.save(update_fields=['is_leukoreduced'])

        write_audit(
            actor=request.user, action='unit.leukoreduced',
            entity_table='inventory_bloodunit', entity_id=unit.pk,
            after={'is_leukoreduced': True, 'filter_lot': filter_lot},
            action_meaning=f'Unit {unit.did} leukoreduced (filter lot: {filter_lot})',
            branch=branch,
        )
        messages.success(request, f"Unit {did} leukoreduced and signed (SOP {sop_version}).")
        return redirect('inventory:unit_detail', did=did)

    return render(request, 'inventory/leukoreduction_unit.html', {'unit': unit})


@login_required
def wash_unit(request, did):
    """
    Guided washing workflow — records wash solution, indication, volume, SOP, e-sign.
    Used for: IgA deficiency, allergic history, haemolytic disease prep, neonatal prep.
    """
    INDICATIONS = [
        ('allergic_history', 'Allergic reaction history — remove plasma proteins'),
        ('iga_deficiency',   'IgA deficiency — prevent anaphylaxis'),
        ('haemolytic',       'Haemolytic disease — remove antibodies/additives'),
        ('hyperkalaemia',    'Hyperkalaemia risk — remove K+'),
        ('neonatal_prep',    'Neonatal preparation — remove additives'),
        ('other',            'Other (see notes)'),
    ]
    WASH_SOLUTIONS = [
        ('normal_saline', '0.9% Normal saline'),
        ('adsol',         'ADSOL / AdSol-M'),
        ('other',         'Other (see notes)'),
    ]
    unit = get_object_or_404(BloodUnit, did=did)
    branch_id = request.session.get('branch_id')

    if unit.is_washed:
        messages.warning(request, f"Unit {did} is already washed.")
        return redirect('inventory:unit_detail', did=did)
    if unit.status not in ('available', 'quarantined', 'reserved'):
        messages.error(request, f"Cannot wash a unit with status '{unit.status}'.")
        return redirect('inventory:unit_detail', did=did)

    if request.method == 'POST':
        indication    = request.POST.get('indication', '').strip()
        wash_solution = request.POST.get('wash_solution', '').strip()
        num_washes    = request.POST.get('num_washes', '').strip()
        wash_vol_ml   = request.POST.get('wash_vol_ml', '').strip()
        sop_version   = request.POST.get('sop_version', '').strip()
        notes         = request.POST.get('notes', '').strip()

        errors = []
        if not indication:
            errors.append("Indication is required.")
        if not sop_version:
            errors.append("SOP version is required.")
        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'inventory/wash_unit.html', {
                'unit': unit, 'indications': INDICATIONS, 'wash_solutions': WASH_SOLUTIONS,
            })

        from audit.utils import create_signature
        from core.models import Branch
        branch = Branch.objects.filter(pk=branch_id).first() if branch_id else unit.owner_branch
        if not branch:
            messages.error(request, "Branch not found. Please re-select your branch.")
            return redirect('core:select_branch')
        now = timezone.now()

        note_parts = [f"Indication: {indication}", f"Solution: {wash_solution or 'N/S'}"]
        if num_washes:
            note_parts.append(f"Washes: {num_washes}")
        if wash_vol_ml:
            note_parts.append(f"Volume/wash: {wash_vol_ml} mL")
        if notes:
            note_parts.append(notes)

        event = ProcessingEvent.objects.create(
            event_type='wash',
            performed_at=now,
            performed_by=request.user,
            branch=branch,
            blood_unit=unit,
            sop_version=sop_version,
            notes='. '.join(note_parts),
        )
        esign = create_signature(
            signer=request.user,
            meaning='verified',
            payload_data={
                'unit_did': unit.did, 'indication': indication,
                'processing_event_pk': event.pk, 'sop_version': sop_version,
            },
        )
        event.esign = esign
        event.save(update_fields=['esign'])

        unit.is_washed = True
        unit.save(update_fields=['is_washed'])

        write_audit(
            actor=request.user, action='unit.washed',
            entity_table='inventory_bloodunit', entity_id=unit.pk,
            after={'is_washed': True, 'indication': indication},
            action_meaning=f'Unit {unit.did} washed — indication: {indication}',
            branch=branch,
        )
        messages.success(request, f"Unit {did} washing recorded (SOP {sop_version}).")
        return redirect('inventory:unit_detail', did=did)

    return render(request, 'inventory/wash_unit.html', {
        'unit': unit, 'indications': INDICATIONS, 'wash_solutions': WASH_SOLUTIONS,
    })


@login_required
def pool_platelets(request):
    """
    Platelet pool composition workflow.

    Select 4-6 available PLT units. Creates a new pooled BloodUnit,
    ProcessingEvent(type='pooling'), UnitLineage edges, marks inputs consumed.
    BCSH: pool expiry = earliest input expiry; pool volume = sum of volumes.
    """
    from collections import Counter
    from core.did import generate_did
    from core.models import Branch, RefFacility

    branch_id = request.session.get('branch_id')
    available_plts = (
        BloodUnit.objects
        .filter(owner_branch_id=branch_id, component_class='PLT', status='available')
        .order_by('expiry_datetime')
    )

    if request.method == 'POST':
        unit_pks    = request.POST.getlist('unit_pks')
        sop_version = request.POST.get('sop_version', '').strip()
        notes       = request.POST.get('notes', '').strip()

        errors = []
        if len(unit_pks) < 4:
            errors.append("Minimum 4 PLT units required for a pool.")
        if len(unit_pks) > 6:
            errors.append("Maximum 6 PLT units allowed per pool.")
        if not sop_version:
            errors.append("SOP version is required.")

        units_to_pool = []
        if unit_pks and not errors:
            units_to_pool = list(
                BloodUnit.objects.filter(
                    pk__in=unit_pks,
                    owner_branch_id=branch_id,
                    component_class='PLT',
                    status='available',
                )
            )
            if len(units_to_pool) != len(unit_pks):
                errors.append("One or more selected units are no longer available.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'inventory/pool_platelets.html', {
                'available_plts': available_plts,
            })

        from audit.utils import create_signature
        branch = Branch.objects.filter(pk=branch_id).first() if branch_id else None
        if not branch:
            messages.error(request, "Branch not found. Please re-select your branch.")
            return redirect('core:select_branch')
        now = timezone.now()

        pool_expiry = min(u.expiry_datetime for u in units_to_pool)
        pool_volume = sum((u.volume_ml or 55) for u in units_to_pool)
        abo_counts = Counter(u.abo_type for u in units_to_pool)
        pool_abo = abo_counts.most_common(1)[0][0]
        rh_d = units_to_pool[0].rh_d_type

        try:
            facility = RefFacility.objects.get(branch=branch)
        except RefFacility.DoesNotExist:
            messages.error(request, "Facility reference not configured for this branch. Contact administrator.")
            return redirect('inventory:unit_list')
        serial = facility.next_serial()
        pool_did = generate_did(facility.facility_code, serial)

        plt_type = ComponentType.objects.filter(component_class='PLT').first()
        if not plt_type:
            messages.error(request, "No PLT component type configured.")
            return redirect('inventory:unit_list')

        pool_event = ProcessingEvent.objects.create(
            event_type='pooling',
            performed_at=now,
            performed_by=request.user,
            branch=branch,
            sop_version=sop_version,
            notes=f"Pool of {len(units_to_pool)} units. ABO: {pool_abo}. {notes}".strip(),
        )

        pooled_unit = BloodUnit.objects.create(
            did=pool_did,
            did_check_char=pool_did[-1],
            donation=units_to_pool[0].donation,
            parent_donation=units_to_pool[0].parent_donation,
            component_type=plt_type,
            component_class='PLT',
            abo_type=pool_abo,
            rh_d_type=rh_d,
            collection_datetime=min(u.collection_datetime for u in units_to_pool),
            expiry_datetime=pool_expiry,
            volume_ml=pool_volume,
            status='available',
            owner_branch=branch,
            production_event=pool_event,
            is_leukoreduced=all(u.is_leukoreduced for u in units_to_pool),
            is_irradiated=all(u.is_irradiated for u in units_to_pool),
        )

        esign = create_signature(
            signer=request.user,
            meaning='verified',
            payload_data={
                'pool_did': pool_did,
                'input_unit_pks': [u.pk for u in units_to_pool],
                'processing_event_pk': pool_event.pk,
                'sop_version': sop_version,
            },
        )
        pool_event.esign = esign
        pool_event.save(update_fields=['esign'])

        for unit in units_to_pool:
            UnitLineage.objects.create(
                processing_event=pool_event,
                parent_unit=unit,
                child_unit=pooled_unit,
                relationship='pooled_into',
            )
            transition_unit(unit, 'issued', request.user,
                            reason=f"Consumed in PLT pool {pool_did}")

        write_audit(
            actor=request.user, action='unit.pooled',
            entity_table='inventory_bloodunit', entity_id=pooled_unit.pk,
            after={'pool_did': pool_did, 'input_count': len(units_to_pool), 'abo': pool_abo},
            action_meaning=f'Platelet pool {pool_did} created from {len(units_to_pool)} units',
            branch=branch,
        )
        messages.success(
            request,
            f"Platelet pool {pool_did} created from {len(units_to_pool)} units. "
            f"ABO: {pool_abo}, expiry: {pool_expiry:%d %b %Y %H:%M}.",
        )
        return redirect('inventory:unit_detail', did=pool_did)

    return render(request, 'inventory/pool_platelets.html', {'available_plts': available_plts})
