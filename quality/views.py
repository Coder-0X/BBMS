from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.core.paginator import Paginator

from .models import (
    Reagent, ReagentLot, QCRun, QCResult, EquipmentCalibration,
    NonConformance, CorrectiveAction, NewLotValidation, LotValidationResult,
    StandardOperatingProcedure, SOPVersion, InternalAudit, AuditFinding,
    StaffCompetency, TransfusionCommittee, CommitteeAction,
)
from accounts.permissions import has_permission
from audit.utils import write_audit


@login_required
def reagent_list(request):
    branch_id = request.session.get('branch_id')
    reagents = Reagent.objects.filter(active=True).prefetch_related('lots')
    reagent_status = []
    for r in reagents:
        lot = r.current_lot()
        reagent_status.append({
            'reagent': r,
            'lot': lot,
            'qc_status': r.qc_status(branch_id),
            'lot_expired': lot.is_expired() if lot else None,
        })
    return render(request, 'quality/reagent_list.html', {
        'reagent_status': reagent_status,
    })


@login_required
def reagent_detail(request, pk):
    reagent = get_object_or_404(Reagent, pk=pk)
    lots = reagent.lots.order_by('-created_at')[:10]
    recent_qc = reagent.qc_runs.order_by('-completed_at')[:20]
    return render(request, 'quality/reagent_detail.html', {
        'reagent': reagent,
        'lots': lots,
        'recent_qc': recent_qc,
        'current_lot': reagent.current_lot(),
    })


@login_required
def register_lot(request, reagent_pk):
    reagent = get_object_or_404(Reagent, pk=reagent_pk)
    if not has_permission(request.user, 'reagent.manage', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('quality:reagent_detail', pk=reagent_pk)

    if request.method == 'POST':
        lot = ReagentLot.objects.create(
            reagent=reagent,
            lot_number=request.POST['lot_number'].strip(),
            expiry_date=request.POST['expiry_date'],
            received_at=request.POST.get('received_at') or timezone.now().date(),
            received_by=request.user,
            branch_id=request.session.get('branch_id'),
            certificate_ok=request.POST.get('certificate_ok') == 'on',
            notes=request.POST.get('notes', ''),
        )
        write_audit(
            actor=request.user,
            action='reagent.lot.received',
            entity_table='quality_reagentlot',
            entity_id=lot.pk,
            after={'lot_number': lot.lot_number, 'expiry': str(lot.expiry_date)},
        )
        messages.success(request, f"Lot {lot.lot_number} registered — status: Quarantined. Run QC to release.")
        return redirect('quality:reagent_detail', pk=reagent_pk)

    return render(request, 'quality/register_lot.html', {'reagent': reagent})


@login_required
def record_qc(request, reagent_pk):
    reagent = get_object_or_404(Reagent, pk=reagent_pk)
    branch_id = request.session.get('branch_id')
    current_lot = reagent.current_lot() or reagent.lots.filter(
        status='quarantined', branch_id=branch_id
    ).order_by('-created_at').first()

    if not current_lot:
        messages.error(request, "No active or quarantined lot for this reagent. Register a lot first.")
        return redirect('quality:reagent_detail', pk=reagent_pk)

    if request.method == 'POST':
        from audit.utils import create_signature
        pos_observed  = request.POST.get('pos_observed', '0')
        neg_observed  = request.POST.get('neg_observed', '0')
        pos_expected  = request.POST.get('pos_expected', '4+')
        neg_expected  = request.POST.get('neg_expected', '0')
        pos_pass      = (pos_observed == pos_expected)
        neg_pass      = (neg_observed == neg_expected)
        overall_pass  = pos_pass and neg_pass

        try:
            lot_id = int(request.POST.get('lot_id', current_lot.pk))
        except (ValueError, TypeError):
            lot_id = current_lot.pk
        lot = get_object_or_404(ReagentLot, pk=lot_id)

        reauth_at = request.session.get('reauth_at')
        esign = create_signature(
            signer=request.user,
            meaning='qc_result',
            payload_data={'reagent': reagent.reagent_code, 'pass': overall_pass},
            reauth_at=reauth_at,
        )

        qc_run = QCRun.objects.create(
            reagent=reagent,
            lot=lot,
            branch_id=branch_id,
            performed_by=request.user,
            started_at=timezone.now(),
            completed_at=timezone.now(),
            overall_pass=overall_pass,
            protocol=request.POST.get('protocol', 'daily'),
            failure_action=request.POST.get('failure_action', ''),
            notes=request.POST.get('notes', ''),
            esign=esign,
        )
        QCResult.objects.create(
            qc_run=qc_run, control_type='pos_control',
            expected_grade=pos_expected, observed_grade=pos_observed,
            passed=pos_pass,
        )
        QCResult.objects.create(
            qc_run=qc_run, control_type='neg_control',
            expected_grade=neg_expected, observed_grade=neg_observed,
            passed=neg_pass,
        )

        if overall_pass and lot.status == 'quarantined':
            lot.status = 'in_use'
            lot.opened_at = timezone.now().date()
            lot.save(update_fields=['status', 'opened_at'])
            messages.success(request, f"QC PASSED — Lot {lot.lot_number} released to In Use.")
        elif overall_pass:
            messages.success(request, "QC PASSED.")
        else:
            lot.status = 'rejected'
            lot.save(update_fields=['status'])
            messages.error(request, f"QC FAILED — Lot {lot.lot_number} has been rejected. Do not use. "
                           f"Action: {request.POST.get('failure_action', 'none specified')}")

        write_audit(
            actor=request.user,
            action='reagent.qc.record',
            entity_table='quality_qcrun',
            entity_id=qc_run.pk,
            after={'reagent': reagent.reagent_code, 'overall_pass': overall_pass},
        )
        return redirect('quality:reagent_detail', pk=reagent_pk)

    return render(request, 'quality/record_qc.html', {
        'reagent': reagent,
        'current_lot': current_lot,
        'lots': reagent.lots.filter(status__in=['quarantined', 'in_use'], branch_id=branch_id),
    })


@login_required
def qc_dashboard(request):
    """Shows today's QC status for all reagents — green/red/overdue."""
    branch_id = request.session.get('branch_id')
    reagents = Reagent.objects.filter(active=True)
    today_qc = []
    for r in reagents:
        lot = r.current_lot()
        status = r.qc_status(branch_id)
        # Latest run today
        from django.utils import timezone
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        latest_run = QCRun.objects.filter(
            reagent=r, branch_id=branch_id, completed_at__gte=today_start
        ).order_by('-completed_at').first()
        today_qc.append({
            'reagent': r,
            'lot': lot,
            'status': status,
            'latest_run': latest_run,
        })

    calibrations = EquipmentCalibration.objects.filter(branch_id=branch_id).order_by('next_due')
    overdue_calibrations = [c for c in calibrations if c.is_overdue()]

    return render(request, 'quality/qc_dashboard.html', {
        'today_qc': today_qc,
        'calibrations': calibrations,
        'overdue_calibrations': overdue_calibrations,
    })


@login_required
def calibration_list(request):
    branch_id = request.session.get('branch_id')
    calibrations = list(EquipmentCalibration.objects.filter(branch_id=branch_id).order_by('next_due'))
    overdue = [c for c in calibrations if c.is_overdue()]

    # Fire alert for any overdue equipment (once per equipment — use get_or_create to avoid dupes)
    if overdue:
        from core.models import Alert, Branch
        branch = Branch.objects.filter(pk=branch_id).first()
        if branch:
            for cal in overdue:
                Alert.objects.get_or_create(
                    alert_type='equipment_calibration_due',
                    branch=branch,
                    entity_table='quality_equipmentcalibration',
                    entity_id=cal.pk,
                    acknowledged_by=None,
                    defaults={
                        'severity': 'critical',
                        'message': (
                            f"{cal.name} (Asset {cal.asset_id}) calibration overdue since {cal.next_due}. "
                            f"Do not use for clinical testing until recalibrated."
                        ),
                    },
                )

    return render(request, 'quality/calibration_list.html', {
        'calibrations': calibrations,
        'overdue_calibrations': overdue,
    })


@login_required
def record_calibration(request):
    if request.method == 'POST':
        cal = EquipmentCalibration.objects.create(
            name=request.POST['name'],
            asset_id=request.POST['asset_id'],
            equipment_type=request.POST['equipment_type'],
            branch_id=request.session.get('branch_id'),
            last_calibrated=request.POST['last_calibrated'],
            next_due=request.POST['next_due'],
            calibrated_by=request.POST['calibrated_by'],
            certificate_ref=request.POST.get('certificate_ref', ''),
            within_spec=request.POST.get('within_spec') == 'on',
            notes=request.POST.get('notes', ''),
            recorded_by=request.user,
        )
        write_audit(
            actor=request.user,
            action='equipment.calibration.record',
            entity_table='quality_equipmentcalibration',
            entity_id=cal.pk,
            after={'asset_id': cal.asset_id, 'next_due': str(cal.next_due)},
        )
        messages.success(request, f"Calibration recorded for {cal.name}.")
        return redirect('quality:calibration_list')
    from .models import EquipmentCalibration as EC
    return render(request, 'quality/record_calibration.html', {
        'equipment_types': EC.EQUIPMENT_TYPES,
    })


# ─── CAPA / Non-Conformance ──────────────────────────────────────────────────

@login_required
def nc_list(request):
    """Non-Conformance event list — filterable by status and severity."""
    branch_id = request.session.get('branch_id')
    qs = NonConformance.objects.filter(branch_id=branch_id).select_related('reported_by', 'assigned_to')

    status_filter   = request.GET.get('status', '')
    severity_filter = request.GET.get('severity', '')
    if status_filter:
        qs = qs.filter(status=status_filter)
    if severity_filter:
        qs = qs.filter(severity=severity_filter)

    open_count     = NonConformance.objects.filter(branch_id=branch_id, status__in=['open','under_review','capa_open','capa_verify']).count()
    overdue_count  = sum(1 for nc in NonConformance.objects.filter(branch_id=branch_id, status='capa_open') if nc.actions.filter(status='assigned').exists())

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'quality/nc_list.html', {
        'page_obj':       page,
        'status_filter':  status_filter,
        'severity_filter': severity_filter,
        'status_choices': NonConformance.STATUS,
        'severity_choices': NonConformance.SEVERITY,
        'open_count':     open_count,
        'overdue_count':  overdue_count,
    })


@login_required
def nc_create(request):
    """Report a new Non-Conformance event."""
    branch_id = request.session.get('branch_id')
    from core.models import Branch
    from django.shortcuts import redirect as _redirect
    branch = Branch.objects.filter(pk=branch_id).first() if branch_id else Branch.objects.first()
    if not branch:
        from django.contrib import messages as _msg
        _msg.error(request, "Branch not found. Please re-select your branch.")
        return _redirect('core:select_branch')
    from django.contrib.auth import get_user_model
    User = get_user_model()
    staff = User.objects.filter(is_active=True).order_by('username')

    if request.method == 'POST':
        nc = NonConformance.objects.create(
            nc_type          = request.POST['nc_type'],
            severity         = request.POST['severity'],
            description      = request.POST['description'],
            immediate_action = request.POST.get('immediate_action', ''),
            event_date       = request.POST['event_date'],
            related_blood_unit_did = request.POST.get('related_blood_unit_did', '').strip(),
            related_patient_id    = request.POST.get('related_patient_id') or None,
            shot_reportable       = request.POST.get('shot_reportable') == '1',
            reported_by           = request.user,
            assigned_to_id        = request.POST.get('assigned_to') or None,
            branch                = branch,
            notes                 = request.POST.get('notes', ''),
        )
        write_audit(
            actor=request.user,
            action='quality.nc.created',
            entity_table='quality_nonconformance',
            entity_id=nc.pk,
            after={'nc_number': nc.nc_number, 'severity': nc.severity, 'nc_type': nc.nc_type},
            branch=branch,
        )
        messages.success(request, f"Non-Conformance {nc.nc_number} reported.")
        return redirect('quality:nc_detail', pk=nc.pk)

    return render(request, 'quality/nc_form.html', {
        'nc_types':  NonConformance.NC_TYPES,
        'severities': NonConformance.SEVERITY,
        'staff':     staff,
        'today':     timezone.now().date(),
    })


@login_required
def nc_detail(request, pk):
    """NC detail view — shows actions, allows adding CA and closing NC."""
    nc = get_object_or_404(NonConformance, pk=pk)
    branch_id = request.session.get('branch_id')
    from core.models import Branch
    from django.shortcuts import redirect as _redirect
    branch = Branch.objects.filter(pk=branch_id).first() if branch_id else Branch.objects.first()
    if not branch:
        from django.contrib import messages as _msg
        _msg.error(request, "Branch not found. Please re-select your branch.")
        return _redirect('core:select_branch')
    from django.contrib.auth import get_user_model
    User = get_user_model()
    staff = User.objects.filter(is_active=True).order_by('username')

    if request.method == 'POST':
        action = request.POST.get('form_action')

        if action == 'add_ca':
            ca = CorrectiveAction.objects.create(
                nc           = nc,
                action_type  = request.POST['action_type'],
                description  = request.POST['ca_description'],
                assigned_to_id = request.POST['ca_assigned_to'],
                due_date     = request.POST['due_date'],
            )
            nc.status = 'capa_open'
            nc.save(update_fields=['status'])
            write_audit(
                actor=request.user,
                action='quality.ca.created',
                entity_table='quality_correctiveaction',
                entity_id=ca.pk,
                after={'nc_number': nc.nc_number, 'action_type': ca.action_type},
                branch=branch,
            )
            messages.success(request, f"Corrective action added to {nc.nc_number}.")

        elif action == 'complete_ca':
            ca_pk = request.POST.get('ca_pk')
            ca = get_object_or_404(CorrectiveAction, pk=ca_pk, nc=nc)
            ca.status       = 'completed'
            ca.completed_at = timezone.now()
            ca.completed_by = request.user
            ca.save(update_fields=['status', 'completed_at', 'completed_by'])
            # Check if all CAs complete — move to verify stage
            if nc.actions.exclude(status__in=['completed','verified']).count() == 0:
                nc.status = 'capa_verify'
                nc.save(update_fields=['status'])
            write_audit(
                actor=request.user,
                action='quality.ca.completed',
                entity_table='quality_correctiveaction',
                entity_id=ca.pk,
                after={'nc_number': nc.nc_number, 'action_type': ca.action_type},
                branch=branch,
            )
            messages.success(request, "Corrective action marked complete.")

        elif action == 'verify_ca':
            ca_pk = request.POST.get('ca_pk')
            ca = get_object_or_404(CorrectiveAction, pk=ca_pk, nc=nc)
            verdict = request.POST.get('verdict', 'effective')
            ca.verified_at     = timezone.now()
            ca.verified_by     = request.user
            ca.verification_notes = request.POST.get('verification_notes', '')
            ca.status = 'verified' if verdict == 'effective' else 'ineffective'
            ca.save(update_fields=['status', 'verified_at', 'verified_by', 'verification_notes'])
            write_audit(
                actor=request.user,
                action='quality.ca.verified',
                entity_table='quality_correctiveaction',
                entity_id=ca.pk,
                after={'status': ca.status, 'nc_number': nc.nc_number},
                branch=branch,
            )
            messages.success(request, "Corrective action verified.")

        elif action == 'close_nc':
            # Only close if all CAs verified effective
            unverified = nc.actions.exclude(status='verified').count()
            if unverified > 0:
                messages.error(request, f"{unverified} corrective action(s) not yet verified. Cannot close NC.")
            else:
                nc.status    = 'closed'
                nc.closed_at = timezone.now()
                nc.notes     = (nc.notes + '\n\nClosure: ' + request.POST.get('closure_notes', '')).strip()
                nc.save(update_fields=['status', 'closed_at', 'notes'])
                write_audit(
                    actor=request.user,
                    action='quality.nc.closed',
                    entity_table='quality_nonconformance',
                    entity_id=nc.pk,
                    after={'nc_number': nc.nc_number},
                    branch=branch,
                )
                messages.success(request, f"{nc.nc_number} closed.")

        elif action == 'update_status':
            new_status = request.POST.get('new_status', nc.status)
            old_status = nc.status
            nc.status = new_status
            nc.save(update_fields=['status'])
            write_audit(
                actor=request.user,
                action='quality.nc.status_updated',
                entity_table='quality_nonconformance',
                entity_id=nc.pk,
                before={'status': old_status},
                after={'status': new_status},
                branch=branch,
            )
            messages.info(request, "Status updated.")

        return redirect('quality:nc_detail', pk=nc.pk)

    return render(request, 'quality/nc_detail.html', {
        'nc':     nc,
        'actions': nc.actions.select_related('assigned_to', 'completed_by', 'verified_by'),
        'action_types': CorrectiveAction.ACTION_TYPES,
        'ca_statuses':  CorrectiveAction.STATUS,
        'nc_statuses':  NonConformance.STATUS,
        'staff':  staff,
        'today':  timezone.now().date(),
    })


# ---------------------------------------------------------------------------
# New Lot Validation
# ---------------------------------------------------------------------------

@login_required
def lot_validation_list(request):
    branch_id = request.session.get('branch_id')
    qs = (
        NewLotValidation.objects
        .filter(branch_id=branch_id)
        .select_related('new_lot__reagent', 'reference_lot', 'initiated_by')
        .order_by('-initiated_at')
    )
    status_filter = request.GET.get('status', '')
    if status_filter:
        qs = qs.filter(status=status_filter)
    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'quality/lot_validation_list.html', {
        'page_obj': page,
        'status_choices': NewLotValidation.STATUS,
        'status_filter': status_filter,
    })


@login_required
def lot_validation_create(request):
    branch_id = request.session.get('branch_id')
    if request.method == 'POST':
        from core.models import Branch
        new_lot_id = request.POST.get('new_lot_id')
        ref_lot_id = request.POST.get('reference_lot_id') or None
        branch = get_object_or_404(Branch, pk=branch_id)
        new_lot = get_object_or_404(ReagentLot, pk=new_lot_id)

        if hasattr(new_lot, 'lot_validation'):
            messages.warning(request, "A validation already exists for this lot.")
            return redirect('quality:lot_validation_detail', pk=new_lot.lot_validation.pk)

        validation = NewLotValidation.objects.create(
            new_lot=new_lot,
            reference_lot_id=ref_lot_id,
            branch=branch,
            initiated_by=request.user,
            status='pending',
        )
        write_audit(
            actor=request.user,
            action='lot_validation.initiated',
            entity_table='quality_newlotvalidation',
            entity_id=validation.pk,
            after={'new_lot_id': new_lot_id, 'ref_lot_id': ref_lot_id},
        )
        messages.success(request, f"Validation initiated for lot {new_lot.lot_number}.")
        return redirect('quality:lot_validation_detail', pk=validation.pk)

    # GET — show form to pick lots
    from quality.models import REACTION_GRADES
    lots_in_quarantine = ReagentLot.objects.filter(
        status='quarantined'
    ).select_related('reagent').order_by('reagent__name', 'lot_number')
    lots_in_use = ReagentLot.objects.filter(status='in_use').select_related('reagent')
    return render(request, 'quality/lot_validation_form.html', {
        'lots_in_quarantine': lots_in_quarantine,
        'lots_in_use': lots_in_use,
        'reaction_grades': REACTION_GRADES,
    })


@login_required
def lot_validation_detail(request, pk):
    validation = get_object_or_404(NewLotValidation, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_result':
            sample_label = request.POST.get('sample_label', '').strip()
            ref_grade    = request.POST.get('ref_grade', '')
            new_grade    = request.POST.get('new_grade', '')
            comment      = request.POST.get('comment', '').strip()

            if sample_label and ref_grade and new_grade:
                result = LotValidationResult.objects.create(
                    validation=validation,
                    sample_label=sample_label,
                    ref_grade=ref_grade,
                    new_grade=new_grade,
                    comment=comment,
                )
                validation.status = 'in_review'
                validation.save(update_fields=['status'])
                write_audit(
                    actor=request.user,
                    action='lot_validation.result_added',
                    entity_table='quality_lotvalidationresult',
                    entity_id=result.pk,
                    after={'validation_id': validation.pk, 'sample_label': sample_label,
                           'ref_grade': ref_grade, 'new_grade': new_grade},
                )
            return redirect('quality:lot_validation_detail', pk=pk)

        elif action == 'submit_for_review':
            old_status = validation.status
            validation.status = 'in_review'
            validation.save(update_fields=['status'])
            write_audit(
                actor=request.user,
                action='lot_validation.submitted_for_review',
                entity_table='quality_newlotvalidation',
                entity_id=validation.pk,
                before={'status': old_status},
                after={'status': 'in_review'},
            )
            messages.info(request, "Submitted for review.")
            return redirect('quality:lot_validation_detail', pk=pk)

        elif action == 'approve':
            reauth_password = request.POST.get('password', '')
            from django.contrib.auth import authenticate
            user = authenticate(request, username=request.user.username, password=reauth_password)
            if not user:
                messages.error(request, "Incorrect password — e-signature failed.")
                return redirect('quality:lot_validation_detail', pk=pk)

            from audit.utils import create_signature
            esign = create_signature(
                signer=request.user,
                meaning='Approved new reagent lot for clinical use after parallel validation',
                payload_data={'validation_id': validation.pk, 'lot': validation.new_lot.lot_number},
                reauth_at=timezone.now(),
            )
            validation.status   = 'approved'
            validation.reviewed_by  = request.user
            validation.reviewed_at  = timezone.now()
            validation.review_notes = request.POST.get('review_notes', '')
            validation.esign        = esign
            validation.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes', 'esign'])

            # Release the new lot to in_use
            validation.new_lot.status = 'in_use'
            if not validation.new_lot.opened_at:
                validation.new_lot.opened_at = timezone.now().date()
            validation.new_lot.save(update_fields=['status', 'opened_at'])

            write_audit(
                actor=request.user,
                action='lot_validation.approved',
                entity_table='quality_newlotvalidation',
                entity_id=validation.pk,
                after={'lot': validation.new_lot.lot_number, 'status': 'approved'},
            )
            messages.success(request, f"Lot {validation.new_lot.lot_number} approved and released for clinical use.")
            return redirect('quality:lot_validation_detail', pk=pk)

        elif action == 'reject':
            validation.status      = 'rejected'
            validation.reviewed_by = request.user
            validation.reviewed_at = timezone.now()
            validation.review_notes = request.POST.get('review_notes', '')
            validation.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes'])

            # Reject the lot itself
            validation.new_lot.status = 'rejected'
            validation.new_lot.save(update_fields=['status'])

            # Auto-create a NonConformance for the reagent failure
            nc = NonConformance.objects.create(
                branch=validation.branch,
                nc_type='reagent_failure',
                severity='significant',
                description=(
                    f"New lot validation FAILED: Reagent {validation.new_lot.reagent.name}, "
                    f"Lot {validation.new_lot.lot_number}. "
                    f"Notes: {validation.review_notes}"
                ),
                reported_by=request.user,
                event_date=timezone.now().date(),
                shot_reportable=False,
            )
            validation.nc = nc
            validation.save(update_fields=['nc'])

            write_audit(
                actor=request.user,
                action='lot_validation.rejected',
                entity_table='quality_newlotvalidation',
                entity_id=validation.pk,
                after={'lot': validation.new_lot.lot_number, 'nc_id': nc.pk},
            )
            messages.error(
                request,
                f"Lot rejected. Non-Conformance {nc.nc_number} raised automatically."
            )
            return redirect('quality:lot_validation_detail', pk=pk)

        elif action == 'delete_result':
            result_pk = request.POST.get('result_pk')
            result_qs = LotValidationResult.objects.filter(pk=result_pk, validation=validation)
            result_obj = result_qs.first()
            if result_obj:
                write_audit(
                    actor=request.user,
                    action='lot_validation.result_deleted',
                    entity_table='quality_lotvalidationresult',
                    entity_id=result_obj.pk,
                    before={'validation_id': validation.pk, 'sample_label': result_obj.sample_label},
                )
                result_qs.delete()
            return redirect('quality:lot_validation_detail', pk=pk)

        return redirect('quality:lot_validation_detail', pk=pk)

    from quality.models import REACTION_GRADES
    results = validation.validation_results.all().order_by('id')
    return render(request, 'quality/lot_validation_detail.html', {
        'validation':      validation,
        'results':         results,
        'overall':         validation.overall_result(),
        'reaction_grades': REACTION_GRADES,
        'status_choices':  NewLotValidation.STATUS,
    })


@login_required
def deplete_lot(request, lot_pk):
    """Mark an in-use reagent lot as depleted and fire low-stock alert if needed."""
    lot = get_object_or_404(ReagentLot, pk=lot_pk)
    if request.method == 'POST':
        if lot.status != 'in_use':
            messages.error(request, f"Lot {lot.lot_number} is not currently in use (status: {lot.get_status_display()}).")
            return redirect('quality:reagent_detail', pk=lot.reagent_id)

        lot.status = 'depleted'
        lot.save(update_fields=['status'])
        write_audit(
            actor=request.user,
            action='reagent.lot.depleted',
            entity_table='quality_reagentlot',
            entity_id=lot.pk,
            after={'lot_number': lot.lot_number, 'reagent': lot.reagent.reagent_code, 'status': 'depleted'},
        )

        # Fire low-stock alert if remaining available lots < minimum threshold
        branch_id = request.session.get('branch_id')
        reagent = lot.reagent
        remaining = ReagentLot.objects.filter(
            reagent=reagent, branch_id=branch_id, status__in=['in_use', 'quarantined'],
        ).count()
        if remaining < reagent.minimum_lots:
            from core.models import Alert, Branch
            branch = Branch.objects.filter(pk=branch_id).first()
            if branch:
                Alert.objects.get_or_create(
                    alert_type='low_inventory',
                    branch=branch,
                    acknowledged_by=None,
                    defaults={
                        'severity': 'critical' if remaining == 0 else 'warning',
                        'message': (
                            f"Low reagent stock: {reagent.name} has {remaining} lot(s) available "
                            f"(minimum: {reagent.minimum_lots}). Order new stock immediately."
                        ),
                        'entity_table': 'quality_reagent',
                        'entity_id': reagent.pk,
                    },
                )
        messages.success(request, f"Lot {lot.lot_number} marked as depleted. {remaining} lot(s) remaining.")
        return redirect('quality:reagent_detail', pk=lot.reagent_id)

    return render(request, 'quality/deplete_lot_confirm.html', {'lot': lot})


# ─── SOP Management ───────────────────────────────────────────────────────────

@login_required
def sop_list(request):
    branch_id = request.session.get('branch_id')
    sops = StandardOperatingProcedure.objects.filter(branch_id=branch_id).prefetch_related('versions')

    category_filter = request.GET.get('category', '')
    status_filter   = request.GET.get('status', '')
    if category_filter:
        sops = sops.filter(category=category_filter)
    if status_filter:
        sops = sops.filter(status=status_filter)

    overdue_reviews = [s for s in sops if s.is_overdue_review()]

    from quality.models import SOP_CATEGORIES
    return render(request, 'quality/sop_list.html', {
        'sops': sops,
        'overdue_reviews': overdue_reviews,
        'category_filter': category_filter,
        'status_filter': status_filter,
        'sop_categories': SOP_CATEGORIES,
        'status_choices': StandardOperatingProcedure.STATUS,
    })


@login_required
def sop_create(request):
    branch_id = request.session.get('branch_id')
    from core.models import Branch
    from quality.models import SOP_CATEGORIES

    if request.method == 'POST':
        sop_code = request.POST.get('sop_code', '').strip()
        title    = request.POST.get('title', '').strip()
        category = request.POST.get('category', '')
        try:
            review_interval = int(request.POST.get('review_interval_months', 12))
        except (ValueError, TypeError):
            review_interval = 12

        if not sop_code or not title or not category:
            messages.error(request, "SOP Code, title, and category are required.")
        elif StandardOperatingProcedure.objects.filter(sop_code=sop_code).exists():
            messages.error(request, f"SOP code {sop_code} already exists.")
        else:
            from django.utils import timezone
            from datetime import timedelta as _td
            next_review = timezone.now().date() + _td(days=review_interval * 30)
            sop = StandardOperatingProcedure.objects.create(
                sop_code=sop_code,
                title=title,
                category=category,
                review_interval_months=review_interval,
                next_review_due=next_review,
                owner=request.user,
                branch_id=branch_id,
                created_by=request.user,
            )
            write_audit(
                actor=request.user,
                action='sop.created',
                entity_table='quality_standardoperatingprocedure',
                entity_id=sop.pk,
                after={'sop_code': sop_code, 'title': title},
            )
            messages.success(request, f"SOP {sop_code} created. Add version documents below.")
            return redirect('quality:sop_detail', pk=sop.pk)

    return render(request, 'quality/sop_form.html', {
        'sop_categories': SOP_CATEGORIES,
        'review_intervals': [(3,'3 months'),(6,'6 months'),(12,'12 months'),(24,'24 months')],
    })


@login_required
def sop_detail(request, pk):
    sop = get_object_or_404(StandardOperatingProcedure, pk=pk)
    versions = sop.versions.order_by('-authored_at')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_version':
            version_number   = request.POST.get('version_number', '').strip()
            summary          = request.POST.get('summary_of_changes', '').strip()
            document_text    = request.POST.get('document_text', '').strip()
            if not version_number:
                messages.error(request, "Version number is required.")
            elif sop.versions.filter(version_number=version_number).exists():
                messages.error(request, f"Version {version_number} already exists for this SOP.")
            else:
                ver = SOPVersion.objects.create(
                    sop=sop,
                    version_number=version_number,
                    summary_of_changes=summary,
                    document_text=document_text,
                    authored_by=request.user,
                )
                write_audit(
                    actor=request.user,
                    action='sop_version.added',
                    entity_table='quality_sopversion',
                    entity_id=ver.pk,
                    after={'sop_code': sop.sop_code, 'version': version_number},
                )
                messages.success(request, f"Version {version_number} added.")
            return redirect('quality:sop_detail', pk=pk)

        elif action == 'approve_version':
            ver_pk   = request.POST.get('version_pk')
            password = request.POST.get('password', '')
            version  = get_object_or_404(SOPVersion, pk=ver_pk, sop=sop)

            # Password re-auth for e-signature
            from django.contrib.auth import authenticate
            auth_user = authenticate(request, username=request.user.username, password=password)
            if not auth_user:
                messages.error(request, "Incorrect password — approval requires re-authentication.")
                return redirect('quality:sop_detail', pk=pk)

            from audit.utils import create_signature
            esign = create_signature(
                signer=request.user,
                meaning='SOP version approved for clinical use',
                payload_data={'sop_code': sop.sop_code, 'version': version.version_number},
            )

            from django.utils import timezone
            from datetime import timedelta as _td
            version.status      = 'approved'
            version.approved_by = request.user
            version.approved_at = timezone.now()
            version.esign       = esign
            version.save(update_fields=['status', 'approved_by', 'approved_at', 'esign'])

            # Retire old active version
            if sop.active_version and sop.active_version != version:
                old = sop.active_version
                old.status = 'retired'
                old.save(update_fields=['status'])

            next_review = timezone.now().date() + _td(days=sop.review_interval_months * 30)
            sop.active_version   = version
            sop.status           = 'active'
            sop.next_review_due  = next_review
            sop.save(update_fields=['active_version', 'status', 'next_review_due'])

            write_audit(
                actor=request.user,
                action='sop_version.approved',
                entity_table='quality_sopversion',
                entity_id=version.pk,
                after={'sop_code': sop.sop_code, 'version': version.version_number, 'next_review': str(next_review)},
            )
            messages.success(request, f"{sop.sop_code} v{version.version_number} approved and active.")
            return redirect('quality:sop_detail', pk=pk)

    return render(request, 'quality/sop_detail.html', {
        'sop': sop,
        'versions': versions,
    })


# ─── Internal Quality Audit ────────────────────────────────────────────────────

@login_required
def internal_audit_list(request):
    branch_id = request.session.get('branch_id')
    audits = InternalAudit.objects.filter(branch_id=branch_id).prefetch_related('findings')

    status_filter = request.GET.get('status', '')
    if status_filter:
        audits = audits.filter(status=status_filter)

    open_findings = AuditFinding.objects.filter(
        audit__branch_id=branch_id,
        status__in=['open', 'capa'],
    ).count()

    return render(request, 'quality/internal_audit_list.html', {
        'audits': audits,
        'open_findings': open_findings,
        'status_filter': status_filter,
        'status_choices': InternalAudit.STATUS,
    })


@login_required
def internal_audit_create(request):
    branch_id = request.session.get('branch_id')
    from core.models import Branch

    if request.method == 'POST':
        audit_type     = request.POST.get('audit_type', '')
        scope          = request.POST.get('scope', '').strip()
        auditee_area   = request.POST.get('auditee_area', '').strip()
        scheduled_date = request.POST.get('scheduled_date', '')

        if not all([audit_type, scope, auditee_area, scheduled_date]):
            messages.error(request, "All fields are required.")
        else:
            from datetime import date as _date
            audit = InternalAudit.objects.create(
                audit_type=audit_type,
                scope=scope,
                auditee_area=auditee_area,
                scheduled_date=scheduled_date,
                branch_id=branch_id,
                lead_auditor=request.user,
                created_by=request.user,
            )
            write_audit(
                actor=request.user,
                action='internal_audit.created',
                entity_table='quality_internalaudit',
                entity_id=audit.pk,
                after={'audit_number': audit.audit_number, 'type': audit_type},
            )
            messages.success(request, f"Audit {audit.audit_number} scheduled.")
            return redirect('quality:internal_audit_detail', pk=audit.pk)

    return render(request, 'quality/internal_audit_form.html', {
        'audit_types': InternalAudit.AUDIT_TYPES,
    })


@login_required
def internal_audit_detail(request, pk):
    audit = get_object_or_404(InternalAudit, pk=pk)
    findings = audit.findings.order_by('classification', '-created_at')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_finding':
            classification = request.POST.get('classification', '')
            description    = request.POST.get('description', '').strip()
            reference      = request.POST.get('reference', '').strip()
            due_date       = request.POST.get('due_date', '') or None
            if not classification or not description:
                messages.error(request, "Classification and description are required.")
            else:
                finding = AuditFinding.objects.create(
                    audit=audit,
                    classification=classification,
                    description=description,
                    reference=reference,
                    due_date=due_date,
                )
                write_audit(
                    actor=request.user,
                    action='internal_audit.finding_added',
                    entity_table='quality_auditfinding',
                    entity_id=finding.pk,
                    after={'audit_number': audit.audit_number, 'classification': classification},
                    branch=audit.branch,
                )
                messages.success(request, "Finding recorded.")
            return redirect('quality:internal_audit_detail', pk=pk)

        elif action == 'update_status':
            new_status = request.POST.get('new_status', '')
            if new_status in dict(InternalAudit.STATUS):
                from django.utils import timezone
                audit.status = new_status
                if new_status == 'in_progress' and not audit.start_date:
                    audit.start_date = timezone.now().date()
                elif new_status in ('complete', 'closed') and not audit.end_date:
                    audit.end_date = timezone.now().date()
                audit.save(update_fields=['status', 'start_date', 'end_date'])
                write_audit(
                    actor=request.user,
                    action='internal_audit.status_changed',
                    entity_table='quality_internalaudit',
                    entity_id=audit.pk,
                    after={'status': new_status},
                )
                messages.success(request, f"Audit status updated to: {audit.get_status_display()}")
            return redirect('quality:internal_audit_detail', pk=pk)

        elif action == 'resolve_finding':
            finding_pk = request.POST.get('finding_pk')
            resolution = request.POST.get('resolution', '').strip()
            finding = get_object_or_404(AuditFinding, pk=finding_pk, audit=audit)
            from django.utils import timezone
            finding.status      = 'resolved'
            finding.resolution  = resolution
            finding.resolved_at = timezone.now().date()
            finding.save(update_fields=['status', 'resolution', 'resolved_at'])
            write_audit(
                actor=request.user,
                action='internal_audit.finding_resolved',
                entity_table='quality_auditfinding',
                entity_id=finding.pk,
                after={'audit_number': audit.audit_number, 'resolution': resolution[:100]},
                branch=audit.branch,
            )
            messages.success(request, "Finding resolved.")
            return redirect('quality:internal_audit_detail', pk=pk)

        elif action == 'raise_nc':
            finding_pk  = request.POST.get('finding_pk')
            finding = get_object_or_404(AuditFinding, pk=finding_pk, audit=audit)
            from django.utils import timezone
            nc = NonConformance.objects.create(
                nc_type='procedure_deviation',
                severity='significant' if finding.classification == 'major' else 'minor',
                description=f"Audit finding ({audit.audit_number}): {finding.description}",
                immediate_action=f"Ref: {finding.reference}" if finding.reference else '',
                reported_by=request.user,
                branch=audit.branch,
                event_date=timezone.now().date(),
            )
            finding.status = 'capa'
            finding.nc     = nc
            finding.save(update_fields=['status', 'nc'])
            write_audit(
                actor=request.user,
                action='internal_audit.nc_raised',
                entity_table='quality_nonconformance',
                entity_id=nc.pk,
                after={'nc_number': nc.nc_number, 'audit_number': audit.audit_number,
                       'finding_pk': finding.pk},
                branch=audit.branch,
            )
            messages.success(request, f"NC {nc.nc_number} raised from finding.")
            return redirect('quality:nc_detail', pk=nc.pk)

    return render(request, 'quality/internal_audit_detail.html', {
        'audit': audit,
        'findings': findings,
        'finding_classifications': AuditFinding.CLASSIFICATION,
    })


# ─── Staff Competency Assessment ──────────────────────────────────────────────

@login_required
def competency_list(request):
    """
    ISO 15189:2022 clause 6.2 — Personnel competency register.
    Shows all active staff competencies with overdue-reassessment alerts.
    """
    branch_id = request.session.get('branch_id')
    records = StaffCompetency.objects.filter(
        branch_id=branch_id,
    ).select_related('staff_member', 'assessed_by', 'related_sop').order_by('staff_member', '-assessed_at')

    staff_filter = request.GET.get('staff', '')
    category_filter = request.GET.get('category', '')
    if staff_filter:
        records = records.filter(staff_member_id=staff_filter)
    if category_filter:
        records = records.filter(task_category=category_filter)

    from django.utils import timezone
    from datetime import timedelta as _td
    today = timezone.now().date()
    overdue_count = records.filter(reassessment_due__lt=today).exclude(outcome='withdrawn').count()
    due_soon_count = records.filter(
        reassessment_due__gte=today,
        reassessment_due__lte=today + _td(days=30),
    ).exclude(outcome='withdrawn').count()

    # Staff list for filter dropdown
    from django.contrib.auth import get_user_model
    User = get_user_model()
    staff_users = User.objects.filter(
        competencies__branch_id=branch_id
    ).distinct()

    return render(request, 'quality/competency_list.html', {
        'records': records[:200],
        'overdue_count': overdue_count,
        'due_soon_count': due_soon_count,
        'staff_filter': staff_filter,
        'category_filter': category_filter,
        'staff_users': staff_users,
        'task_categories': StaffCompetency.TASK_CATEGORIES,
    })


@login_required
def competency_record(request):
    """Record a new staff competency assessment."""
    branch_id = request.session.get('branch_id')
    from core.models import Branch
    from django.contrib.auth import get_user_model
    User = get_user_model()

    if request.method == 'POST':
        staff_pk    = request.POST.get('staff_member', '')
        task_cat    = request.POST.get('task_category', '')
        task_desc   = request.POST.get('task_description', '').strip()
        method      = request.POST.get('assessment_method', '')
        outcome     = request.POST.get('outcome', '')
        assessed_at = request.POST.get('assessed_at', '')
        reass_due   = request.POST.get('reassessment_due', '')
        sop_pk      = request.POST.get('related_sop', '') or None
        score_str   = request.POST.get('score', '').strip()
        comments    = request.POST.get('comments', '').strip()

        score = int(score_str) if score_str.isdigit() else None

        if not all([staff_pk, task_cat, task_desc, method, outcome, assessed_at, reass_due]):
            messages.error(request, "All required fields must be filled in.")
        elif staff_pk == str(request.user.pk):
            messages.error(request, "A staff member cannot assess their own competency (assessor ≠ assessee).")
        else:
            comp = StaffCompetency.objects.create(
                staff_member_id=staff_pk,
                task_category=task_cat,
                task_description=task_desc,
                assessment_method=method,
                outcome=outcome,
                assessed_at=assessed_at,
                reassessment_due=reass_due,
                related_sop_id=sop_pk,
                score=score,
                comments=comments,
                assessed_by=request.user,
                branch_id=branch_id,
            )
            write_audit(
                actor=request.user,
                action='competency.assessed',
                entity_table='quality_staffcompetency',
                entity_id=comp.pk,
                after={
                    'staff_member': staff_pk,
                    'task': task_desc[:60],
                    'outcome': outcome,
                },
            )
            messages.success(request, f"Competency record saved for {comp.staff_member.display_name or comp.staff_member.username}.")
            return redirect('quality:competency_list')

    sops = StandardOperatingProcedure.objects.filter(
        branch_id=branch_id, status='active'
    ).order_by('sop_code')
    staff_users = User.objects.filter(is_active=True).order_by('display_name')

    from django.utils import timezone
    from datetime import timedelta as _td
    default_reass = (timezone.now().date() + _td(days=365)).isoformat()

    return render(request, 'quality/competency_form.html', {
        'task_categories': StaffCompetency.TASK_CATEGORIES,
        'assessment_methods': StaffCompetency.METHODS,
        'outcome_choices': StaffCompetency.OUTCOMES,
        'sops': sops,
        'staff_users': staff_users,
        'default_reassessment_due': default_reass,
    })


# ─── Transfusion Committee ─────────────────────────────────────────────────────

@login_required
def committee_list(request):
    branch_id = request.session.get('branch_id')
    meetings = TransfusionCommittee.objects.filter(branch_id=branch_id).select_related('chair')

    # Open actions count (across all meetings) for banner
    open_actions = CommitteeAction.objects.filter(
        meeting__branch_id=branch_id,
        status__in=('open', 'in_progress'),
    ).count()
    overdue_actions = [
        a for a in CommitteeAction.objects.filter(
            meeting__branch_id=branch_id, status__in=('open', 'in_progress'),
        ).select_related('meeting') if a.is_overdue()
    ]

    paginator = Paginator(meetings, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'quality/committee_list.html', {
        'page_obj': page,
        'open_actions': open_actions,
        'overdue_actions': overdue_actions,
    })


@login_required
def committee_create(request):
    if request.method == 'POST':
        branch_id = request.session.get('branch_id')
        meeting_type = request.POST.get('meeting_type', '').strip()
        scheduled_date = request.POST.get('scheduled_date', '').strip()
        agenda_text = request.POST.get('agenda_text', '').strip()
        chair_id = request.POST.get('chair_id', '').strip()

        if not meeting_type or not scheduled_date or not chair_id:
            messages.error(request, "Meeting type, date, and chair are required.")
            from accounts.models import User
            return render(request, 'quality/committee_form.html', {
                'meeting_types': TransfusionCommittee.MEETING_TYPES,
                'staff_users': User.objects.filter(is_active=True).order_by('display_name'),
            })

        try:
            chair_id_int = int(chair_id)
        except (ValueError, TypeError):
            messages.error(request, "Invalid chair selection.")
            from accounts.models import User
            return render(request, 'quality/committee_form.html', {
                'meeting_types': TransfusionCommittee.MEETING_TYPES,
                'staff_users': User.objects.filter(is_active=True).order_by('display_name'),
            })
        meeting = TransfusionCommittee.objects.create(
            branch_id=branch_id,
            meeting_type=meeting_type,
            scheduled_date=scheduled_date,
            agenda_text=agenda_text,
            chair_id=chair_id_int,
            created_by=request.user,
        )
        write_audit(
            actor=request.user,
            action='committee.meeting.scheduled',
            entity_table='quality_transfusioncommittee',
            entity_id=meeting.pk,
            after={'meeting_type': meeting_type, 'scheduled_date': scheduled_date},
        )
        messages.success(request, f"Committee meeting scheduled for {meeting.scheduled_date}.")
        return redirect('quality:committee_detail', pk=meeting.pk)

    from accounts.models import User
    return render(request, 'quality/committee_form.html', {
        'meeting_types': TransfusionCommittee.MEETING_TYPES,
        'staff_users': User.objects.filter(is_active=True).order_by('display_name'),
    })


@login_required
def committee_detail(request, pk):
    from audit.utils import create_signature
    from django.contrib.auth import authenticate
    meeting = get_object_or_404(TransfusionCommittee, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'record_minutes':
            meeting.actual_date = request.POST.get('actual_date') or meeting.scheduled_date
            meeting.attendees_text = request.POST.get('attendees_text', '').strip()
            meeting.quorum_met = request.POST.get('quorum_met') == 'on'
            meeting.minutes_text = request.POST.get('minutes_text', '').strip()
            meeting.qi_reviewed = [
                q.strip() for q in request.POST.get('qi_reviewed', '').split(',') if q.strip()
            ]
            meeting.status = 'minutes_draft'
            meeting.save()
            write_audit(
                actor=request.user,
                action='committee.minutes.recorded',
                entity_table='quality_transfusioncommittee',
                entity_id=meeting.pk,
                after={'status': 'minutes_draft', 'actual_date': str(meeting.actual_date)},
            )
            messages.success(request, "Minutes recorded.")

        elif action == 'approve_minutes':
            password = request.POST.get('password', '')
            user = authenticate(request=request, username=request.user.username, password=password)
            if not user:
                messages.error(request, "Incorrect password — minutes approval requires re-authentication.")
                return redirect('quality:committee_detail', pk=pk)
            meeting.approved_by = request.user
            meeting.approved_at = timezone.now()
            meeting.status = 'minutes_approved'
            esign = create_signature(
                signer=request.user,
                meaning='committee_minutes_approval',
                payload_data={'meeting_pk': pk, 'approved_at': timezone.now().isoformat()},
            )
            meeting.esign = esign
            meeting.save()
            write_audit(
                actor=request.user,
                action='committee.minutes.approved',
                entity_table='quality_transfusioncommittee',
                entity_id=meeting.pk,
                after={'status': 'minutes_approved'},
            )
            messages.success(request, "Minutes approved with electronic signature.")

        elif action == 'add_action':
            description = request.POST.get('description', '').strip()
            owner_name = request.POST.get('owner_name', '').strip()
            due_date = request.POST.get('due_date', '').strip()
            owner_id = request.POST.get('owner_id', '').strip() or None

            if not description or not due_date:
                messages.error(request, "Action description and due date are required.")
                return redirect('quality:committee_detail', pk=pk)

            try:
                owner_id_int = int(owner_id) if owner_id else None
            except (ValueError, TypeError):
                owner_id_int = None
            ca = CommitteeAction.objects.create(
                meeting=meeting,
                description=description,
                owner_name=owner_name,
                owner_id=owner_id_int,
                due_date=due_date,
            )
            write_audit(
                actor=request.user,
                action='committee.action_added',
                entity_table='quality_committeeaction',
                entity_id=ca.pk,
                after={'meeting_pk': meeting.pk, 'due_date': due_date, 'description': description[:80]},
            )
            messages.success(request, "Action item added.")

        elif action == 'update_action':
            action_pk = request.POST.get('action_pk', '')
            ca = get_object_or_404(CommitteeAction, pk=action_pk, meeting=meeting)
            old_status = ca.status
            ca.status = request.POST.get('status', ca.status)
            ca.completion_notes = request.POST.get('completion_notes', ca.completion_notes)
            if ca.status == 'completed' and not ca.completed_at:
                ca.completed_at = timezone.now().date()
            ca.save()
            write_audit(
                actor=request.user,
                action='committee.action_updated',
                entity_table='quality_committeeaction',
                entity_id=ca.pk,
                before={'status': old_status},
                after={'status': ca.status, 'meeting_pk': meeting.pk},
            )
            messages.success(request, "Action updated.")

        return redirect('quality:committee_detail', pk=pk)

    actions = meeting.actions.select_related('owner').order_by('due_date')
    overdue = [a for a in actions if a.is_overdue()]
    from accounts.models import User
    return render(request, 'quality/committee_detail.html', {
        'meeting': meeting,
        'actions': actions,
        'overdue_count': len(overdue),
        'statuses': CommitteeAction.STATUSES,
        'staff_users': User.objects.filter(is_active=True).order_by('display_name'),
    })
