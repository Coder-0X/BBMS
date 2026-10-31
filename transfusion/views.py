from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.db.models import Q

from .models import (
    Sample, BloodRequest, Crossmatch, EmergencyRelease, TestDefinition, MSBOS,
    IssueTransaction, TransfusionAdministration, LookbackCampaign, LookbackNotification,
    DonationBloodGrouping, TransfusionReaction, TransfusionGuidelineCheck,
    PostTransfusionOutcome, SurgicalBloodOrder,
)
from django.core.paginator import Paginator
from .issue import issue_unit
from .testing import record_test_result
from audit.utils import write_audit, create_signature
from accounts.permissions import has_permission


def _compatible_abo_donors(patient_abo: str) -> list:
    """Return ABO types that can donate to a patient with the given ABO."""
    compat = {
        'O':  ['O'],
        'A':  ['O', 'A'],
        'B':  ['O', 'B'],
        'AB': ['O', 'A', 'B', 'AB'],
    }
    return compat.get(patient_abo, [patient_abo])


def _compatible_rh_donors(patient_rh: str) -> list:
    """Rh D negative patients must receive Rh D negative; positive can receive either."""
    if patient_rh == 'neg':
        return ['neg']
    return ['pos', 'neg', 'weak_d']


@login_required
def new_blood_request(request):
    if request.method == 'POST':
        from patients.models import Patient
        try:
            patient_id_val = int(request.POST.get('patient_id', ''))
        except (ValueError, TypeError):
            messages.error(request, "Invalid patient selection.")
            return redirect('transfusion:request_list')
        patient = get_object_or_404(Patient, pk=patient_id_val)
        is_neonatal = request.POST.get('is_neonatal') == '1'
        neonatal_weight = request.POST.get('neonatal_weight_kg', '').strip() or None
        try:
            neonatal_weight_kg_float = float(neonatal_weight) if neonatal_weight else None
        except (ValueError, TypeError):
            neonatal_weight_kg_float = None
        # Consent check — warn (don't block) if no valid consent on file
        from patients.models import TransfusionConsent
        urgency = request.POST.get('urgency', 'routine')
        active_consent = TransfusionConsent.objects.filter(
            patient=patient, status='active',
        ).order_by('-obtained_at').first()
        consent_valid = active_consent and active_consent.is_valid()

        try:
            units_requested = int(request.POST.get('units_requested', 1))
        except (ValueError, TypeError):
            units_requested = 1

        req = BloodRequest.objects.create(
            patient=patient,
            branch_id=request.session.get('branch_id'),
            requesting_physician=request.user,
            component_class=request.POST['component_class'],
            units_requested=units_requested,
            urgency=urgency,
            is_neonatal=is_neonatal,
            neonatal_weight_kg=neonatal_weight_kg_float,
            special_requirements_snapshot={
                r.requirement: r.antigen_spec
                for r in patient.active_special_requirements()
            },
        )
        write_audit(
            actor=request.user,
            action='transfusion.request.create',
            entity_table='transfusion_bloodrequest',
            entity_id=req.pk,
            after={'patient_id': patient.pk, 'component_class': req.component_class,
                   'units_requested': req.units_requested, 'urgency': urgency},
            branch=req.branch,
        )
        msg = f"Request #{req.pk} created."
        if is_neonatal:
            msg += " Neonatal flag set — please create a Neonatal Order to specify unit requirements."
        if not consent_valid and urgency != 'emergency_mtp':
            messages.warning(request,
                f"Request #{req.pk} created. WARNING: Patient #{patient.pk} has no valid informed consent on file. "
                "Obtain consent before transfusion proceeds (visit Patient detail → Consent tab)."
            )
        else:
            messages.success(request, msg)
        return redirect('transfusion:request_detail', pk=req.pk)
    return render(request, 'transfusion/new_request.html')


@login_required
def request_detail(request, pk):
    req = get_object_or_404(BloodRequest, pk=pk)
    return render(request, 'transfusion/request_detail.html', {
        'req': req,
        'crossmatches': req.crossmatches.select_related('blood_unit', 'tech').all(),
        'issues': req.issue_transactions.select_related('blood_unit', 'issued_by').all(),
    })


@login_required
def collect_sample(request):
    if request.method == 'POST':
        from patients.models import Patient
        try:
            patient_id_val = int(request.POST.get('patient_id', ''))
        except (ValueError, TypeError):
            messages.error(request, "Invalid patient selection.")
            return redirect('transfusion:collect_sample')
        patient = get_object_or_404(Patient, pk=patient_id_val)
        # 3-day rule: recent transfusion/pregnancy → 72h validity
        had_recent_event = request.POST.get('recent_transfusion_or_pregnancy') == 'yes'
        from datetime import timedelta as _td
        expiry = timezone.now() + _td(hours=72) if had_recent_event else None
        sample = Sample.objects.create(
            patient=patient,
            accession_number=request.POST['accession_number'],
            collected_at=timezone.now(),
            collected_by=request.user,
            sample_type='pre_transfusion',
            validity_expiry=expiry,
            branch_id=request.session.get('branch_id'),
        )
        write_audit(
            actor=request.user,
            action='sample.collect.pretransfusion',
            entity_table='transfusion_sample',
            entity_id=sample.pk,
            after={'accession': sample.accession_number, 'patient_id': patient.pk,
                   'validity_expiry': sample.validity_expiry.isoformat() if sample.validity_expiry else None},
        )
        messages.success(request, f"Sample {sample.accession_number} collected.")
        return redirect('transfusion:request_detail', pk=request.POST['request_id'])
    return render(request, 'transfusion/collect_sample.html')


@login_required
def collect_donor_sample(request, donation_pk):
    """
    Register a donor screening sample for a specific donation.
    This sample will be used for TTI testing and blood grouping.
    """
    from donors.models import Donation
    donation = get_object_or_404(Donation, pk=donation_pk)
    donor = donation.donor

    if request.method == 'POST':
        accession_number = request.POST.get('accession_number', '').strip()
        if not accession_number:
            messages.error(request, "Accession number is required.")
            return redirect('transfusion:collect_donor_sample', donation_pk=donation_pk)

        if Sample.objects.filter(accession_number=accession_number).exists():
            messages.error(request, f"Sample {accession_number} already registered.")
            return redirect('transfusion:collect_donor_sample', donation_pk=donation_pk)

        sample = Sample.objects.create(
            donor=donor,
            accession_number=accession_number,
            collected_at=timezone.now(),
            collected_by=request.user,
            sample_type='donor_screening',
            branch_id=request.session.get('branch_id'),
        )
        write_audit(
            actor=request.user,
            action='sample.collect.donor',
            entity_table='transfusion_sample',
            entity_id=sample.pk,
            after={'donation_id': donation.pk, 'accession': accession_number},
        )
        messages.success(request, f"Donor screening sample {sample.accession_number} registered.")
        return redirect('transfusion:donation_blood_grouping', donation_pk=donation_pk)

    existing_samples = Sample.objects.filter(donor=donor, sample_type='donor_screening').order_by('-collected_at')[:5]
    return render(request, 'transfusion/collect_donor_sample.html', {
        'donation': donation,
        'donor': donor,
        'existing_samples': existing_samples,
    })


@login_required
def record_tti_result(request):
    if not has_permission(request.user, 'test.perform', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')

    if request.method == 'POST':
        from donors.models import Donation
        donation = get_object_or_404(Donation, pk=request.POST['donation_id'])
        sample = get_object_or_404(Sample, accession_number=request.POST['accession_number'])

        reauth_at = request.session.get('reauth_at')
        result = record_test_result(
            donation=donation,
            test_code=request.POST['test_code'],
            sample=sample,
            result=request.POST['result'],
            performed_by=request.user,
            reviewed_by=request.user,
            reauth_at=reauth_at,
            instrument=request.POST.get('instrument', ''),
            instrument_lot=request.POST.get('instrument_lot', ''),
        )
        if result.result == 'reactive':
            messages.warning(request, f"Reactive result — all units from donation #{donation.pk} have been quarantined.")
        else:
            messages.success(request, f"Test result recorded: {result.result}")
        return redirect('donors:detail', pk=donation.donor_id)
    tests = TestDefinition.objects.filter(mandatory=True, applies_to__in=['donors', 'both'])
    return render(request, 'transfusion/record_tti.html', {'tests': tests})


@login_required
def new_antibody_screen(request):
    if request.method == 'POST':
        from .models import AntibodyScreen
        sample = get_object_or_404(Sample, accession_number=request.POST['accession_number'])
        screen = AntibodyScreen.objects.create(
            sample=sample,
            method=request.POST['method'],
            screen_cell_lot=request.POST['screen_cell_lot'],
            result_per_cell=request.POST.get('result_per_cell', {}),
            overall_result=request.POST['overall_result'],
            tech=request.user,
            performed_at=timezone.now(),
        )
        write_audit(
            actor=request.user,
            action='antibody.screen.record',
            entity_table='transfusion_antibodyscreen',
            entity_id=screen.pk,
            after={'accession': sample.accession_number, 'result': screen.overall_result},
        )
        messages.success(request, f"Antibody screen: {screen.overall_result}")
        request_id = request.POST.get('request_id', '').strip()
        if request_id:
            return redirect('transfusion:request_detail', pk=int(request_id))
        return redirect('core:dashboard')
    return render(request, 'transfusion/antibody_screen.html')


def _check_electronic_xm_eligibility(patient, unit) -> list:
    """
    Returns a list of reasons why electronic crossmatch is NOT eligible.
    Empty list = all gates pass, electronic XM permitted.
    Gates (REQ-X05):
      (a) ≥2 concordant ABO/Rh results on file for patient
      (b) Current antibody screen = negative (most recent screen on a valid sample)
      (c) No clinically significant antibody history
      (d) Blood unit ABO confirmed (abo_type not blank)
    """
    reasons = []

    # Gate (a): ≥2 concordant determinations
    confirmed_count = patient.blood_groups.filter(is_discrepant=False).count()
    if confirmed_count < 2:
        reasons.append(
            f"Patient has only {confirmed_count} concordant ABO/Rh determination(s) — 2 required for electronic XM."
        )

    # Gate (b): most recent antibody screen result
    from transfusion.models import AntibodyScreen
    latest_screen = (
        AntibodyScreen.objects
        .filter(sample__patient=patient)
        .order_by('-performed_at')
        .first()
    )
    if latest_screen is None:
        reasons.append("No antibody screen on file — screen required before electronic XM.")
    elif latest_screen.overall_result != 'negative':
        reasons.append(f"Latest antibody screen is {latest_screen.overall_result} — negative required for electronic XM.")

    # Gate (c): no clinically significant antibody history
    from patients.models import PatientAntibody
    has_antibodies = PatientAntibody.objects.filter(
        patient=patient,
        clinical_significance='significant',
        status__in=['identified', 'historical_only'],
    ).exists()
    if has_antibodies:
        reasons.append("Patient has a history of clinically significant alloantibodies — AHG crossmatch required.")

    # Gate (d): unit ABO confirmed
    if not unit.abo_type:
        reasons.append(f"Blood unit {unit.did} does not have a confirmed ABO type.")

    return reasons


def _abo_rh_label(abo, rh_d):
    rh_map = {'pos': '+', 'neg': '−', 'weak_d': 'weak D', 'unknown': '?'}
    return f"{abo}{rh_map.get(rh_d, rh_d)}"


def _compatible_label_list(abo, rh_d):
    """Return display labels of all compatible donor types for a patient."""
    abos = _compatible_abo_donors(abo)
    rhs  = _compatible_rh_donors(rh_d)
    labels = []
    for a in abos:
        for r in rhs:
            labels.append(_abo_rh_label(a, r))
    return labels


@login_required
def lock_unit_for_xm(request):
    """Reserve a unit for crossmatch — moves it from available → reserved."""
    if not has_permission(request.user, 'test.crossmatch', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')

    if request.method != 'POST':
        return redirect('transfusion:crossmatch')

    from inventory.models import BloodUnit
    from inventory.state_machine import transition_unit
    from django.db import transaction as db_tx, OperationalError

    req  = get_object_or_404(BloodRequest, pk=request.POST['request_id'])
    unit = get_object_or_404(BloodUnit, did=request.POST['unit_did'])

    try:
        with db_tx.atomic():
            unit = BloodUnit.objects.select_for_update(nowait=True).get(pk=unit.pk)
            if unit.status != 'available':
                messages.error(request, f"Unit {unit.did} is not available (status: {unit.status}).")
                return redirect(f"{request.META.get('HTTP_REFERER', '/')}?request_id={req.pk}")

            transition_unit(unit, 'reserved', request.user,
                            reason=f"Reserved for crossmatch — Request #{req.pk}")
            from datetime import timedelta as _td
            reserved_until = timezone.now() + _td(hours=4)
            unit.reserved_for_request = req
            unit.reserved_by = request.user
            unit.reserved_until = reserved_until
            unit.save(update_fields=['reserved_for_request', 'reserved_by', 'reserved_until'])
            write_audit(
                actor=request.user,
                action='unit.reserved_for_xm',
                entity_table='inventory_bloodunit',
                entity_id=unit.pk,
                after={
                    'request_id': req.pk,
                    'reserved_until': reserved_until.isoformat(),
                },
            )

    except OperationalError:
        messages.error(request, f"Unit {unit.did} is locked by another user. Please try again.")

    return redirect(f"{request.build_absolute_uri('/transfusion/crossmatch/new/')}?request_id={req.pk}")


@login_required
def unlock_unit_for_xm(request):
    """Release a reserved unit back to available."""
    if not has_permission(request.user, 'test.crossmatch', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')

    if request.method != 'POST':
        return redirect('transfusion:crossmatch')

    from inventory.models import BloodUnit
    from inventory.state_machine import transition_unit
    from django.db import transaction as db_tx, OperationalError

    req  = get_object_or_404(BloodRequest, pk=request.POST['request_id'])
    unit = get_object_or_404(BloodUnit, did=request.POST['unit_did'])

    try:
        with db_tx.atomic():
            unit = BloodUnit.objects.select_for_update(nowait=True).get(pk=unit.pk)
            if unit.status == 'reserved' and unit.reserved_for_request_id == req.pk:
                transition_unit(unit, 'available', request.user,
                                reason=f"Reservation released — Request #{req.pk}")
                unit.reserved_for_request = None
                unit.reserved_by = None
                unit.reserved_until = None
                unit.save(update_fields=['reserved_for_request', 'reserved_by', 'reserved_until'])
                write_audit(
                    actor=request.user,
                    action='unit.reservation_released',
                    entity_table='inventory_bloodunit',
                    entity_id=unit.pk,
                    after={'request_id': req.pk},
                )
                messages.success(request, f"Unit {unit.did} released back to available.")
            else:
                messages.error(request, f"Unit {unit.did} is not reserved for this request.")
    except OperationalError:
        messages.error(request, f"Unit {unit.did} is locked. Please try again.")

    return redirect(f"{request.build_absolute_uri('/transfusion/crossmatch/new/')}?request_id={req.pk}")


@login_required
def new_crossmatch(request):
    if not has_permission(request.user, 'test.crossmatch', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')

    if request.method == 'POST':
        from inventory.models import BloodUnit
        sample = get_object_or_404(Sample, accession_number=request.POST['accession_number'])
        unit   = get_object_or_404(BloodUnit, did=request.POST['unit_did'])
        req    = get_object_or_404(BloodRequest, pk=request.POST['request_id'])

        # Sample validity (3-day rule)
        if not sample.is_valid():
            messages.error(request, f"Sample {sample.accession_number} has expired (3-day rule). Collect a fresh sample.")
            return redirect(f"{request.build_absolute_uri('/transfusion/crossmatch/new/')}?request_id={req.pk}")

        # Patient belongs to this request
        if sample.patient and sample.patient_id != req.patient_id:
            messages.error(request, "Sample does not belong to the patient on this request.")
            return redirect(f"{request.build_absolute_uri('/transfusion/crossmatch/new/')}?request_id={req.pk}")

        method = request.POST['method']

        # Electronic XM eligibility gates (REQ-X05)
        if method == 'electronic':
            patient = req.patient
            xm_errors = _check_electronic_xm_eligibility(patient, unit)
            if xm_errors:
                for err in xm_errors:
                    messages.error(request, f"Electronic XM blocked: {err}")
                messages.warning(request, "Switch to AHG (full antiglobulin) method.")
                return redirect(f"{request.build_absolute_uri('/transfusion/crossmatch/new/')}?request_id={req.pk}")

        reauth_at = request.session.get('reauth_at')
        esign = create_signature(
            signer=request.user,
            meaning='crossmatch_result',
            payload_data={
                'unit_did': unit.did,
                'patient_id': req.patient_id,
                'result': request.POST['result'],
            },
            reauth_at=reauth_at,
        )

        from django.db import transaction as db_tx, OperationalError
        try:
            with db_tx.atomic():
                from inventory.models import BloodUnit as BU
                unit = BU.objects.select_for_update(nowait=True).get(pk=unit.pk)

                # Accept both available (direct) and reserved (locked) units
                if unit.status not in ('available', 'reserved'):
                    messages.error(request, f"Unit {unit.did} cannot be crossmatched (status: {unit.status}).")
                    return redirect('transfusion:crossmatch')

                xm = Crossmatch.objects.create(
                    sample=sample,
                    blood_unit=unit,
                    request=req,
                    method=method,
                    result=request.POST['result'],
                    reagent_lot=request.POST.get('reagent_lot', ''),
                    tech=request.user,
                    performed_at=timezone.now(),
                    esign=esign,
                )

                write_audit(
                    actor=request.user,
                    action='crossmatch.record',
                    entity_table='transfusion_crossmatch',
                    entity_id=xm.pk,
                    after={'unit_did': unit.did, 'result': xm.result, 'method': method,
                           'patient_id': req.patient_id},
                    branch=req.branch,
                )

                from inventory.state_machine import transition_unit
                if xm.result in ('compatible', 'electronic_release'):
                    transition_unit(unit, 'crossmatched', request.user,
                                    reason=f"Crossmatch #{xm.pk} — compatible")
                    # Clear reservation metadata
                    unit.reserved_for_request = None
                    unit.reserved_by = None
                    unit.reserved_until = None
                    unit.save(update_fields=['reserved_for_request', 'reserved_by', 'reserved_until'])
                    req.units_crossmatched += 1
                    req.crossmatch_completed_ts = timezone.now()
                    req.save(update_fields=['units_crossmatched', 'crossmatch_completed_ts'])
                elif xm.result == 'incompatible':
                    # If unit was reserved, release it back to available
                    if unit.status == 'reserved':
                        transition_unit(unit, 'available', request.user,
                                        reason=f"Crossmatch #{xm.pk} — incompatible, released")
                        unit.reserved_for_request = None
                        unit.reserved_by = None
                        unit.reserved_until = None
                        unit.save(update_fields=['reserved_for_request', 'reserved_by', 'reserved_until'])
                    messages.warning(request, f"Crossmatch INCOMPATIBLE — unit {unit.did} returned to available stock.")
                    return redirect('transfusion:request_detail', pk=req.pk)

        except OperationalError:
            messages.error(request, f"Unit {unit.did} is locked by another transaction. Please try again.")
            return redirect('transfusion:crossmatch')

        messages.success(request, f"Crossmatch {xm.get_result_display()} — unit {unit.did} crossmatched to Request #{req.pk}.")
        return redirect('transfusion:request_detail', pk=req.pk)

    # GET — build the crossmatch workspace for a request
    from inventory.models import BloodUnit
    request_id = request.GET.get('request_id')
    req = None
    available_units = []
    locked_units = []
    patient_bg = None
    compatible_type_labels = []

    if request_id:
        req = get_object_or_404(BloodRequest, pk=request_id)
        branch_id = request.session.get('branch_id')
        patient = req.patient
        patient_bg = patient.effective_blood_group()

        # Build available compatible units — exclude expired even if cron hasn't run yet
        qs_avail = BloodUnit.objects.filter(
            owner_branch_id=branch_id,
            component_class=req.component_class,
            status='available',
            expiry_datetime__gt=timezone.now(),
        ).order_by('expiry_datetime')

        # Build already-locked (reserved) units for this request
        qs_locked = BloodUnit.objects.filter(
            reserved_for_request=req,
            status='reserved',
        ).order_by('expiry_datetime')

        if patient_bg:
            compatible_abo = _compatible_abo_donors(patient_bg.abo)
            compatible_rh  = _compatible_rh_donors(patient_bg.rh_d)
            qs_avail = qs_avail.filter(abo_type__in=compatible_abo, rh_d_type__in=compatible_rh)
            compatible_type_labels = _compatible_label_list(patient_bg.abo, patient_bg.rh_d)

        snap = req.special_requirements_snapshot or {}
        if snap.get('irradiated'):
            qs_avail  = qs_avail.filter(is_irradiated=True)
            qs_locked = qs_locked.filter(is_irradiated=True)
        if snap.get('leukoreduced') or snap.get('leuco_reduced'):
            qs_avail  = qs_avail.filter(is_leukoreduced=True)
            qs_locked = qs_locked.filter(is_leukoreduced=True)
        if snap.get('cmv_negative'):
            qs_avail  = qs_avail.filter(is_cmv_negative=True)
            qs_locked = qs_locked.filter(is_cmv_negative=True)
        if snap.get('washed'):
            qs_avail  = qs_avail.filter(is_washed=True)
            qs_locked = qs_locked.filter(is_washed=True)

        available_units = list(qs_avail[:50])
        locked_units    = list(qs_locked[:20])

    return render(request, 'transfusion/crossmatch.html', {
        'req': req,
        'available_units': available_units,
        'locked_units': locked_units,
        'patient_bg': patient_bg,
        'compatible_type_labels': compatible_type_labels,
    })


@login_required
def issue_unit_view(request):
    if not has_permission(request.user, 'unit.release', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')

    if request.method == 'POST':
        from inventory.models import BloodUnit
        unit_did = request.POST.get('unit_did', '').strip()
        try:
            request_id = int(request.POST['request_id'])
        except (ValueError, KeyError):
            messages.error(request, "Invalid request ID.")
            return redirect('transfusion:request_list')

        try:
            unit = BloodUnit.objects.get(did=unit_did)
        except BloodUnit.DoesNotExist:
            messages.error(request, f"Blood unit '{unit_did}' not found.")
            return redirect('transfusion:request_detail', pk=request_id)

        emergency_release_id = request.POST.get('emergency_release_id') or None
        crossmatch_id = request.POST.get('crossmatch_id') or None

        # Auto-resolve crossmatch from this unit + request if not manually supplied
        if not crossmatch_id and not emergency_release_id:
            xm = Crossmatch.objects.filter(
                blood_unit=unit,
                request_id=request_id,
                result__in=('compatible', 'electronic_release'),
            ).order_by('-performed_at').first()
            if xm:
                crossmatch_id = xm.pk

        reauth_at = request.session.get('reauth_at')
        try:
            tx = issue_unit(
                blood_unit_id=unit.pk,
                patient_id=int(request.POST['patient_id']),
                request_id=request_id,
                actor=request.user,
                reauth_at=reauth_at,
                crossmatch_id=crossmatch_id,
                emergency_release_id=emergency_release_id,
            )
            messages.success(request, f"Unit {unit.did} issued — Transaction #{tx.pk}.")
        except Exception as e:
            messages.error(request, f"Issue failed: {e}")
        return redirect('transfusion:request_detail', pk=request_id)

    # GET — show crossmatched-and-compatible units ready to issue for the request
    req = None
    crossmatched_xms = []
    request_id = request.GET.get('request_id')
    if request_id:
        req = get_object_or_404(BloodRequest, pk=request_id)
        seen_units = set()
        for xm in Crossmatch.objects.filter(
            request=req,
            result__in=('compatible', 'electronic_release'),
        ).select_related('blood_unit').order_by('blood_unit__expiry_datetime'):
            if xm.blood_unit_id not in seen_units and xm.blood_unit.status == 'crossmatched':
                crossmatched_xms.append(xm)
                seen_units.add(xm.blood_unit_id)

    return render(request, 'transfusion/issue.html', {
        'req': req,
        'crossmatched_xms': crossmatched_xms,
    })


@login_required
def emergency_release_view(request):
    if not has_permission(request.user, 'unit.emergency_release', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')

    if request.method == 'POST':
        from patients.models import Patient
        from inventory.models import BloodUnit
        from inventory.state_machine import transition_unit

        req = get_object_or_404(BloodRequest, pk=request.POST['request_id'])

        reauth_at = request.session.get('reauth_at')
        esign = create_signature(
            signer=request.user,
            meaning='emergency_blood_release',
            payload_data={
                'patient_id': req.patient_id,
                'request_id': req.pk,
                'justification': request.POST['justification'],
            },
            reauth_at=reauth_at,
        )

        unit_ids = [int(x) for x in request.POST.getlist('unit_ids')]
        with transaction.atomic():
            er = EmergencyRelease.objects.create(
                request=req,
                patient=req.patient,
                units=unit_ids,
                physician=request.user,
                justification=request.POST['justification'],
                release_esign=esign,
            )

            # Transition each unit to issued — use get_object_or_404 so a stale
            # or tampered unit_id rolls back the whole transaction (ER included).
            for uid in unit_ids:
                unit = get_object_or_404(BloodUnit, pk=uid)
                transition_unit(unit, 'issued', request.user,
                                reason=f"Emergency release #{er.pk}")

            write_audit(
                actor=request.user,
                action='emergency_release.created',
                entity_table='transfusion_emergencyrelease',
                entity_id=er.pk,
                after={
                    'request_id': req.pk,
                    'patient_id': req.patient_id,
                    'unit_ids': unit_ids,
                    'justification': request.POST['justification'],
                },
                action_meaning='Uncrossmatched emergency blood release — retrospective crossmatch required',
                branch=req.branch,
            )
        messages.warning(request, f"Emergency release #{er.pk} created. Retrospective crossmatch required.")
        return redirect('transfusion:request_detail', pk=req.pk)
    return render(request, 'transfusion/emergency_release.html')


@login_required
def emergency_signoff_view(request, pk):
    er = get_object_or_404(EmergencyRelease, pk=pk)
    if not has_permission(request.user, 'unit.emergency_release', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')

    if request.method == 'POST':
        reauth_at = request.session.get('reauth_at')
        esign = create_signature(
            signer=request.user,
            meaning='emergency_release_signoff',
            payload_data={'emergency_release_id': er.pk},
            reauth_at=reauth_at,
        )
        er.signoff_status   = 'signed_off'
        er.signoff_physician = request.user
        er.signoff_at       = timezone.now()
        er.signoff_esign    = esign
        er.save(update_fields=['signoff_status', 'signoff_physician', 'signoff_at', 'signoff_esign'])
        write_audit(
            actor=request.user,
            action='emergency_release.signed_off',
            entity_table='transfusion_emergencyrelease',
            entity_id=er.pk,
            after={
                'request_id': er.request_id,
                'signoff_status': 'signed_off',
                'esign_id': esign.pk,
            },
            action_meaning='Physician signed off on uncrossmatched emergency release',
        )
        messages.success(request, f"Emergency release #{er.pk} signed off.")
        return redirect('transfusion:request_detail', pk=er.request_id)
    return render(request, 'transfusion/emergency_signoff.html', {'er': er})


@login_required
def msbos_list(request):
    branch_id = request.session.get('branch_id')
    entries = MSBOS.objects.filter(branch_id=branch_id).order_by('procedure_code')
    return render(request, 'transfusion/msbos_list.html', {'entries': entries})


@login_required
def msbos_add(request):
    branch_id = request.session.get('branch_id')
    if request.method == 'POST':
        procedure_code = request.POST['procedure_code'].strip()
        entry, created = MSBOS.objects.update_or_create(
            procedure_code=procedure_code,
            branch_id=branch_id,
            defaults={
                'order_type': request.POST['order_type'],
                'units_count': _safe_int(request.POST.get('units_count')) or 0,
            },
        )
        write_audit(
            actor=request.user,
            action='msbos.create' if created else 'msbos.update',
            entity_table='transfusion_msbos',
            entity_id=entry.pk,
            after={'procedure_code': procedure_code, 'order_type': entry.order_type,
                   'units_count': entry.units_count},
        )
        messages.success(request, f"MSBOS entry for '{procedure_code}' saved.")
        return redirect('transfusion:msbos_list')
    return render(request, 'transfusion/msbos_form.html', {'entry': None})


@login_required
def msbos_edit(request, pk):
    branch_id = request.session.get('branch_id')
    entry = get_object_or_404(MSBOS, pk=pk, branch_id=branch_id)
    if request.method == 'POST':
        before = {'order_type': entry.order_type, 'units_count': entry.units_count}
        entry.order_type = request.POST['order_type']
        entry.units_count = _safe_int(request.POST.get('units_count')) or 0
        entry.save(update_fields=['order_type', 'units_count'])
        write_audit(
            actor=request.user,
            action='msbos.update',
            entity_table='transfusion_msbos',
            entity_id=entry.pk,
            before=before,
            after={'order_type': entry.order_type, 'units_count': entry.units_count},
        )
        messages.success(request, "MSBOS entry updated.")
        return redirect('transfusion:msbos_list')
    return render(request, 'transfusion/msbos_form.html', {'entry': entry})


@login_required
def msbos_delete(request, pk):
    branch_id = request.session.get('branch_id')
    entry = get_object_or_404(MSBOS, pk=pk, branch_id=branch_id)
    if request.method == 'POST':
        entry_pk = entry.pk
        before = {'procedure_code': entry.procedure_code, 'order_type': entry.order_type}
        entry.delete()
        write_audit(
            actor=request.user,
            action='msbos.delete',
            entity_table='transfusion_msbos',
            entity_id=entry_pk,
            before=before,
        )
        messages.success(request, f"MSBOS entry '{before['procedure_code']}' removed.")
        return redirect('transfusion:msbos_list')
    return render(request, 'transfusion/msbos_confirm_delete.html', {'entry': entry})


@login_required
def request_list(request):
    """List all blood requests for the current branch with filtering."""
    branch_id = request.session.get('branch_id')
    qs = BloodRequest.objects.filter(branch_id=branch_id).select_related(
        'patient', 'requesting_physician'
    ).order_by('-requested_ts')

    urgency_filter   = request.GET.get('urgency', '')
    outcome_filter   = request.GET.get('outcome', '')
    component_filter = request.GET.get('component', '')

    if urgency_filter:
        qs = qs.filter(urgency=urgency_filter)
    if outcome_filter:
        qs = qs.filter(outcome=outcome_filter)
    if component_filter:
        qs = qs.filter(component_class=component_filter)

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'transfusion/request_list.html', {
        'page_obj': page,
        'urgency_filter': urgency_filter,
        'outcome_filter': outcome_filter,
        'component_filter': component_filter,
    })


@login_required
def record_administration(request, issue_pk):
    """Record bedside transfusion administration details for an issue transaction."""
    issue = get_object_or_404(IssueTransaction, pk=issue_pk)

    if hasattr(issue, 'administration'):
        messages.info(request, "Administration already recorded for this issue transaction.")
        return redirect('transfusion:request_detail', pk=issue.request_id)

    if request.method == 'POST':
        patient_scan = request.POST.get('patient_scan_id', '').strip()
        unit_scan    = request.POST.get('unit_scan_did', '').strip()

        # Bedside identity verification — BOTH fields must be present AND match.
        # Empty fields must count as FAIL: an unscanned wristband is not a match.
        verify_pass = bool(patient_scan) and bool(unit_scan) and (
            patient_scan == str(issue.patient_id) and
            unit_scan == issue.blood_unit.did
        )

        from django.utils.dateparse import parse_datetime
        start_at_raw = request.POST.get('start_at', '').strip()
        start_at_dt = parse_datetime(start_at_raw)
        if start_at_dt is None:
            messages.error(request, f"Invalid transfusion start time: '{start_at_raw}'. Use the datetime picker.")
            return redirect('transfusion:record_administration', issue_pk=issue_pk)
        completed_at_raw = request.POST.get('completed_at', '').strip() or None
        completed_at_dt = parse_datetime(completed_at_raw) if completed_at_raw else None

        admin_rec = TransfusionAdministration.objects.create(
            blood_unit=issue.blood_unit,
            patient=issue.patient,
            issue=issue,
            bedside_verify_pass=verify_pass,
            patient_scan_id=patient_scan,
            unit_scan_did=unit_scan,
            admin_staff_1=request.user,
            start_at=start_at_dt,
            completed_at=completed_at_dt,
            volume_given_ml=request.POST.get('volume_given_ml') or None,
            outcome=request.POST['outcome'],
            vitals_json={
                'pre_bp':    request.POST.get('pre_bp', ''),
                'pre_pulse': request.POST.get('pre_pulse', ''),
                'pre_temp':  request.POST.get('pre_temp', ''),
                'post_bp':   request.POST.get('post_bp', ''),
                'post_pulse': request.POST.get('post_pulse', ''),
                'post_temp': request.POST.get('post_temp', ''),
            },
            branch_id=request.session.get('branch_id'),
            notes=request.POST.get('notes', ''),
        )

        write_audit(
            actor=request.user,
            action='transfusion.administration.record',
            entity_table='transfusion_transfusionadministration',
            entity_id=admin_rec.pk,
            after={
                'blood_unit': issue.blood_unit.did,
                'patient': str(issue.patient_id),
                'outcome': admin_rec.outcome,
                'bedside_verify_pass': verify_pass,
            },
        )

        if not verify_pass:
            messages.warning(request,
                "Administration recorded — bedside identity check FAILED. "
                "Ensure patient/unit identity is confirmed manually.")
        else:
            messages.success(request, f"Transfusion administration #{admin_rec.pk} recorded.")
        return redirect('transfusion:request_detail', pk=issue.request_id)

    return render(request, 'transfusion/record_administration.html', {'issue': issue})


@login_required
def lookback_list(request):
    branch_id = request.session.get('branch_id')
    campaigns = LookbackCampaign.objects.filter(
        donor__registration_branch_id=branch_id,
    ).distinct().select_related('donor', 'initiated_by').order_by('-triggered_at')
    for c in campaigns:
        c.pending_count = c.notifications.filter(status='pending').count()
    return render(request, 'transfusion/lookback_list.html', {'campaigns': campaigns})


@login_required
def lookback_initiate(request):
    """
    Initiate a lookback campaign from a reactive TTI result.

    WHO/SHOT/MHRA lookback guidelines:
    - When a repeat donor tests reactive for HIV-1/2, HCV, HBV, or HTLV,
      all PREVIOUS donations within the window period must be traced.
    - Window periods (conservative NAT windows):
        HIV:   22 days (NAT); 45 days (antibody only)
        HCV:   7  days (NAT); 70 days (antibody only)
        HBV:   25 days (NAT); 45 days (HBsAg); 82 days (antibody only)
        HTLV:  51 days (antibody)
        Syphilis: 30 days
    - For each prior donation in scope: if any unit was transfused → patient must
      be notified via their treating clinician.
    """
    from donors.models import Donation
    from transfusion.models import DonationTestResult

    # Window period in days per pathogen (conservative = longest window)
    WINDOW_DAYS = {
        'HIV': 45, 'HIV-1': 45, 'HIV-2': 45, 'HIV-1/2': 45,
        'HCV': 70, 'HCV-Ab': 70, 'HCV-NAT': 7,
        'HBV': 82, 'HBsAg': 45, 'HBV-NAT': 25,
        'HTLV': 51,
        'SYPHILIS': 30, 'RPR': 30, 'TPHA': 30,
    }

    if request.method == 'POST':
        test_result_pk = request.POST.get('test_result_pk', '').strip()
        custom_window_days = request.POST.get('window_days', '').strip()

        try:
            reactive_result = DonationTestResult.objects.select_related(
                'donation__donor', 'test'
            ).get(pk=test_result_pk, result='reactive')
        except DonationTestResult.DoesNotExist:
            messages.error(request, "Reactive test result not found or result is not 'reactive'.")
            return redirect('transfusion:lookback_list')

        donor = reactive_result.donation.donor
        reactive_donation_date = reactive_result.donation.donated_at.date()

        # Determine window period
        test_code_upper = reactive_result.test.test_code.upper()
        window_days = int(custom_window_days) if custom_window_days else None
        if not window_days:
            for key, days in WINDOW_DAYS.items():
                if key in test_code_upper:
                    window_days = days
                    break
            if not window_days:
                window_days = 90  # conservative default if pathogen not mapped

        from datetime import timedelta as _td
        lookback_from = reactive_donation_date - _td(days=window_days)

        # Create the lookback campaign
        campaign = LookbackCampaign.objects.create(
            donor=donor,
            triggered_by_test=reactive_result.test.test_code,
            triggered_at=timezone.now(),
            initiated_by=request.user,
            lookback_from=lookback_from,
            notes=f"Window period: {window_days} days. Reactive result PK: {reactive_result.pk}",
        )

        # Find all prior donations in the window period (BEFORE the reactive donation)
        prior_donations = Donation.objects.filter(
            donor=donor,
            donated_at__date__gte=lookback_from,
            donated_at__date__lt=reactive_donation_date,
        )

        # For each prior donation, find all transfused units
        recipient_count = 0
        for donation in prior_donations:
            transfused_txs = IssueTransaction.objects.filter(
                blood_unit__donation=donation,
            ).select_related('patient', 'blood_unit')
            for tx in transfused_txs:
                LookbackNotification.objects.get_or_create(
                    campaign=campaign,
                    patient=tx.patient,
                    issue_tx=tx,
                    defaults={
                        'unit_did': tx.blood_unit.did,
                        'transfusion_date': tx.issued_at.date(),
                        'status': 'pending',
                    },
                )
                recipient_count += 1

        write_audit(
            actor=request.user,
            action='lookback.campaign.initiated',
            entity_table='transfusion_lookbackcampaign',
            entity_id=campaign.pk,
            after={
                'donor': donor.pk,
                'test': reactive_result.test.test_code,
                'window_days': window_days,
                'lookback_from': str(lookback_from),
                'recipients_identified': recipient_count,
            },
        )

        if recipient_count == 0:
            messages.warning(request,
                f"Lookback campaign LB-{campaign.pk} created. "
                f"No transfused units found in the window period ({lookback_from} to {reactive_donation_date}).")
        else:
            messages.warning(request,
                f"Lookback campaign LB-{campaign.pk} initiated. "
                f"{recipient_count} recipient notification(s) created — requires urgent follow-up.")

        return redirect('transfusion:lookback_detail', pk=campaign.pk)

    # GET: show initiation form with reactive results available for this branch
    branch_id = request.session.get('branch_id')
    reactive_results = DonationTestResult.objects.filter(
        result='reactive',
        donation__branch_id=branch_id,
    ).select_related('donation__donor', 'test').order_by('-performed_at')[:100]

    # Exclude results already linked to a lookback campaign
    existing_campaign_tests = set(
        LookbackCampaign.objects.filter(
            donor__registration_branch_id=branch_id
        ).values_list('triggered_by_test', flat=True)
    )

    return render(request, 'transfusion/lookback_initiate.html', {
        'reactive_results': reactive_results,
        'existing_campaign_tests': existing_campaign_tests,
        'window_days': WINDOW_DAYS,
    })


@login_required
def lookback_detail(request, pk):
    campaign = get_object_or_404(LookbackCampaign, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'close':
            campaign.status = 'closed'
            campaign.closed_at = timezone.now()
            campaign.closed_by = request.user
            campaign.save(update_fields=['status', 'closed_at', 'closed_by'])
            write_audit(
                actor=request.user,
                action='lookback.campaign.closed',
                entity_table='transfusion_lookbackcampaign',
                entity_id=campaign.pk,
                after={'status': 'closed'},
            )
            messages.success(request, f"Lookback campaign #{campaign.pk} closed.")
            return redirect('transfusion:lookback_list')

    notifications = campaign.notifications.select_related('patient', 'notified_by', 'issue_tx').order_by('status')
    pending_count = notifications.filter(status='pending').count()
    return render(request, 'transfusion/lookback_detail.html', {
        'campaign': campaign,
        'notifications': notifications,
        'pending_count': pending_count,
    })


@login_required
def update_notification(request, pk, notif_pk):
    campaign = get_object_or_404(LookbackCampaign, pk=pk)
    notif = get_object_or_404(LookbackNotification, pk=notif_pk, campaign=campaign)

    if request.method == 'POST':
        new_status = request.POST.get('status')
        notif.status = new_status
        notif.notes = request.POST.get('notes', notif.notes)
        notif.clinician_name = request.POST.get('clinician_name', notif.clinician_name)
        if new_status == 'notified' and not notif.notified_at:
            notif.notified_at = timezone.now()
            notif.notified_by = request.user
        notif.save()

        # Auto-update campaign status if all notified
        all_done = not campaign.notifications.filter(status='pending').exists()
        if all_done and campaign.status == 'open':
            campaign.status = 'notified'
            campaign.save(update_fields=['status'])
            write_audit(
                actor=request.user,
                action='lookback.campaign.all_notified',
                entity_table='transfusion_lookbackcampaign',
                entity_id=campaign.pk,
                after={'status': 'notified'},
            )

        write_audit(
            actor=request.user,
            action='lookback.notification.updated',
            entity_table='transfusion_lookbacknotification',
            entity_id=notif.pk,
            after={'status': new_status, 'campaign': campaign.pk},
        )
        messages.success(request, f"Notification status updated to '{notif.get_status_display()}'.")
    return redirect('transfusion:lookback_detail', pk=pk)


@login_required
def record_donation_blood_grouping(request, donation_pk):
    """
    Record ABO + Rh D serological typing for a donation sample.

    International workflow (AABB TM / BSH GL / WHO Blood Safety):
      1. Donation collected → blood in quarantine.
      2. Lab receives donation sample → performs forward (cell) + reverse (serum) ABO grouping
         AND Rh D typing.  If apparent Rh D negative → weak D (Du) test mandatory.
      3. Result entered here → ABO/Rh written onto ALL blood units from this donation.
      4. If this is donor's FIRST typing → status = 'first'; donor blood group set tentatively.
         A SECOND concordant typing (from same or later donation) → status = 'confirmed'.
      5. Discrepant results → investigation required before units can be released.
    """
    if not has_permission(request.user, 'donor.blood_group', request.session.get('branch_id')):
        messages.error(request, "Permission denied — Lab Technologist role required.")
        return redirect('core:dashboard')

    from donors.models import Donation

    donation = get_object_or_404(Donation, pk=donation_pk)
    donor = donation.donor
    existing_groupings = DonationBloodGrouping.objects.filter(donation=donation)
    prior_confirmed = DonationBloodGrouping.objects.filter(
        donation__donor=donor, determination_status='confirmed'
    ).exclude(donation=donation).exists()

    # Auto-find a donor screening sample for this donation so the form can pre-fill it
    donor_sample = Sample.objects.filter(
        donor=donor, sample_type='donor_screening'
    ).order_by('-collected_at').first()

    if request.method == 'POST':
        accession_no = request.POST.get('accession_number', '').strip()
        sample = get_object_or_404(Sample, accession_number=accession_no)

        if sample.donor_id and sample.donor_id != donor.pk:
            messages.error(request, "Sample does not belong to this donor.")
            return redirect('transfusion:donation_blood_grouping', donation_pk=donation_pk)

        abo_result  = request.POST['abo_result']
        rh_d_result = request.POST['rh_d_result']
        det_status  = request.POST.get('determination_status', 'first')

        # Check concordance with prior typing on the same donation
        if existing_groupings.filter(determination_status='first').exists():
            prev = existing_groupings.filter(determination_status='first').first()
            if prev.abo_result != abo_result or prev.rh_d_result != rh_d_result:
                det_status = 'discrepant'
                messages.warning(request,
                    f"DISCREPANT result: previous typing was {prev.abo_result} {prev.rh_d_result}, "
                    f"this result is {abo_result} {rh_d_result}. "
                    "Status set to DISCREPANT — investigation required before unit release.")
            elif prior_confirmed or det_status == 'confirmed':
                det_status = 'confirmed'

        grouping = DonationBloodGrouping.objects.create(
            donation=donation,
            sample=sample,
            forward_a=request.POST.get('forward_a', ''),
            forward_b=request.POST.get('forward_b', ''),
            reverse_a_cells=request.POST.get('reverse_a_cells', ''),
            reverse_b_cells=request.POST.get('reverse_b_cells', ''),
            abo_result=abo_result,
            rh_d_result=rh_d_result,
            weak_d_test_done=request.POST.get('weak_d_test_done') == '1',
            method=request.POST['method'],
            reagent_lot=request.POST.get('reagent_lot', ''),
            instrument=request.POST.get('instrument', ''),
            determination_status=det_status,
            notes=request.POST.get('notes', ''),
            performed_by=request.user,
            performed_at=timezone.now(),
        )

        write_audit(
            actor=request.user,
            action='donation.blood_grouping',
            entity_table='transfusion_donationbloodgrouping',
            entity_id=grouping.pk,
            after={
                'donation_id': donation.pk,
                'abo': abo_result,
                'rh_d': rh_d_result,
                'determination_status': det_status,
            },
        )

        unit_count = 0
        if det_status == 'discrepant':
            messages.error(request,
                f"Blood grouping recorded as DISCREPANT — blood units NOT updated. "
                "Resolve discrepancy before releasing units.")
        else:
            # Propagate ABO/Rh to all blood units from this donation
            unit_count = donation.units.update(abo_type=abo_result, rh_d_type=rh_d_result)
            # Update donor's own blood group record
            donor.blood_group_abo = abo_result
            donor.blood_group_rh = rh_d_result
            donor.save(update_fields=['blood_group_abo', 'blood_group_rh'])
            messages.success(request,
                f"Blood group {abo_result} {'Rh+' if rh_d_result == 'pos' else 'Rh−' if rh_d_result == 'neg' else 'Weak D'} "
                f"recorded and propagated to {unit_count} blood unit(s). "
                f"Status: {grouping.get_determination_status_display()}.")

        return redirect('donors:detail', pk=donor.pk)

    return render(request, 'transfusion/donation_blood_grouping.html', {
        'donation': donation,
        'donor': donor,
        'existing_groupings': existing_groupings,
        'prior_confirmed': prior_confirmed,
        'donor_sample': donor_sample,
        'methods': DonationBloodGrouping.METHODS,
    })


@login_required
def neonatal_order_create(request, request_pk):
    """Create a neonatal transfusion order linked to a blood request."""
    req = get_object_or_404(BloodRequest, pk=request_pk)
    from .models import NeonatalTransfusionOrder

    if hasattr(req, 'neonatal_order'):
        messages.info(request, "A neonatal order already exists for this request.")
        return redirect('transfusion:neonatal_order_detail', pk=req.neonatal_order.pk)

    if not req.is_neonatal:
        req.is_neonatal = True
        req.save(update_fields=['is_neonatal'])

    if request.method == 'POST':
        try:
            weight_kg = float(request.POST['weight_kg'])
        except (ValueError, KeyError):
            messages.error(request, "Valid patient weight is required.")
            return redirect('transfusion:neonatal_order_create', request_pk=request_pk)

        indication = request.POST.get('indication', 'top_up')
        max_age = request.POST.get('max_unit_age_days', '').strip()
        maternal_ab_raw = request.POST.get('maternal_antibodies', '').strip()
        maternal_ab = [a.strip() for a in maternal_ab_raw.split(',') if a.strip()] if maternal_ab_raw else []

        order = NeonatalTransfusionOrder.objects.create(
            patient=req.patient,
            blood_request=req,
            gestational_age_weeks=request.POST.get('gestational_age_weeks') or None,
            postnatal_age_days=_safe_int(request.POST.get('postnatal_age_days')) or 0,
            weight_kg=weight_kg,
            indication=indication,
            maternal_abo=request.POST.get('maternal_abo', ''),
            maternal_rh_d=request.POST.get('maternal_rh_d', ''),
            maternal_antibodies=maternal_ab,
            irradiation_required=request.POST.get('irradiation_required') == '1',
            cmv_negative_required=request.POST.get('cmv_negative_required') == '1',
            leukoreduced_required=request.POST.get('leukoreduced_required') == '1',
            max_unit_age_days=_safe_int(max_age) if max_age else None,
            notes=request.POST.get('notes', ''),
            created_by=request.user,
        )
        write_audit(
            actor=request.user,
            action='neonatal_order.create',
            entity_table='transfusion_neonataltransfusionorder',
            entity_id=order.pk,
            after={
                'request_id': req.pk,
                'indication': indication,
                'weight_kg': str(weight_kg),
                'irradiation': order.irradiation_required,
                'cmv_neg': order.cmv_negative_required,
            },
        )
        messages.success(request,
            f"Neonatal order created. Max volume: {order.max_volume_ml:.0f} mL. "
            "Units must be irradiated, CMV-negative, and leukoreduced (per AABB/BSH).")
        return redirect('transfusion:neonatal_order_detail', pk=order.pk)

    return render(request, 'transfusion/neonatal_order_form.html', {
        'req': req,
        'indications': NeonatalTransfusionOrder.INDICATIONS,
        'abo_choices': [('A','A'), ('B','B'), ('AB','AB'), ('O','O')],
        'rh_choices': [('pos','D Positive'), ('neg','D Negative')],
    })


@login_required
def neonatal_order_detail(request, pk):
    """Show a neonatal transfusion order with unit eligibility checker."""
    from .models import NeonatalTransfusionOrder
    from inventory.models import BloodUnit
    order = get_object_or_404(NeonatalTransfusionOrder, pk=pk)

    eligible_units = []
    ineligible_units = []
    for unit in BloodUnit.objects.filter(
        status='available',
        owner_branch=order.blood_request.branch,
        component_class=order.blood_request.component_class,
    ).order_by('expiry_datetime')[:50]:
        ok, reasons = order.unit_eligible(unit)
        if ok:
            eligible_units.append(unit)
        else:
            ineligible_units.append({'unit': unit, 'reasons': reasons})

    return render(request, 'transfusion/neonatal_order_detail.html', {
        'order': order,
        'eligible_units': eligible_units[:10],
        'ineligible_units': ineligible_units[:10],
    })


@login_required
def haemovigilance_dashboard(request):
    """
    Haemovigilance dashboard — aggregates transfusion reaction data by type/severity/period.
    Meets SHOT/FDA/EBA reporting requirements: numerator/denominator, imputability grading.
    """
    from django.db.models import Count, Q
    from datetime import timedelta

    branch_id = request.session.get('branch_id')

    days = _safe_int(request.GET.get('days')) or 90
    cutoff = timezone.now() - timedelta(days=days)

    type_filter = request.GET.get('type', '')
    severity_filter = request.GET.get('severity', '')

    qs = TransfusionReaction.objects.filter(
        blood_unit__owner_branch_id=branch_id,
        recorded_at__gte=cutoff,
    )
    if type_filter:
        qs = qs.filter(reaction_type=type_filter)
    if severity_filter:
        qs = qs.filter(severity=severity_filter)

    reactions = qs.select_related('patient', 'blood_unit', 'recorded_by').order_by('-onset_datetime')

    # Denominator: transfusions issued in same period
    total_issues = IssueTransaction.objects.filter(
        intended_branch_id=branch_id,
        issued_at__gte=cutoff,
    ).count()

    # By type
    by_type = list(
        qs.values('reaction_type').annotate(count=Count('pk')).order_by('-count')
    )
    # By severity
    by_severity = list(
        qs.values('severity').annotate(count=Count('pk')).order_by('severity')
    )
    # Serious reactions (grade 3+)
    serious = qs.filter(severity__in=['grade_3', 'grade_4', 'grade_5'])
    # Fatalities
    fatal = qs.filter(severity='grade_5').count()
    # Unreported serious
    unreported_serious = serious.filter(reported_to_authority=False).count()

    # Reaction rate per 1000 transfusions
    reaction_rate = round((qs.count() / total_issues * 1000), 2) if total_issues else 0

    paginator = Paginator(reactions, 25)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'transfusion/haemovigilance_dashboard.html', {
        'page_obj': page,
        'days': days,
        'type_filter': type_filter,
        'severity_filter': severity_filter,
        'total_reactions': qs.count(),
        'total_issues': total_issues,
        'reaction_rate': reaction_rate,
        'serious_count': serious.count(),
        'fatal_count': fatal,
        'unreported_serious': unreported_serious,
        'by_type': by_type,
        'by_severity': by_severity,
        'reaction_types': TransfusionReaction.REACTION_TYPES,
        'severity_choices': TransfusionReaction.SEVERITY,
    })


@login_required
def mtp_activate(request):
    """
    Activate Massive Transfusion Protocol.
    Issues O-neg RBC + AB FFP (universal donors) without waiting for crossmatch.
    Requires physician e-signature.
    """
    from .models import MTPActivation
    from patients.models import Patient

    if request.method == 'POST':
        patient_id = request.POST.get('patient_id')
        if not patient_id:
            messages.error(request, "Patient ID is required to activate MTP.")
            return redirect('transfusion:mtp_activate')

        patient = get_object_or_404(Patient, pk=patient_id)
        branch_id = request.session.get('branch_id')

        mtp = MTPActivation.objects.create(
            patient=patient,
            branch_id=branch_id,
            trigger_type=request.POST.get('trigger_type', 'other'),
            activated_at=timezone.now(),
            activated_by=request.user,
            status='active',
            clinical_notes=request.POST.get('clinical_notes', ''),
        )

        write_audit(
            actor=request.user,
            action='mtp.activate',
            entity_table='transfusion_mtpactivation',
            entity_id=mtp.pk,
            after={
                'patient_id': patient.pk,
                'trigger': mtp.trigger_type,
            },
        )

        # Pre-allocate O-neg RBC units (up to 6) for MTP first pack
        from inventory.models import BloodUnit
        oneg_units = BloodUnit.objects.filter(
            owner_branch_id=branch_id,
            component_class='RBC',
            abo_type='O',
            rh_d_type='neg',
            status='available',
            expiry_datetime__gt=timezone.now(),
        ).order_by('expiry_datetime')[:6]

        oneg_count = oneg_units.count()
        if oneg_count < 6:
            messages.warning(request,
                f"MTP activated (#{mtp.pk}) — only {oneg_count} O-neg RBC available (need 6 for Pack 1). "
                "Consider emergency cross-site transfer for additional O-neg stock.")
        else:
            messages.success(request,
                f"MTP #{mtp.pk} ACTIVATED for Patient #{patient.pk}. "
                f"Universal O-neg RBC pre-identified: {oneg_count} units. "
                "Issue via emergency release. Complete retrospective XM when patient stable.")

        return redirect('transfusion:mtp_detail', pk=mtp.pk)

    from patients.models import Patient
    return render(request, 'transfusion/mtp_activate.html', {
        'trigger_types': MTPActivation.TRIGGER_TYPES,
    })


@login_required
def mtp_detail(request, pk):
    """View MTP activation record and update its status."""
    from .models import MTPActivation
    mtp = get_object_or_404(MTPActivation, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'stand_down':
            mtp.status = 'stand_down'
            mtp.stand_down_at = timezone.now()
            mtp.save(update_fields=['status', 'stand_down_at'])
            messages.success(request, f"MTP #{mtp.pk} stood down at {mtp.stand_down_at:%H:%M}.")
        elif action == 'complete':
            mtp.status = 'completed'
            mtp.patient_survived = request.POST.get('patient_survived') == '1'
            mtp.retrospective_xm_completed = request.POST.get('retro_xm') == '1'
            mtp.reviewed_by = request.user
            mtp.rbc_units_issued = _safe_int(request.POST.get('rbc_issued')) or 0
            mtp.ffp_units_issued = _safe_int(request.POST.get('ffp_issued')) or 0
            mtp.plt_units_issued = _safe_int(request.POST.get('plt_issued')) or 0
            mtp.cryo_units_issued = _safe_int(request.POST.get('cryo_issued')) or 0
            mtp.clinical_notes = request.POST.get('clinical_notes', mtp.clinical_notes)
            mtp.save(update_fields=[
                'status', 'patient_survived', 'retrospective_xm_completed', 'reviewed_by',
                'rbc_units_issued', 'ffp_units_issued', 'plt_units_issued', 'cryo_units_issued',
                'clinical_notes',
            ])
            write_audit(
                actor=request.user,
                action='mtp.complete',
                entity_table='transfusion_mtpactivation',
                entity_id=mtp.pk,
                after={'status': 'completed', 'survived': mtp.patient_survived},
            )
            messages.success(request, f"MTP #{mtp.pk} completed and documented.")
        return redirect('transfusion:mtp_detail', pk=pk)

    # Get related emergency releases and issue transactions for this patient during MTP
    related_issues = IssueTransaction.objects.filter(
        patient=mtp.patient,
        issued_at__gte=mtp.activated_at,
    ).select_related('blood_unit').order_by('issued_at')

    return render(request, 'transfusion/mtp_detail.html', {
        'mtp': mtp,
        'related_issues': related_issues,
    })


@login_required
def mtp_list(request):
    """List MTP activations at this branch."""
    from .models import MTPActivation
    branch_id = request.session.get('branch_id')
    activations = MTPActivation.objects.filter(branch_id=branch_id).select_related(
        'patient', 'activated_by'
    ).order_by('-activated_at')
    status_filter = request.GET.get('status', '')
    if status_filter:
        activations = activations.filter(status=status_filter)
    paginator = Paginator(activations, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'transfusion/mtp_list.html', {
        'page_obj': page,
        'status_filter': status_filter,
        'statuses': MTPActivation.STATUSES,
    })


@login_required
def guideline_check(request, request_pk):
    """
    Pre-transfusion Clinical Decision Support — records clinical trigger parameters
    and evaluates whether the request meets WHO/AABB/BCSH guideline thresholds.
    """
    from .guidelines import check_transfusion_guideline
    blood_request = get_object_or_404(BloodRequest, pk=request_pk)

    # If already assessed, show the existing result
    existing = getattr(blood_request, 'guideline_check', None)

    if request.method == 'POST':
        indication    = request.POST.get('clinical_indication', 'other')
        is_bleeding   = request.POST.get('is_actively_bleeding') == 'on'
        is_icu        = request.POST.get('is_critical_care') == 'on'
        is_cardiac    = request.POST.get('is_cardiac_surgery') == 'on'
        is_ortho      = request.POST.get('is_orthopaedic') == 'on'
        is_neuro      = request.POST.get('is_neurosurgery') == 'on'
        is_obstetric  = request.POST.get('is_obstetric') == 'on'
        override_just = request.POST.get('override_justification', '').strip()

        def _dec(key):
            v = request.POST.get(key, '').strip()
            return v if v else None

        def _int_val(key):
            v = request.POST.get(key, '').strip()
            return int(v) if v else None

        hb         = _dec('pre_transfusion_hb_g_dl')
        plt        = _int_val('pre_transfusion_plt_per_nl')
        fibrinogen = _dec('pre_transfusion_fibrinogen_g_l')
        pt_ratio   = _dec('pt_ratio')
        aptt_ratio = _dec('aptt_ratio')

        result = check_transfusion_guideline(
            blood_request.component_class,
            pre_transfusion_hb_g_dl=hb,
            pre_transfusion_plt_per_nl=plt,
            pre_transfusion_fibrinogen_g_l=fibrinogen,
            pt_ratio=pt_ratio,
            aptt_ratio=aptt_ratio,
            is_actively_bleeding=is_bleeding,
            is_critical_care=is_icu,
            is_cardiac_surgery=is_cardiac,
            is_orthopaedic=is_ortho,
            is_neurosurgery=is_neuro,
            is_obstetric=is_obstetric,
            clinical_indication=indication,
        )

        if not result['meets_guideline'] and not override_just:
            messages.error(request,
                "Transfusion does not meet guideline thresholds. "
                "A clinical override justification is required.")
            return render(request, 'transfusion/guideline_check.html', {
                'blood_request': blood_request,
                'indications': TransfusionGuidelineCheck.INDICATIONS,
                'result': result,
                'flags': [f.to_dict() for f in result['flags']],
                'post_data': request.POST,
            })

        check = TransfusionGuidelineCheck.objects.update_or_create(
            request=blood_request,
            defaults=dict(
                clinical_indication=indication,
                is_actively_bleeding=is_bleeding,
                is_critical_care=is_icu,
                is_cardiac_surgery=is_cardiac,
                is_orthopaedic=is_ortho,
                is_neurosurgery=is_neuro,
                is_obstetric=is_obstetric,
                pre_transfusion_hb_g_dl=hb,
                pre_transfusion_plt_per_nl=plt,
                pre_transfusion_fibrinogen_g_l=fibrinogen,
                pt_ratio=pt_ratio,
                aptt_ratio=aptt_ratio,
                meets_guideline=result['meets_guideline'],
                guideline_flags_json=[f.to_dict() for f in result['flags']],
                summary=result['summary'],
                override_justification=override_just,
                assessed_by=request.user,
            ),
        )[0]

        write_audit(
            actor=request.user,
            action='transfusion.guideline_check',
            entity_table='transfusion_transfusionguidelinecheck',
            entity_id=check.pk,
            after={'request_pk': request_pk, 'meets_guideline': result['meets_guideline']},
        )

        if result['meets_guideline']:
            messages.success(request, "Guideline check recorded — transfusion meets clinical thresholds.")
        else:
            messages.warning(request,
                "Non-compliant guideline check recorded. Override justification noted.")

        return redirect('transfusion:request_detail', pk=request_pk)

    return render(request, 'transfusion/guideline_check.html', {
        'blood_request': blood_request,
        'existing':      existing,
        'indications':   TransfusionGuidelineCheck.INDICATIONS,
    })


@login_required
def appropriateness_report(request):
    """
    Transfusion Appropriateness Report — CDS compliance summary for the branch.
    Shows what percentage of requests had guideline checks and compliance rates.
    """
    from django.db.models import Count, Q
    from datetime import timedelta as _td

    branch_id = request.session.get('branch_id')
    days = _safe_int(request.GET.get('days')) or 30
    cutoff = timezone.now() - _td(days=days)

    # Total requests in period
    total_requests = BloodRequest.objects.filter(
        branch_id=branch_id,
        requested_ts__gte=cutoff,
    )
    total_count = total_requests.count()

    # Requests with guideline check recorded
    checked_qs = TransfusionGuidelineCheck.objects.filter(
        request__branch_id=branch_id,
        assessed_at__gte=cutoff,
    )
    checked_count = checked_qs.count()
    compliant_count = checked_qs.filter(meets_guideline=True).count()
    non_compliant_count = checked_qs.filter(meets_guideline=False).count()

    # Breakdown by component
    by_component = (
        checked_qs
        .values('request__component_class')
        .annotate(
            total=Count('pk'),
            compliant=Count('pk', filter=Q(meets_guideline=True)),
        )
        .order_by('request__component_class')
    )

    # Breakdown by indication
    by_indication = (
        checked_qs
        .values('clinical_indication')
        .annotate(
            total=Count('pk'),
            compliant=Count('pk', filter=Q(meets_guideline=True)),
        )
        .order_by('-total')
    )

    # Non-compliant requests (last 20)
    non_compliant_requests = (
        checked_qs
        .filter(meets_guideline=False)
        .select_related('request', 'assessed_by')
        .order_by('-assessed_at')[:20]
    )

    coverage_pct = round(checked_count / total_count * 100, 1) if total_count else 0
    compliance_pct = round(compliant_count / checked_count * 100, 1) if checked_count else 0

    indication_labels = dict(TransfusionGuidelineCheck.INDICATIONS)
    by_indication_resolved = [
        {**row, 'label': indication_labels.get(row['clinical_indication'], row['clinical_indication'])}
        for row in by_indication
    ]

    return render(request, 'transfusion/appropriateness_report.html', {
        'days':                  days,
        'total_requests':        total_count,
        'checked_count':         checked_count,
        'compliant_count':       compliant_count,
        'non_compliant_count':   non_compliant_count,
        'coverage_pct':          coverage_pct,
        'compliance_pct':        compliance_pct,
        'by_component':          list(by_component),
        'by_indication':         by_indication_resolved,
        'non_compliant_requests': non_compliant_requests,
    })


@login_required
def bedside_pwa(request):
    """
    Standalone bedside verification PWA shell.
    Injects the user's API token so the ZXing scanner can POST to
    /api/v1/bedside/verify/ without a separate login step.
    """
    from rest_framework.authtoken.models import Token
    token, _ = Token.objects.get_or_create(user=request.user)
    return render(request, 'transfusion/bedside_pwa.html', {'api_token': token.key})


@login_required
def dose_calculator(request):
    """
    Transfusion dose calculator for neonates and adults.
    Provides weight-based volume calculations for RBC, PLT, FFP, CRYO.
    References: AABB Standards; BSH Guidelines; British National Formulary.
    """
    results = None
    if request.method == 'POST':
        try:
            weight_kg = float(request.POST.get('weight_kg', '') or 0)
        except ValueError:
            weight_kg = 0

        component = request.POST.get('component', 'RBC')
        pre_hb     = _safe_float(request.POST.get('pre_hb', ''))
        target_hb  = _safe_float(request.POST.get('target_hb', ''))
        pre_plt    = _safe_int(request.POST.get('pre_plt', ''))
        target_plt = _safe_int(request.POST.get('target_plt', ''))
        pre_fib    = _safe_float(request.POST.get('pre_fib', ''))
        pre_pt     = _safe_float(request.POST.get('pre_pt', ''))
        is_neonate = request.POST.get('is_neonate') == 'on'

        results = {}

        if component == 'RBC' and weight_kg > 0:
            # BSH neonatal: 10-20 mL/kg; adult empirical: 1 unit raises Hb ~1 g/dL per unit (70 kg adult)
            if is_neonate:
                dose_lo = round(weight_kg * 10)
                dose_hi = round(weight_kg * 20)
                results['rbc_volume_ml'] = f'{dose_lo}–{dose_hi} mL (10–20 mL/kg)'
                results['rbc_note'] = 'Neonatal/paediatric: 10 mL/kg for top-up; up to 20 mL/kg for severe anaemia. Max rate 5 mL/kg/h.'
            else:
                # Adult: Expected ΔHb = (ΔHb target) × weight × 0.24 / Hct of unit (assume 0.65)
                if pre_hb and target_hb and target_hb > pre_hb:
                    units_needed = round((target_hb - pre_hb) / 1.0)
                    results['rbc_units_estimate'] = f'{units_needed} unit(s)'
                    results['rbc_note'] = 'Adult estimate: ~1 g/dL increment per RBC unit (average 70 kg patient). Recheck Hb 15 min after transfusion.'
                else:
                    results['rbc_note'] = 'Enter pre and target Hb to estimate units needed.'

        elif component == 'PLT' and weight_kg > 0:
            if is_neonate:
                dose_lo = round(weight_kg * 10)
                dose_hi = round(weight_kg * 20)
                results['plt_volume_ml'] = f'{dose_lo}–{dose_hi} mL (10–20 mL/kg)'
                results['plt_note'] = 'Neonatal platelets: 10 mL/kg raises count by ~50–100 ×10⁹/L. Re-check 1-hour CCI.'
            else:
                # Adult: 1 adult therapeutic dose (ATD) typically raises count by 20–50 ×10⁹/L
                if pre_plt and target_plt and target_plt > pre_plt:
                    increment_needed = target_plt - pre_plt
                    # CCI target: >7500 at 1h; >4500 at 18-24h
                    atd_estimate = max(1, round(increment_needed / 30))
                    results['plt_atd_estimate'] = f'~{atd_estimate} ATD (Adult Therapeutic Dose)'
                    results['plt_note'] = 'Each ATD raises count by ~20–50 ×10⁹/L; highly variable. Aim 1-hour CCI >7500.'
                else:
                    results['plt_note'] = 'Enter pre and target platelet count to estimate ATD needed.'

        elif component == 'FFP' and weight_kg > 0:
            dose_lo = round(weight_kg * 12)
            dose_hi = round(weight_kg * 15)
            results['ffp_volume_ml'] = f'{dose_lo}–{dose_hi} mL ({12}–{15} mL/kg)'
            if is_neonate:
                results['ffp_note'] = 'Neonatal FFP: 12–15 mL/kg. Check PT/APTT <1.5× normal before issuing.'
            else:
                results['ffp_note'] = 'Adult FFP: 12–15 mL/kg. Expect ~20% reduction in PT/APTT. Reassess post-infusion.'

        elif component == 'CRYO' and weight_kg > 0:
            if is_neonate:
                # Neonatal: 5-10 mL/kg fibrinogen concentrate/cryo
                dose_lo = round(weight_kg * 5)
                dose_hi = round(weight_kg * 10)
                results['cryo_volume_ml'] = f'{dose_lo}–{dose_hi} mL (5–10 mL/kg)'
                results['cryo_note'] = 'Neonatal cryoprecipitate: 5 mL/kg raises fibrinogen by ~1 g/L.'
            else:
                # Adult: empirical 1 pool of 5-unit cryo raises fibrinogen by ~0.5–1.0 g/L
                if pre_fib:
                    deficit = max(0, 2.0 - pre_fib)
                    pools = round(deficit / 0.75)
                    results['cryo_pools_estimate'] = f'~{max(1, pools)} pool(s)' if pools > 0 else '1 pool (minimum)'
                    results['cryo_note'] = f'Pre-fibrinogen {pre_fib} g/L → target ≥2.0 g/L. Each pool (~5 units) raises by ~0.5–1.0 g/L in 70 kg adult.'
                else:
                    results['cryo_note'] = 'Adult: 1 pool (5 units) raises fibrinogen ~0.5–1.0 g/L. Target ≥1.5 g/L (≥2.0 in PPH/massive haemorrhage).'

        results['component'] = component
        results['weight_kg'] = weight_kg

    return render(request, 'transfusion/dose_calculator.html', {
        'results': results,
        'components': [
            ('RBC', 'Red Blood Cells'),
            ('PLT', 'Platelets'),
            ('FFP', 'Fresh Frozen Plasma'),
            ('CRYO', 'Cryoprecipitate'),
        ],
    })


def _safe_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


@login_required
def record_post_outcome(request, request_pk):
    """
    Record the post-transfusion Hb response (PBM Programme completion).
    Should be done 24–48 h after the final unit. AABB PBM Toolkit / NHS GIRFT.
    """
    blood_request = get_object_or_404(BloodRequest, pk=request_pk)

    existing = getattr(blood_request, 'post_outcome', None)

    gc = getattr(blood_request, 'guideline_check', None)
    pre_hb = gc.pre_transfusion_hb_g_dl if gc else None

    if request.method == 'POST':
        post_hb_raw = request.POST.get('post_hb_g_dl', '').strip()
        post_hb = None
        if post_hb_raw:
            try:
                post_hb = float(post_hb_raw)
            except ValueError:
                messages.error(request, "Invalid Hb value.")
                return redirect('transfusion:record_post_outcome', request_pk=request_pk)

        post_hb_date_raw = request.POST.get('post_hb_date', '').strip() or None
        if post_hb_date_raw:
            from django.utils.dateparse import parse_date
            post_hb_date_val = parse_date(post_hb_date_raw)
            if post_hb_date_val is None:
                messages.error(request, f"Invalid post-Hb date: '{post_hb_date_raw}'.")
                return redirect('transfusion:record_post_outcome', request_pk=request_pk)
        else:
            post_hb_date_val = None

        outcome, created = PostTransfusionOutcome.objects.update_or_create(
            request=blood_request,
            defaults=dict(
                patient=blood_request.patient,
                post_hb_g_dl=post_hb,
                post_hb_date=post_hb_date_val,
                clinical_response=request.POST.get('clinical_response', ''),
                further_transfusion_planned=request.POST.get('further_transfusion_planned') == 'on',
                reaction_occurred=request.POST.get('reaction_occurred') == 'on',
                notes=request.POST.get('notes', '').strip(),
                recorded_by=request.user,
            ),
        )

        write_audit(
            actor=request.user,
            action='transfusion.post_outcome.record',
            entity_table='transfusion_posttransfusionoutcome',
            entity_id=outcome.pk,
            after={
                'request_pk': request_pk,
                'post_hb_g_dl': str(post_hb),
                'clinical_response': outcome.clinical_response,
            },
        )
        messages.success(request, "Post-transfusion outcome recorded.")
        return redirect('transfusion:request_detail', pk=request_pk)

    return render(request, 'transfusion/post_outcome_form.html', {
        'blood_request':  blood_request,
        'existing':       existing,
        'pre_hb':         pre_hb,
        'responses':      PostTransfusionOutcome.RESPONSES,
    })


@login_required
def pbm_dashboard(request):
    """
    Patient Blood Management (PBM) compliance dashboard.
    Tracks pre-Hb documentation, guideline compliance, and post-Hb increment.
    Reference: NHS GIRFT Blood Programme; AABB PBM implementation guide.
    """
    from django.db.models import Count, Avg, Q
    from datetime import timedelta as _td
    from decimal import Decimal

    branch_id = request.session.get('branch_id')
    days = _safe_int(request.GET.get('days')) or 30
    cutoff = timezone.now() - _td(days=days)

    rbc_requests = BloodRequest.objects.filter(
        branch_id=branch_id,
        requested_ts__gte=cutoff,
        component_class='RBC',
    )
    total_rbc = rbc_requests.count()

    # Guideline check coverage
    rbc_with_check = rbc_requests.filter(guideline_check__isnull=False).count()
    rbc_compliant  = rbc_requests.filter(guideline_check__meets_guideline=True).count()
    rbc_with_outcome = rbc_requests.filter(post_outcome__isnull=False).count()

    coverage_pct  = round(rbc_with_check  / total_rbc * 100, 1) if total_rbc else 0
    compliance_pct = round(rbc_compliant  / rbc_with_check * 100, 1) if rbc_with_check else 0
    outcome_pct   = round(rbc_with_outcome / total_rbc * 100, 1) if total_rbc else 0

    # Average Hb increment where both pre and post are documented
    increments = []
    for req in (
        rbc_requests
        .filter(
            guideline_check__pre_transfusion_hb_g_dl__isnull=False,
            post_outcome__post_hb_g_dl__isnull=False,
        )
        .select_related('guideline_check', 'post_outcome')
    ):
        delta = float(req.post_outcome.post_hb_g_dl) - float(req.guideline_check.pre_transfusion_hb_g_dl)
        increments.append(delta)

    avg_increment = round(sum(increments) / len(increments), 2) if increments else None

    # Trigger distribution (pre-Hb bands)
    trigger_bands = {'<7': 0, '7-8': 0, '8-10': 0, '>10': 0}
    for gc in (
        TransfusionGuidelineCheck.objects.filter(
            request__branch_id=branch_id,
            request__component_class='RBC',
            assessed_at__gte=cutoff,
            pre_transfusion_hb_g_dl__isnull=False,
        ).values_list('pre_transfusion_hb_g_dl', flat=True)
    ):
        hb = float(gc)
        if hb < 7:
            trigger_bands['<7'] += 1
        elif hb < 8:
            trigger_bands['7-8'] += 1
        elif hb < 10:
            trigger_bands['8-10'] += 1
        else:
            trigger_bands['>10'] += 1

    # Recent non-compliant requests
    non_compliant = (
        TransfusionGuidelineCheck.objects
        .filter(
            request__branch_id=branch_id,
            request__component_class='RBC',
            assessed_at__gte=cutoff,
            meets_guideline=False,
        )
        .select_related('request', 'assessed_by')
        .order_by('-assessed_at')[:10]
    )

    # Recent below-expected outcomes
    below_expected = (
        PostTransfusionOutcome.objects
        .filter(
            request__branch_id=branch_id,
            recorded_at__gte=cutoff,
            clinical_response='below_expected',
        )
        .select_related('request', 'patient', 'recorded_by')
        .order_by('-recorded_at')[:10]
    )

    total_triggers = sum(trigger_bands.values())
    trigger_bands_list = [
        {'band': band, 'count': count, 'pct': round(count / total_triggers * 100) if total_triggers else 0}
        for band, count in trigger_bands.items()
    ]

    return render(request, 'transfusion/pbm_dashboard.html', {
        'days':               days,
        'total_rbc':          total_rbc,
        'rbc_with_check':     rbc_with_check,
        'rbc_compliant':      rbc_compliant,
        'rbc_with_outcome':   rbc_with_outcome,
        'coverage_pct':       coverage_pct,
        'compliance_pct':     compliance_pct,
        'outcome_pct':        outcome_pct,
        'avg_increment':      avg_increment,
        'trigger_bands_list': trigger_bands_list,
        'total_triggers':     total_triggers,
        'non_compliant':      non_compliant,
        'below_expected':     below_expected,
    })


@login_required
def post_outcome_list(request):
    """List of all recorded post-transfusion outcomes for the branch — PBM Programme."""
    from django.db.models import Avg
    branch_id = request.session.get('branch_id')
    qs = (
        PostTransfusionOutcome.objects
        .filter(request__branch_id=branch_id)
        .select_related('patient', 'request', 'recorded_by')
        .order_by('-recorded_at')
    )

    response_filter = request.GET.get('response', '')
    if response_filter:
        qs = qs.filter(clinical_response=response_filter)

    # Summary stats
    avg_post_hb = qs.filter(post_hb_g_dl__isnull=False).aggregate(avg=Avg('post_hb_g_dl'))['avg']
    below_count = qs.filter(clinical_response='below_expected').count()
    reaction_count = qs.filter(reaction_occurred=True).count()

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'transfusion/post_outcome_list.html', {
        'page_obj': page,
        'response_filter': response_filter,
        'response_choices': PostTransfusionOutcome.RESPONSES,
        'avg_post_hb': round(float(avg_post_hb), 1) if avg_post_hb else None,
        'below_count': below_count,
        'reaction_count': reaction_count,
        'total': qs.count(),
    })


# ─── Surgical Blood Orders ────────────────────────────────────────────────────

@login_required
def surgical_order_list(request):
    branch_id = request.session.get('branch_id')
    orders = (SurgicalBloodOrder.objects
              .filter(branch_id=branch_id)
              .select_related('patient', 'surgeon', 'approved_by')
              .order_by('scheduled_datetime'))
    return render(request, 'transfusion/surgical_order_list.html', {'orders': orders})


@login_required
def surgical_order_create(request, patient_pk):
    from patients.models import Patient
    patient = get_object_or_404(Patient, pk=patient_pk)
    branch_id = request.session.get('branch_id')

    if request.method == 'POST':
        from django.utils.dateparse import parse_datetime
        proc_code = request.POST.get('procedure_code', '').strip()
        sched_str = request.POST.get('scheduled_datetime', '').strip()
        sched = parse_datetime(sched_str) if sched_str else None
        if not proc_code or not sched:
            messages.error(request, 'Procedure code and scheduled date/time are required.')
        else:
            order = SurgicalBloodOrder.objects.create(
                patient=patient,
                branch_id=branch_id,
                procedure_code=proc_code,
                procedure_name=request.POST.get('procedure_name', ''),
                scheduled_datetime=sched,
                component_class=request.POST.get('component_class', 'RBC'),
                notes=request.POST.get('notes', ''),
                surgeon=request.user,
                created_by=request.user,
            )
            write_audit(
                actor=request.user, action='surgical_order.create',
                entity_table='transfusion_surgicalbloodorder', entity_id=order.pk,
                action_meaning=f'Surgical blood order created: {proc_code} for Patient #{patient.pk}',
            )
            messages.success(
                request,
                f"Surgical order #{order.pk} created"
                + (f" — MSBOS suggests {order.msbos_order_type} × {order.msbos_units_suggested}"
                   if order.msbos_matched else " — no MSBOS entry found for this procedure") + ".",
            )
            return redirect('transfusion:surgical_order_detail', pk=order.pk)

    # Pre-populate procedure_code from query string
    proc_code_hint = request.GET.get('procedure_code', '')
    msbos_hint = None
    if proc_code_hint:
        msbos_hint = MSBOS.objects.filter(
            procedure_code__iexact=proc_code_hint,
        ).filter(
            Q(branch_id=branch_id) | Q(branch__isnull=True)
        ).first()

    return render(request, 'transfusion/surgical_order_form.html', {
        'patient': patient,
        'proc_code_hint': proc_code_hint,
        'msbos_hint': msbos_hint,
        'component_classes': [('RBC','RBC'),('FFP','FFP'),('PLT','PLT'),('CRYO','CRYO')],
    })


@login_required
def surgical_order_detail(request, pk):
    branch_id = request.session.get('branch_id')
    order = get_object_or_404(
        SurgicalBloodOrder.objects.select_related(
            'patient', 'surgeon', 'approved_by', 'blood_request',
        ),
        pk=pk, branch_id=branch_id,
    )
    return render(request, 'transfusion/surgical_order_detail.html', {'order': order})


@login_required
def surgical_order_approve(request, pk):
    """Blood bank approves order — creates a BloodRequest and marks approved."""
    branch_id = request.session.get('branch_id')
    order = get_object_or_404(SurgicalBloodOrder, pk=pk, branch_id=branch_id)

    if order.status != 'pending':
        messages.warning(request, 'Order is not in pending status.')
        return redirect('transfusion:surgical_order_detail', pk=pk)

    if request.method == 'POST':
        approved_type = request.POST.get('approved_order_type', order.msbos_order_type)
        approved_units = _safe_int(request.POST.get('approved_units') or order.msbos_units_suggested) or 0

        if approved_type != 'none' and approved_units > 0:
            blood_request = BloodRequest.objects.create(
                patient=order.patient,
                branch_id=branch_id,
                component_class=order.component_class,
                units_requested=approved_units,
                urgency='routine',
                requesting_physician=order.surgeon,
            )
            order.blood_request = blood_request

        order.approved_order_type = approved_type
        order.approved_units = approved_units
        order.approved_by = request.user
        order.approved_at = timezone.now()
        order.status = 'approved'
        order.save(update_fields=[
            'approved_order_type', 'approved_units', 'approved_by',
            'approved_at', 'status', 'blood_request',
        ])
        write_audit(
            actor=request.user, action='surgical_order.approve',
            entity_table='transfusion_surgicalbloodorder', entity_id=order.pk,
            after={'approved_order_type': approved_type, 'approved_units': approved_units},
            action_meaning=f'Surgical order approved: {approved_type} × {approved_units}',
        )
        messages.success(request, f"Order approved. {approved_units} × {order.component_class} requested.")
        return redirect('transfusion:surgical_order_detail', pk=pk)

    return render(request, 'transfusion/surgical_order_approve.html', {
        'order': order,
        'order_type_choices': SurgicalBloodOrder.ORDER_TYPES,
    })


@login_required
def surgical_order_cancel(request, pk):
    branch_id = request.session.get('branch_id')
    order = get_object_or_404(SurgicalBloodOrder, pk=pk, branch_id=branch_id)
    if request.method == 'POST':
        if order.blood_request:
            order.blood_request.outcome = 'cancelled'
            order.blood_request.save(update_fields=['outcome'])
        order.status = 'cancelled'
        order.save(update_fields=['status'])
        write_audit(
            actor=request.user, action='surgical_order.cancel',
            entity_table='transfusion_surgicalbloodorder', entity_id=order.pk,
            action_meaning='Surgical blood order cancelled',
        )
        messages.info(request, 'Surgical blood order cancelled.')
        return redirect('transfusion:surgical_order_list')
    return render(request, 'transfusion/surgical_order_confirm_cancel.html', {'order': order})
