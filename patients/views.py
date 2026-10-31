from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone

from .models import (
    Patient, PatientBloodGroup, PatientAntibody, PatientTransfusionRequirement,
    TransfusionConsent, BloodGroupDiscrepancyInvestigation, PatientPhenotype,
    TherapeuticPhlebotomy, AntenatalRecord, AntiDProphylaxis, HaemolyticDiseaseCase,
)
from privacy.models import SubjectIdentity
from audit.utils import write_audit
from accounts.permissions import has_permission


def _to_int_or_none(val):
    """Convert val to int, returning None on ValueError/TypeError or empty string."""
    if val is None or val == '':
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


@login_required
def patient_list(request):
    qs = Patient.objects.filter(record_status='active').order_by('-created_at')

    q = request.GET.get('q', '').strip()
    if q:
        from privacy.vault import blind_index
        if q.isdigit():
            qs = qs.filter(pk=int(q))
        else:
            idx = blind_index(q)
            qs = qs.filter(subject__name_blind_index=idx)

    blood_group = request.GET.get('abo', '')
    if blood_group:
        from django.db.models import OuterRef, Subquery
        from .models import PatientBloodGroup as PBG
        latest_bg = PBG.objects.filter(
            patient=OuterRef('pk'), is_discrepant=False
        ).order_by('-determined_at').values('abo')[:1]
        qs = qs.annotate(current_abo=Subquery(latest_bg)).filter(current_abo=blood_group)

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'patients/list.html', {
        'page_obj': page,
        'q': q,
        'abo': blood_group,
        'abo_choices': [('A', 'A'), ('B', 'B'), ('AB', 'AB'), ('O', 'O')],
    })


@login_required
def register_patient(request):
    if not has_permission(request.user, 'patient.register', request.session.get('branch_id')):
        messages.error(request, "You don't have permission to register patients.")
        return redirect('core:dashboard')

    if request.method == 'POST':
        subject = SubjectIdentity.create_from_plain(
            name=request.POST['full_name'],
            national_id=request.POST.get('national_id', ''),
            contact=request.POST.get('contact', ''),
            subject_type='patient',
            created_by=request.user,
        )
        patient = Patient.objects.create(
            subject=subject,
            sex=request.POST['sex'],
            dob=request.POST.get('dob') or None,
            abo=request.POST.get('abo', ''),
            rh_d=request.POST.get('rh_d', ''),
            created_by=request.user,
        )
        write_audit(
            actor=request.user,
            action='patient.register',
            entity_table='patients_patient',
            entity_id=patient.pk,
            after={'sex': patient.sex, 'abo': patient.abo, 'rh_d': patient.rh_d},
        )
        messages.success(request, f"Patient #{patient.pk} registered.")
        return redirect('patients:detail', pk=patient.pk)

    return render(request, 'patients/register.html')


@login_required
def patient_detail(request, pk):
    from transfusion.models import Crossmatch
    patient = get_object_or_404(Patient, pk=pk)
    crossmatches = Crossmatch.objects.filter(
        request__patient=patient
    ).select_related('blood_unit', 'tech', 'request').order_by('-performed_at')[:20]
    active_consent = patient.consents.filter(status='active').order_by('-obtained_at').first()
    antenatal_records = AntenatalRecord.objects.filter(patient=patient).order_by('-created_at')[:5]
    tp_history = TherapeuticPhlebotomy.objects.filter(patient=patient).order_by('-scheduled_date')[:5]
    return render(request, 'patients/detail.html', {
        'patient':           patient,
        'blood_groups':      patient.blood_groups.order_by('-determined_at')[:10],
        'antibodies':        patient.antibodies.all(),
        'special_reqs':      patient.special_requirements.filter(active=True),
        'requests':          patient.blood_requests.order_by('-requested_ts')[:10],
        'crossmatches':      crossmatches,
        'active_consent':    active_consent,
        'antenatal_records': antenatal_records,
        'tp_history':        tp_history,
    })


@login_required
def add_blood_group(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    if not has_permission(request.user, 'patient.blood_group', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('patients:detail', pk=pk)

    if request.method == 'POST':
        accession = request.POST.get('accession_number', '').strip()
        if accession:
            from transfusion.models import Sample
            sample = get_object_or_404(Sample, accession_number=accession)
            source = 'current_testing'
        else:
            sample = None
            source = 'historical'

        # Check for discrepancy against last confirmed group
        last = patient.current_blood_group()
        is_discrepant = bool(
            last and (last.abo != request.POST['abo'] or last.rh_d != request.POST['rh_d'])
        )

        bg = PatientBloodGroup.objects.create(
            patient=patient,
            abo=request.POST['abo'],
            rh_d=request.POST['rh_d'],
            method=request.POST['method'],
            sample=sample,
            determined_by=request.user,
            branch_id=request.session.get('branch_id'),
            source=source,
            is_discrepant=is_discrepant,
            determined_at=timezone.now(),
        )
        write_audit(
            actor=request.user,
            action='patient.blood_group.add',
            entity_table='patients_patientbloodgroup',
            entity_id=bg.pk,
            after={'patient_id': patient.pk, 'abo': bg.abo, 'rh_d': bg.rh_d,
                   'is_discrepant': is_discrepant},
        )
        if is_discrepant:
            messages.warning(request, "Blood group discrepancy detected — manual review required.")
        else:
            messages.success(request, f"Blood group {bg.abo} {bg.rh_d} recorded.")
        return redirect('patients:detail', pk=pk)

    return render(request, 'patients/add_blood_group.html', {'patient': patient})


@login_required
def add_antibody(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    if request.method == 'POST':
        ab = PatientAntibody.objects.create(
            patient=patient,
            specificity=request.POST['specificity'],
            antigen_system=request.POST['antigen_system'],
            clinical_significance=request.POST['clinical_significance'],
            status='identified',
            first_identified_at=timezone.now(),
            first_identified_branch_id=request.session.get('branch_id'),
            identified_by=request.user,
        )
        write_audit(
            actor=request.user,
            action='patient.antibody.add',
            entity_table='patients_patientantibody',
            entity_id=ab.pk,
            after={'patient_id': patient.pk, 'specificity': ab.specificity,
                   'antigen_system': ab.antigen_system,
                   'clinical_significance': ab.clinical_significance},
        )
        messages.success(request, "Antibody recorded.")
        return redirect('patients:detail', pk=pk)
    return render(request, 'patients/add_antibody.html', {'patient': patient})


@login_required
def add_requirement(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    if not has_permission(request.user, 'patient.special_requirement', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('patients:detail', pk=pk)

    if request.method == 'POST':
        req = PatientTransfusionRequirement.objects.create(
            patient=patient,
            requirement=request.POST['requirement'],
            antigen_spec=request.POST.get('antigen_spec', ''),
            reason=request.POST['reason'],
            set_by=request.user,
        )
        write_audit(
            actor=request.user,
            action='patient.requirement.add',
            entity_table='patients_patienttransfusionrequirement',
            entity_id=req.pk,
            after={'patient_id': patient.pk, 'requirement': req.requirement,
                   'antigen_spec': req.antigen_spec},
        )
        messages.success(request, "Special requirement added.")
        return redirect('patients:detail', pk=pk)
    return render(request, 'patients/add_requirement.html', {'patient': patient})


@login_required
def traceability_report(request, pk):
    """Full transfusion history and vein-to-vein traceability for a patient."""
    from transfusion.models import IssueTransaction, TransfusionReaction
    from django.http import HttpResponse

    patient = get_object_or_404(Patient, pk=pk)
    transactions = IssueTransaction.objects.filter(
        patient=patient
    ).select_related(
        'blood_unit', 'blood_unit__component_type', 'blood_unit__donation',
        'blood_unit__donation__donor', 'issued_by', 'intended_branch',
    ).order_by('-issued_at')

    if request.GET.get('format') == 'pdf':
        from core.pdf_reports import render_patient_traceability_pdf
        pdf = render_patient_traceability_pdf(patient, list(transactions))
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="traceability_patient_{patient.pk}.pdf"'
        return resp

    return render(request, 'patients/traceability.html', {
        'patient': patient,
        'transactions': transactions,
    })


@login_required
def merge_patient(request, pk):
    """
    Merge a duplicate patient record into a surviving record.
    The source record is marked as merged and all future lookups redirect to the target.
    """
    from django.db import transaction
    source = get_object_or_404(Patient, pk=pk, record_status='active')

    if not has_permission(request.user, 'patient.register', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('patients:detail', pk=pk)

    if request.method == 'POST':
        target_id = request.POST.get('target_patient_id', '').strip()
        reason = request.POST.get('reason', '').strip()
        if not target_id or not reason:
            messages.error(request, "Target patient ID and reason are both required.")
            return render(request, 'patients/merge.html', {'source': source})

        try:
            target = Patient.objects.get(pk=target_id, record_status='active')
        except Patient.DoesNotExist:
            messages.error(request, f"Patient #{target_id} not found or is not active.")
            return render(request, 'patients/merge.html', {'source': source})

        if target.pk == source.pk:
            messages.error(request, "Cannot merge a patient record into itself.")
            return render(request, 'patients/merge.html', {'source': source})

        with transaction.atomic():
            source.merged_into = target
            source.record_status = 'merged'
            source.save(update_fields=['merged_into', 'record_status'])

            # Reassign blood group history, antibodies, requirements, requests to target
            source.blood_groups.update(patient=target)
            source.antibodies.update(patient=target)
            source.special_requirements.update(patient=target)
            source.blood_requests.update(patient=target)

            write_audit(
                actor=request.user,
                action='patient.merge',
                entity_table='patients_patient',
                entity_id=source.pk,
                after={
                    'merged_into': target.pk,
                    'reason': reason,
                },
            )
        messages.success(request, f"Patient #{source.pk} merged into Patient #{target.pk}.")
        return redirect('patients:detail', pk=target.pk)

    return render(request, 'patients/merge.html', {'source': source})


@login_required
def record_consent(request, pk):
    """Record informed consent for transfusion."""
    patient = get_object_or_404(Patient, pk=pk)

    if request.method == 'POST':
        from django.utils import timezone as tz
        import datetime
        obtained_at = tz.now()
        valid_until = obtained_at.date() + datetime.timedelta(days=30)

        consent_type = request.POST.get('consent_type', 'verbal')
        emergency = (consent_type == 'implied')

        if emergency and not request.POST.get('emergency_justification', '').strip():
            messages.error(request, "Emergency justification is required for implied consent.")
            return render(request, 'patients/record_consent.html', {
                'patient': patient,
                'consent_types': TransfusionConsent.CONSENT_TYPES,
            })

        consent = TransfusionConsent.objects.create(
            patient=patient,
            consent_type=consent_type,
            alternatives_discussed=request.POST.get('alternatives_discussed') == 'on',
            risks_explained=request.POST.get('risks_explained') == 'on',
            questions_answered=request.POST.get('questions_answered') == 'on',
            obtained_by=request.user,
            obtained_at=obtained_at,
            form_reference=request.POST.get('form_reference', '').strip(),
            emergency_justification=request.POST.get('emergency_justification', '').strip(),
            valid_until=valid_until,
            branch_id=request.session.get('branch_id'),
            notes=request.POST.get('notes', ''),
        )
        write_audit(
            actor=request.user,
            action='patient.consent.record',
            entity_table='patients_transfusionconsent',
            entity_id=consent.pk,
            after={'type': consent_type, 'valid_until': str(valid_until)},
        )
        messages.success(request, f"Consent recorded — valid until {valid_until}.")
        return redirect('patients:detail', pk=pk)

    return render(request, 'patients/record_consent.html', {
        'patient': patient,
        'consent_types': TransfusionConsent.CONSENT_TYPES,
        'existing': patient.consents.filter(status='active').order_by('-obtained_at').first(),
    })


@login_required
def investigate_discrepancy(request, pk):
    """
    Blood group discrepancy investigation workflow.
    Opens or updates a BloodGroupDiscrepancyInvestigation record.
    BCSH 2012 / SHOT guidance: all discrepancies must reach root cause before
    electronic crossmatch is re-enabled.
    """
    from core.models import Branch
    patient = get_object_or_404(Patient, pk=pk)
    if not has_permission(request.user, 'patient.blood_group', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('patients:detail', pk=pk)

    discrepant_groups = patient.blood_groups.filter(is_discrepant=True).order_by('-determined_at')
    prior_group = patient.blood_groups.filter(is_discrepant=False).order_by('-determined_at').first()

    # Existing open investigation if any
    existing = BloodGroupDiscrepancyInvestigation.objects.filter(
        patient=patient, status='open',
    ).order_by('-opened_at').first()

    if not discrepant_groups.exists() and not existing:
        messages.info(request, "No active discrepancies for this patient.")
        return redirect('patients:detail', pk=pk)

    branch_id = request.session.get('branch_id')
    branch = Branch.objects.filter(pk=branch_id).first() if branch_id else Branch.objects.first()
    if not branch:
        messages.error(request, "Branch not found. Please re-select your branch.")
        return redirect('core:select_branch')

    if request.method == 'POST':
        action = request.POST.get('action')
        root_cause = request.POST.get('root_cause', '')
        resolution_action = request.POST.get('resolution_action', '').strip()
        notes = request.POST.get('notes', '').strip()
        shot_reportable = request.POST.get('shot_reportable') == '1'
        wbit_event = request.POST.get('wbit_event') == '1'
        confirmed_group_pk = request.POST.get('confirmed_group_pk', '').strip()

        if not resolution_action:
            messages.error(request, "Resolution action is required.")
            return render(request, 'patients/investigate_discrepancy.html', {
                'patient': patient,
                'discrepant_groups': discrepant_groups,
                'prior_group': prior_group,
                'existing': existing,
                'root_cause_choices': BloodGroupDiscrepancyInvestigation.ROOT_CAUSE_CHOICES,
                'blood_groups': patient.blood_groups.order_by('-determined_at')[:10],
            })

        discrepant_group = discrepant_groups.first()
        confirmed_group = None
        if confirmed_group_pk:
            try:
                confirmed_group = PatientBloodGroup.objects.get(pk=confirmed_group_pk, patient=patient)
            except PatientBloodGroup.DoesNotExist:
                pass

        if existing:
            inv = existing
            inv.root_cause = root_cause
            inv.resolution_action = resolution_action
            inv.notes = notes
            inv.shot_reportable = shot_reportable
            inv.wbit_event = wbit_event
            if confirmed_group:
                inv.confirmed_group = confirmed_group
        else:
            inv = BloodGroupDiscrepancyInvestigation(
                patient=patient,
                discrepant_group=discrepant_group or discrepant_groups.first(),
                prior_group=prior_group,
                root_cause=root_cause,
                resolution_action=resolution_action,
                notes=notes,
                shot_reportable=shot_reportable,
                wbit_event=wbit_event,
                confirmed_group=confirmed_group,
                investigated_by=request.user,
                branch=branch,
            )

        if action == 'resolve':
            inv.status = 'resolved'
            inv.resolved_by = request.user
            inv.resolved_at = timezone.now()
            inv.save()
            # Clear the discrepant flag — electronic crossmatch is now unblocked
            discrepant_groups.update(is_discrepant=False)
            write_audit(
                actor=request.user,
                action='patient.discrepancy.resolved',
                entity_table='patients_bloodgroupdiscrepancyinvestigation',
                entity_id=inv.pk,
                after={
                    'root_cause': root_cause,
                    'resolution_action': resolution_action,
                    'shot_reportable': shot_reportable,
                    'wbit_event': wbit_event,
                },
                branch=branch,
            )
            messages.success(request, "Discrepancy investigation resolved. Electronic crossmatch unblocked.")
        elif action == 'escalate':
            inv.status = 'escalated'
            inv.save()
            write_audit(
                actor=request.user,
                action='patient.discrepancy.escalated',
                entity_table='patients_bloodgroupdiscrepancyinvestigation',
                entity_id=inv.pk,
                after={'notes': notes},
                branch=branch,
            )
            messages.warning(request, "Investigation escalated. Senior review required. Manual crossmatch only.")
        else:
            # Save as open (in-progress update)
            inv.save()
            messages.info(request, "Investigation updated.")

        return redirect('patients:detail', pk=pk)

    return render(request, 'patients/investigate_discrepancy.html', {
        'patient': patient,
        'discrepant_groups': discrepant_groups,
        'prior_group': prior_group,
        'existing': existing,
        'root_cause_choices': BloodGroupDiscrepancyInvestigation.ROOT_CAUSE_CHOICES,
        'blood_groups': patient.blood_groups.order_by('-determined_at')[:10],
    })


@login_required
def discrepancy_investigation_list(request):
    """
    Lab/quality view — all blood group discrepancy investigations for this branch.
    Filterable by status (open / resolved / escalated).
    """
    branch_id = request.session.get('branch_id')
    qs = BloodGroupDiscrepancyInvestigation.objects.filter(
        branch_id=branch_id,
    ).select_related('patient', 'discrepant_group', 'investigated_by').order_by('-opened_at')

    status_filter = request.GET.get('status', 'open')
    if status_filter in ('open', 'resolved', 'escalated'):
        qs = qs.filter(status=status_filter)

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'patients/discrepancy_investigation_list.html', {
        'page_obj': page,
        'status_filter': status_filter,
        'open_count': BloodGroupDiscrepancyInvestigation.objects.filter(branch_id=branch_id, status='open').count(),
        'escalated_count': BloodGroupDiscrepancyInvestigation.objects.filter(branch_id=branch_id, status='escalated').count(),
    })


@login_required
def record_patient_phenotype(request, pk):
    """
    Record or update extended red cell phenotype for a patient.

    BCSH 2016: Extended phenotyping (Rh C/c/E/e + Kell) should be performed
    before the first transfusion in all chronically transfused patients and
    women of childbearing potential.
    """
    from core.models import Branch
    patient = get_object_or_404(Patient, pk=pk)
    if not has_permission(request.user, 'patient.blood_group', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('patients:detail', pk=pk)

    branch_id = request.session.get('branch_id')
    branch = Branch.objects.filter(pk=branch_id).first() if branch_id else Branch.objects.first()
    if not branch:
        messages.error(request, "Branch not found. Please re-select your branch.")
        return redirect('core:select_branch')

    existing = getattr(patient, 'phenotype', None)
    ANTIGEN_FIELDS = PatientPhenotype.ANTIGEN_FIELDS

    if request.method == 'POST':
        from audit.utils import create_signature

        antigen_values = {}
        for antigen in ANTIGEN_FIELDS:
            val = request.POST.get(f'antigen_{antigen}', '')
            if val == 'pos':
                antigen_values[antigen] = True
            elif val == 'neg':
                antigen_values[antigen] = False
            else:
                antigen_values[antigen] = None

        method = request.POST.get('method', 'serology')
        notes  = request.POST.get('notes', '').strip()

        esign = create_signature(
            signer=request.user,
            meaning='patient_phenotype_record',
            payload_data={'patient_id': patient.pk, 'antigens': {k: v for k, v in antigen_values.items() if v is not None}},
        )

        if existing:
            for field, val in antigen_values.items():
                setattr(existing, field, val)
            existing.method = method
            existing.notes = notes
            existing.typed_at = timezone.now()
            existing.typed_by = request.user
            existing.esign = esign
            existing.save()
            action = 'patient.phenotype.updated'
        else:
            existing = PatientPhenotype.objects.create(
                patient=patient,
                typed_at=timezone.now(),
                typed_by=request.user,
                method=method,
                branch=branch,
                notes=notes,
                esign=esign,
                **antigen_values,
            )
            action = 'patient.phenotype.created'

        write_audit(
            actor=request.user,
            action=action,
            entity_table='patients_patientphenotype',
            entity_id=existing.pk,
            after={'typed_antigens': sum(1 for v in antigen_values.values() if v is not None)},
            branch=branch,
        )
        messages.success(request, "Extended phenotype saved.")
        return redirect('patients:detail', pk=pk)

    return render(request, 'patients/record_phenotype.html', {
        'patient': patient,
        'existing': existing,
        'antigen_systems': PatientPhenotype.ANTIGEN_SYSTEMS,
        'antigen_fields': ANTIGEN_FIELDS,
        'method_choices': PatientPhenotype.METHODS,
    })


@login_required
def withdraw_consent(request, pk, consent_pk):
    """Withdraw an active transfusion consent."""
    patient = get_object_or_404(Patient, pk=pk)
    consent = get_object_or_404(TransfusionConsent, pk=consent_pk, patient=patient)

    if consent.status != 'active':
        messages.warning(request, "This consent is already inactive.")
        return redirect('patients:detail', pk=pk)

    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, "Reason for withdrawal is required.")
            return render(request, 'patients/withdraw_consent.html', {'patient': patient, 'consent': consent})

        consent.status = 'withdrawn'
        consent.withdrawn_at = timezone.now()
        consent.withdrawn_by = request.user
        consent.notes = (consent.notes + '\n\nWithdrawal reason: ' + reason).strip()
        consent.save(update_fields=['status', 'withdrawn_at', 'withdrawn_by', 'notes'])

        write_audit(
            actor=request.user,
            action='patient.consent.withdrawn',
            entity_table='patients_transfusionconsent',
            entity_id=consent.pk,
            after={'reason': reason},
        )
        messages.warning(request, "Consent withdrawn. Routine transfusions must not proceed without a new consent.")

        # Raise a critical alert so opted-in branch staff are notified by email
        branch_id = request.session.get('branch_id')
        if branch_id:
            try:
                from core.models import Branch
                from core.alerts import _raise_alert
                branch = Branch.objects.get(pk=branch_id)
                _raise_alert(
                    branch=branch,
                    alert_type='consent_withdrawn',
                    severity='critical',
                    message=f"Patient consent withdrawn (Patient #{patient.pk}). "
                            f"Routine transfusions must not proceed without new consent. "
                            f"Reason: {reason[:200]}",
                    entity_table='patients_transfusionconsent',
                    entity_id=consent.pk,
                )
            except Exception:
                pass

        return redirect('patients:detail', pk=pk)

    return render(request, 'patients/withdraw_consent.html', {'patient': patient, 'consent': consent})


# ─── Therapeutic Phlebotomy ────────────────────────────────────────────────────

@login_required
def therapeutic_phlebotomy_list(request):
    branch_id = request.session.get('branch_id')
    qs = TherapeuticPhlebotomy.objects.filter(branch_id=branch_id).select_related('patient')

    status_filter = request.GET.get('status', '')
    indication_filter = request.GET.get('indication', '')
    if status_filter:
        qs = qs.filter(status=status_filter)
    if indication_filter:
        qs = qs.filter(indication=indication_filter)

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'patients/tp_list.html', {
        'page_obj': page,
        'status_filter': status_filter,
        'indication_filter': indication_filter,
        'statuses': TherapeuticPhlebotomy.STATUSES,
        'indications': TherapeuticPhlebotomy.INDICATIONS,
    })


@login_required
def therapeutic_phlebotomy_schedule(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk)
    if request.method == 'POST':
        indication = request.POST.get('indication', '').strip()
        scheduled_date = request.POST.get('scheduled_date', '').strip()
        target_volume = request.POST.get('target_volume_ml', '450').strip() or '450'
        disposition = request.POST.get('disposition', 'discard')
        indication_notes = request.POST.get('indication_notes', '').strip()

        if not indication or not scheduled_date:
            messages.error(request, "Indication and scheduled date are required.")
            return render(request, 'patients/tp_schedule.html', {
                'patient': patient,
                'indications': TherapeuticPhlebotomy.INDICATIONS,
                'dispositions': TherapeuticPhlebotomy.DISPOSITIONS,
            })

        branch_id = request.session.get('branch_id')
        try:
            target_volume_ml_int = int(target_volume)
        except (ValueError, TypeError):
            target_volume_ml_int = 450
        tp = TherapeuticPhlebotomy.objects.create(
            patient=patient,
            indication=indication,
            indication_notes=indication_notes,
            scheduled_date=scheduled_date,
            target_volume_ml=target_volume_ml_int,
            disposition=disposition,
            branch_id=branch_id,
            created_by=request.user,
        )
        write_audit(
            actor=request.user,
            action='therapeutic_phlebotomy.scheduled',
            entity_table='patients_therapeuticphlebotomy',
            entity_id=tp.pk,
            after={'patient': patient_pk, 'indication': indication, 'scheduled_date': scheduled_date},
        )
        messages.success(request, f"Therapeutic phlebotomy scheduled for {tp.scheduled_date}.")
        return redirect('patients:tp_detail', pk=tp.pk)

    return render(request, 'patients/tp_schedule.html', {
        'patient': patient,
        'indications': TherapeuticPhlebotomy.INDICATIONS,
        'dispositions': TherapeuticPhlebotomy.DISPOSITIONS,
    })


@login_required
def therapeutic_phlebotomy_detail(request, pk):
    tp = get_object_or_404(TherapeuticPhlebotomy, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'perform':
            tp.performed_date = request.POST.get('performed_date') or None
            tp.actual_volume_ml = request.POST.get('actual_volume_ml') or None
            tp.hb_pre_g_dl = request.POST.get('hb_pre_g_dl') or None
            tp.hb_post_g_dl = request.POST.get('hb_post_g_dl') or None
            tp.haematocrit_pre = request.POST.get('haematocrit_pre') or None
            tp.haematocrit_post = request.POST.get('haematocrit_post') or None
            tp.ferritin_pre_ug_l = request.POST.get('ferritin_pre_ug_l') or None
            tp.bp_systolic = request.POST.get('bp_systolic') or None
            tp.bp_diastolic = request.POST.get('bp_diastolic') or None
            tp.pulse_bpm = request.POST.get('pulse_bpm') or None
            tp.weight_kg = request.POST.get('weight_kg') or None
            tp.notes = request.POST.get('notes', tp.notes)
            tp.performed_by = request.user
            tp.status = 'completed'
            tp.save()
            write_audit(
                actor=request.user,
                action='therapeutic_phlebotomy.completed',
                entity_table='patients_therapeuticphlebotomy',
                entity_id=tp.pk,
                after={'status': 'completed', 'actual_volume_ml': str(tp.actual_volume_ml)},
            )
            messages.success(request, "Therapeutic phlebotomy recorded as completed.")

        elif action == 'cancel':
            tp.status = 'cancelled'
            cancel_reason = request.POST.get('cancel_reason', '')
            tp.notes = (tp.notes + '\nCancelled: ' + cancel_reason).strip()
            tp.save(update_fields=['status', 'notes'])
            write_audit(
                actor=request.user,
                action='therapeutic_phlebotomy.cancelled',
                entity_table='patients_therapeuticphlebotomy',
                entity_id=tp.pk,
                after={'status': 'cancelled', 'cancel_reason': cancel_reason},
            )
            messages.warning(request, "Session cancelled.")

        elif action == 'declined':
            tp.status = 'declined'
            tp.save(update_fields=['status'])
            write_audit(
                actor=request.user,
                action='therapeutic_phlebotomy.declined',
                entity_table='patients_therapeuticphlebotomy',
                entity_id=tp.pk,
                after={'status': 'declined'},
            )
            messages.warning(request, "Recorded as patient declined.")

        return redirect('patients:tp_detail', pk=pk)

    history = TherapeuticPhlebotomy.objects.filter(
        patient=tp.patient
    ).exclude(pk=tp.pk).order_by('-scheduled_date')[:10]
    return render(request, 'patients/tp_detail.html', {'tp': tp, 'history': history})


# ─── Antenatal Anti-D Programme ───────────────────────────────────────────────

@login_required
def antenatal_list(request):
    branch_id = request.session.get('branch_id')
    qs = AntenatalRecord.objects.filter(branch_id=branch_id).select_related('patient')

    outcome_filter = request.GET.get('outcome', '')
    rh_neg_only = request.GET.get('rh_neg', '') == '1'
    if outcome_filter:
        qs = qs.filter(outcome=outcome_filter)
    if rh_neg_only:
        qs = qs.filter(is_rh_d_negative=True)

    raadp_due = []
    for anc in AntenatalRecord.objects.filter(branch_id=branch_id, outcome='ongoing', is_rh_d_negative=True):
        if anc.requires_raadp():
            for label, weeks, due_date in anc.raadp_schedule():
                already_given = anc.anti_d_doses.filter(indication=label).exists()
                if not already_given and due_date <= timezone.now().date():
                    raadp_due.append({'anc': anc, 'label': label, 'weeks': weeks, 'due_date': due_date})

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'patients/antenatal_list.html', {
        'page_obj': page,
        'outcome_filter': outcome_filter,
        'rh_neg_only': rh_neg_only,
        'outcomes': AntenatalRecord.OUTCOMES,
        'raadp_due': raadp_due,
    })


@login_required
def antenatal_create(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk)
    if request.method == 'POST':
        edd = request.POST.get('edd', '').strip()
        abo = request.POST.get('abo', '').strip()
        rh_d = request.POST.get('rh_d', '').strip()
        partner_rh_d = request.POST.get('partner_rh_d', '').strip()
        gestation_wks = request.POST.get('gestation_at_booking_wks', '').strip() or None

        if not edd:
            messages.error(request, "Estimated date of delivery is required.")
            return render(request, 'patients/antenatal_form.html', {
                'patient': patient,
                'abo_choices': [('A','A'),('B','B'),('AB','AB'),('O','O')],
                'rh_choices': [('pos','Positive'),('neg','Negative'),('weak_d','Weak D')],
                'partner_rh_choices': [('pos','Positive'),('neg','Negative'),('unknown','Unknown')],
            })

        branch_id = request.session.get('branch_id')
        anc = AntenatalRecord.objects.create(
            patient=patient,
            edd=edd,
            abo=abo,
            rh_d=rh_d,
            partner_rh_d=partner_rh_d,
            gestation_at_booking_wks=_to_int_or_none(gestation_wks),
            branch_id=branch_id,
            created_by=request.user,
        )
        write_audit(
            actor=request.user,
            action='antenatal.record.created',
            entity_table='patients_antenatalrecord',
            entity_id=anc.pk,
            after={'patient': patient_pk, 'edd': edd, 'rh_d': rh_d},
        )
        messages.success(request, f"Antenatal record created. EDD: {anc.edd}.")
        return redirect('patients:antenatal_detail', pk=anc.pk)

    return render(request, 'patients/antenatal_form.html', {
        'patient': patient,
        'abo_choices': [('A','A'),('B','B'),('AB','AB'),('O','O')],
        'rh_choices': [('pos','Positive'),('neg','Negative'),('weak_d','Weak D')],
        'partner_rh_choices': [('pos','Positive'),('neg','Negative'),('unknown','Unknown')],
    })


@login_required
def antenatal_detail(request, pk):
    anc = get_object_or_404(AntenatalRecord, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_outcome':
            anc.outcome = request.POST.get('outcome', anc.outcome)
            anc.delivery_date = request.POST.get('delivery_date') or None
            anc.cord_blood_group_abo = request.POST.get('cord_blood_group_abo', '')
            anc.cord_blood_group_rh = request.POST.get('cord_blood_group_rh', '')
            anc.save()
            write_audit(
                actor=request.user,
                action='antenatal.outcome.updated',
                entity_table='patients_antenatalrecord',
                entity_id=anc.pk,
                after={'outcome': anc.outcome, 'delivery_date': str(anc.delivery_date)},
            )
            messages.success(request, "Outcome updated.")
            if anc.postnatal_anti_d_required():
                messages.warning(request, "Cord blood is RhD-positive — postnatal Anti-D must be given within 72 hours.")

        elif action == 'record_anti_d':
            indication = request.POST.get('indication', '').strip()
            product = request.POST.get('product', '').strip()
            dose_iu = request.POST.get('dose_iu', '').strip()
            batch_number = request.POST.get('batch_number', '').strip()
            expiry_date = request.POST.get('expiry_date', '').strip()
            administered_at = request.POST.get('administered_at', '').strip()
            kleihauer_done = request.POST.get('kleihauer_done') == 'on'
            kleihauer_pct = request.POST.get('kleihauer_result_pct', '').strip() or None
            fmh_ml = request.POST.get('fmh_volume_ml', '').strip() or None
            extra_dose = request.POST.get('additional_dose_required') == 'on'

            if not all([indication, product, dose_iu, batch_number, expiry_date, administered_at]):
                messages.error(request, "All Anti-D fields are required.")
                return redirect('patients:antenatal_detail', pk=pk)

            try:
                from django.utils.dateparse import parse_datetime
                administered_at_dt = parse_datetime(administered_at)
                if administered_at_dt is None:
                    raise ValueError("unparseable")
            except (ValueError, TypeError):
                messages.error(request, f"Invalid date/time format for 'Administered at': {administered_at!r}. Use the date-time picker.")
                return redirect('patients:antenatal_detail', pk=pk)

            if kleihauer_pct and not fmh_ml:
                try:
                    fmh_ml = str(round(float(kleihauer_pct) / 100 * 1800, 1))
                    if float(fmh_ml) > 4.0:
                        extra_dose = True
                except (ValueError, TypeError):
                    pass

            dose = AntiDProphylaxis.objects.create(
                antenatal_record=anc,
                indication=indication,
                product=product,
                dose_iu=_to_int_or_none(dose_iu) or 0,
                batch_number=batch_number,
                expiry_date=expiry_date,
                administered_at=administered_at_dt,
                administered_by=request.user,
                kleihauer_done=kleihauer_done,
                kleihauer_result_pct=kleihauer_pct,
                fmh_volume_ml=fmh_ml,
                additional_dose_required=extra_dose,
            )
            write_audit(
                actor=request.user,
                action='anti_d.administered',
                entity_table='patients_antidprophylaxis',
                entity_id=dose.pk,
                after={'indication': indication, 'dose_iu': dose_iu, 'kleihauer_done': kleihauer_done},
            )
            msg = f"Anti-D {dose_iu} IU ({indication}) recorded."
            if extra_dose:
                msg += " WARNING: FMH >4 mL — additional dose required."
            messages.success(request, msg)

        return redirect('patients:antenatal_detail', pk=pk)

    anti_d_doses = anc.anti_d_doses.select_related('administered_by').order_by('-administered_at')
    raadp_schedule = anc.raadp_schedule()
    schedule_with_status = []
    for label, weeks, due_date in raadp_schedule:
        given = anc.anti_d_doses.filter(indication=label).first()
        overdue = not given and due_date <= timezone.now().date()
        schedule_with_status.append({'label': label, 'weeks': weeks, 'due_date': due_date,
                                      'given': given, 'overdue': overdue})

    return render(request, 'patients/antenatal_detail.html', {
        'anc': anc,
        'anti_d_doses': anti_d_doses,
        'schedule_with_status': schedule_with_status,
        'indications': AntiDProphylaxis.INDICATIONS,
        'products': AntiDProphylaxis.PRODUCTS,
        'outcomes': AntenatalRecord.OUTCOMES,
        'abo_choices': [('A','A'),('B','B'),('AB','AB'),('O','O')],
        'rh_choices': [('pos','Positive'),('neg','Negative'),('weak_d','Weak D')],
    })


@login_required
def patient_blood_group_card_pdf(request, pk):
    """Wallet-sized blood group card PDF for the patient."""
    from django.http import HttpResponse
    from core.models import Branch
    from core.pdf_reports import render_patient_blood_group_card_pdf

    patient = get_object_or_404(Patient, pk=pk)
    branch_id = request.session.get('branch_id')
    try:
        branch_name = Branch.objects.get(pk=branch_id).name if branch_id else 'Blood Bank'
    except Branch.DoesNotExist:
        branch_name = 'Blood Bank'

    pdf = render_patient_blood_group_card_pdf(patient, branch_name)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="bg_card_patient_{pk}.pdf"'
    return resp


@login_required
def hdfn_list(request):
    """List of HDFN cases — filterable by outcome and severity."""
    branch_id = request.session.get('branch_id')
    # Show all cases where the mother's patient record was created at this branch,
    # or fall back to all cases if no branch set.
    qs = HaemolyticDiseaseCase.objects.all()
    if branch_id:
        qs = qs.filter(
            mother__registration_branch_id=branch_id
        ).distinct()
    qs = qs.select_related('mother', 'neonate', 'maternal_antibody').order_by('-created_at')

    severity_filter = request.GET.get('severity', '')
    if severity_filter:
        qs = qs.filter(severity=severity_filter)

    outcome_filter = request.GET.get('outcome', '')
    if outcome_filter:
        qs = qs.filter(outcome=outcome_filter)

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'patients/hdfn_list.html', {
        'page_obj':       page,
        'severity_filter': severity_filter,
        'outcome_filter':  outcome_filter,
        'severities':     HaemolyticDiseaseCase.SEVERITY,
        'outcomes':       HaemolyticDiseaseCase.OUTCOMES,
    })


@login_required
def hdfn_create(request, mother_pk):
    """Create a new HDFN case for a maternal patient."""
    mother = get_object_or_404(Patient, pk=mother_pk)

    if request.method == 'POST':
        antibody_pk = request.POST.get('maternal_antibody_id', '').strip() or None
        ab = get_object_or_404(PatientAntibody, pk=antibody_pk) if antibody_pk else None

        def _int(key):
            v = request.POST.get(key, '').strip()
            return _to_int_or_none(v)

        def _dec(key):
            v = request.POST.get(key, '').strip()
            return v if v else None

        case = HaemolyticDiseaseCase.objects.create(
            mother=mother,
            antibody_specificity_text=request.POST.get('antibody_specificity_text', ''),
            maternal_antibody=ab,
            gestational_age_wks=_int('gestational_age_wks'),
            birth_weight_g=_int('birth_weight_g'),
            cord_hb_g_dl=_dec('cord_hb_g_dl'),
            direct_antiglobulin_test=request.POST.get('direct_antiglobulin_test', 'not_done'),
            peak_bilirubin_umol_l=_int('peak_bilirubin_umol_l'),
            hours_at_peak_bilirubin=_int('hours_at_peak_bilirubin'),
            severity=request.POST.get('severity', ''),
            phototherapy_started=request.POST.get('phototherapy_started') == 'on',
            phototherapy_start_date=request.POST.get('phototherapy_start_date') or None,
            phototherapy_duration_h=_int('phototherapy_duration_h'),
            exchange_transfusion_done=request.POST.get('exchange_transfusion_done') == 'on',
            exchange_transfusion_date=request.POST.get('exchange_transfusion_date') or None,
            num_exchange_volumes=_int('num_exchange_volumes'),
            iut_required=request.POST.get('iut_required') == 'on',
            num_iut_procedures=_int('num_iut_procedures') or 0,
            ivig_given=request.POST.get('ivig_given') == 'on',
            outcome=request.POST.get('outcome', ''),
            clinical_notes=request.POST.get('clinical_notes', '').strip(),
            reported_to_haemovigilance=request.POST.get('reported_to_haemovigilance') == 'on',
            recorded_by=request.user,
        )

        write_audit(
            actor=request.user,
            action='patients.hdfn.create',
            entity_table='patients_haemolyticdiseasecase',
            entity_id=case.pk,
            after={
                'mother_pk': mother_pk,
                'severity': case.severity,
                'outcome': case.outcome,
                'exchange': case.exchange_transfusion_done,
                'iut': case.iut_required,
            },
        )
        messages.success(request, f"HDFN case #{case.pk} created.")
        return redirect('patients:hdfn_detail', pk=case.pk)

    maternal_antibodies = mother.antibodies.filter(clinical_significance='significant')
    return render(request, 'patients/hdfn_form.html', {
        'mother':             mother,
        'maternal_antibodies': maternal_antibodies,
        'severities':         HaemolyticDiseaseCase.SEVERITY,
        'outcomes':           HaemolyticDiseaseCase.OUTCOMES,
        'dat_choices':        HaemolyticDiseaseCase.DAT_RESULTS,
    })


@login_required
def hdfn_detail(request, pk):
    """View/update an HDFN case — records treatment updates and outcome."""
    case = get_object_or_404(HaemolyticDiseaseCase, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')

        def _int(key):
            v = request.POST.get(key, '').strip()
            return _to_int_or_none(v)

        if action == 'update_treatment':
            case.severity = request.POST.get('severity', case.severity)
            case.phototherapy_started = request.POST.get('phototherapy_started') == 'on'
            case.phototherapy_start_date = request.POST.get('phototherapy_start_date') or case.phototherapy_start_date
            case.phototherapy_duration_h = _int('phototherapy_duration_h') or case.phototherapy_duration_h
            case.exchange_transfusion_done = request.POST.get('exchange_transfusion_done') == 'on'
            case.exchange_transfusion_date = request.POST.get('exchange_transfusion_date') or case.exchange_transfusion_date
            case.num_exchange_volumes = _int('num_exchange_volumes') or case.num_exchange_volumes
            case.iut_required = request.POST.get('iut_required') == 'on'
            case.num_iut_procedures = _int('num_iut_procedures') or case.num_iut_procedures
            case.ivig_given = request.POST.get('ivig_given') == 'on'
            case.reported_to_haemovigilance = request.POST.get('reported_to_haemovigilance') == 'on'
            case.save()
            write_audit(
                actor=request.user,
                action='patients.hdfn.update_treatment',
                entity_table='patients_haemolyticdiseasecase',
                entity_id=case.pk,
                after={'severity': case.severity, 'exchange': case.exchange_transfusion_done},
            )
            messages.success(request, "Treatment details updated.")

        elif action == 'update_outcome':
            case.outcome = request.POST.get('outcome', case.outcome)
            case.clinical_notes = request.POST.get('clinical_notes', case.clinical_notes)
            case.peak_bilirubin_umol_l = _int('peak_bilirubin_umol_l') or case.peak_bilirubin_umol_l
            case.hours_at_peak_bilirubin = _int('hours_at_peak_bilirubin') or case.hours_at_peak_bilirubin
            case.save()
            write_audit(
                actor=request.user,
                action='patients.hdfn.update_outcome',
                entity_table='patients_haemolyticdiseasecase',
                entity_id=case.pk,
                after={'outcome': case.outcome},
            )
            messages.success(request, "Outcome updated.")

        elif action == 'link_neonate':
            neonate_pk = request.POST.get('neonate_pk', '').strip()
            if neonate_pk:
                try:
                    neonate_pk_int = int(neonate_pk)
                except (ValueError, TypeError):
                    messages.error(request, "Invalid patient ID.")
                else:
                    try:
                        neonate = Patient.objects.get(pk=neonate_pk_int)
                        case.neonate = neonate
                        case.save(update_fields=['neonate'])
                        write_audit(
                            actor=request.user,
                            action='patients.hdfn.neonate_linked',
                            entity_table='patients_haemolyticdiseasecase',
                            entity_id=case.pk,
                            after={'neonate_pk': neonate.pk},
                        )
                        messages.success(request, f"Neonate Patient #{neonate_pk} linked.")
                    except Patient.DoesNotExist:
                        messages.error(request, "Patient not found.")

        return redirect('patients:hdfn_detail', pk=pk)

    return render(request, 'patients/hdfn_detail.html', {
        'case':        case,
        'severities':  HaemolyticDiseaseCase.SEVERITY,
        'outcomes':    HaemolyticDiseaseCase.OUTCOMES,
        'dat_choices': HaemolyticDiseaseCase.DAT_RESULTS,
    })

