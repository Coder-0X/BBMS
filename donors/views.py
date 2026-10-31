from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone

from .models import Donor, Donation, DonorAdverseEvent, DonorPhenotype, DonorMilestone, RetentionCampaign, CampaignEnrollment, DonorHealthQuestionnaire
from compliance.engine import check_donor_eligibility
from core.did import generate_did
from core.models import RefFacility
from audit.utils import write_audit
from accounts.permissions import has_permission


@login_required
def donor_list(request):
    branch_id = request.session.get('branch_id')
    qs = Donor.objects.filter(registration_branch_id=branch_id).order_by('-created_at')

    q = request.GET.get('q', '').strip()
    if q:
        from privacy.vault import blind_index
        # Blind index is an HMAC — must match exactly; also allow ID search
        if q.isdigit():
            qs = qs.filter(pk=int(q))
        else:
            idx = blind_index(q)
            qs = qs.filter(subject__name_blind_index=idx)

    status_filter = request.GET.get('deferral', '')
    if status_filter:
        qs = qs.filter(deferral_status=status_filter)

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'donors/list.html', {
        'page_obj': page,
        'q': q,
        'deferral': status_filter,
    })


@login_required
def register_donor(request):
    if not has_permission(request.user, 'donor.register', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('core:dashboard')

    if request.method == 'POST':
        from privacy.models import SubjectIdentity
        subject = SubjectIdentity.create_from_plain(
            name=request.POST['full_name'],
            national_id=request.POST.get('national_id', ''),
            contact=request.POST.get('contact', ''),
            subject_type='donor',
            created_by=request.user,
        )
        donor = Donor.objects.create(
            subject=subject,
            sex=request.POST.get('sex', 'U'),
            dob=request.POST.get('dob') or None,
            registration_branch_id=request.session.get('branch_id'),
            created_by=request.user,
        )
        write_audit(
            actor=request.user,
            action='donor.register',
            entity_table='donors_donor',
            entity_id=donor.pk,
            after={'deferral_status': donor.deferral_status},
        )
        messages.success(request, f"Donor #{donor.pk} registered.")
        return redirect('donors:detail', pk=donor.pk)
    return render(request, 'donors/register.html')


@login_required
def donor_detail(request, pk):
    donor = get_object_or_404(Donor, pk=pk)
    branch_id = request.session.get('branch_id')
    if donor.registration_branch_id != branch_id and not request.user.is_superuser:
        messages.error(request, "You do not have permission to view donors from another branch.")
        return redirect('donors:list')
    return render(request, 'donors/detail.html', {
        'donor': donor,
        'donations': donor.donations.order_by('-donated_at')[:20],
        'adverse_events': donor.adverse_events.order_by('-recorded_at')[:10],
        'previous_dhqs': donor.health_questionnaires.order_by('-completed_at')[:5],
    })


@login_required
def eligibility_screen(request, pk):
    donor = get_object_or_404(Donor, pk=pk)

    if request.method == 'POST':
        branch_id = request.session.get('branch_id')
        from core.models import Branch
        branch = get_object_or_404(Branch, pk=branch_id)

        donor_data = {
            'age': request.POST.get('age'),
            'weight_kg': request.POST.get('weight_kg'),
            'hb_g_dl': request.POST.get('hemoglobin'),
            'bp_systolic': request.POST.get('bp_systolic'),
            'bp_diastolic': request.POST.get('bp_diastolic'),
            'pulse': request.POST.get('pulse'),
            # Compute interval from database, not from staff-entered form field
            'days_since_last_donation': (
                (timezone.now().date() - donor.last_donation_date).days
                if donor.last_donation_date else None
            ),
            'deferral_status': donor.deferral_status,
            'sex': donor.sex,
        }
        failures = check_donor_eligibility(branch, donor_data)

        if failures:
            # Persist deferral if not already deferred
            if donor.deferral_status == 'active':
                donor.deferral_status = 'temporary_defer'
                donor.deferral_reason = '; '.join(f.message for f in failures)
                donor.save(update_fields=['deferral_status', 'deferral_reason'])
                from audit.utils import write_audit as _wa
                _wa(
                    actor=request.user,
                    action='donor.eligibility.deferred',
                    entity_table='donors_donor',
                    entity_id=donor.pk,
                    before={'deferral_status': 'active'},
                    after={'deferral_status': 'temporary_defer',
                           'deferral_reason': donor.deferral_reason},
                )
            # Re-render form with failures so staff see citations
            return render(request, 'donors/eligibility.html', {
                'donor': donor,
                'failures': failures,
                'form_data': request.POST,
            })

        messages.success(request, "Donor is eligible to donate.")
        return redirect('donors:record_donation', pk=pk)

    return render(request, 'donors/eligibility.html', {'donor': donor})


@login_required
def record_donation(request, pk):
    donor = get_object_or_404(Donor, pk=pk)

    if not donor.is_eligible_to_donate():
        if donor.days_until_eligible > 0:
            messages.error(
                request,
                f"Donor is not currently eligible to donate. Minimum donation interval not met: "
                f"{donor.days_until_eligible} days remaining before next eligible donation."
            )
        else:
            messages.error(
                request,
                f"Donor is not currently eligible to donate ({donor.get_deferral_status_display()}: {donor.deferral_reason})."
            )
        return redirect('donors:detail', pk=pk)

    if request.method == 'POST':
        from privacy.models import ConsentRecord
        consent = ConsentRecord.objects.create(
            subject=donor.subject,
            subject_type='donor',
            lawful_basis='consent',
            purpose='blood_donation',
            notice_version='1.0',
            captured_by=request.user,
        )

        branch_id = request.session.get('branch_id')
        if not branch_id:
            messages.error(request, "No branch selected. Please select a branch before recording a donation.")
            return redirect('donors:detail', pk=pk)
        from core.models import RefFacility
        try:
            facility = RefFacility.objects.get(branch_id=branch_id)
        except RefFacility.DoesNotExist:
            messages.error(request, "This branch has no facility code configured. Contact your administrator.")
            return redirect('donors:detail', pk=pk)

        serial = facility.next_serial()
        did = generate_did(facility.facility_code, serial)

        purpose = request.POST.get('donation_purpose', 'allogeneic')
        recipient_id = request.POST.get('intended_recipient_id', '').strip() or None

        try:
            volume_ml = int(request.POST.get('volume_ml', 450))
        except (ValueError, TypeError):
            volume_ml = 450

        donation = Donation.objects.create(
            donor=donor,
            donation_type=request.POST.get('donation_type', 'whole_blood'),
            volume_ml=volume_ml,
            collected_by=request.user,
            consent=consent,
            donated_at=timezone.now(),
            branch_id=branch_id,
            donation_purpose=purpose,
            intended_recipient_id=recipient_id if purpose in ('autologous', 'directed') else None,
        )

        donor.total_donations = donor.donations.count()
        if donor.first_donation_date is None:
            donor.first_donation_date = timezone.now().date()
        donor.last_donation_date = timezone.now().date()
        donor.save(update_fields=['total_donations', 'first_donation_date', 'last_donation_date'])
        donor.check_and_create_milestones()

        write_audit(
            actor=request.user,
            action='donor.donation',
            entity_table='donors_donation',
            entity_id=donation.pk,
            after={'donation_type': donation.donation_type, 'volume_ml': donation.volume_ml},
        )
        messages.success(request, f"Donation #{donation.pk} recorded.")
        return redirect('donors:detail', pk=pk)
    return render(request, 'donors/record_donation.html', {'donor': donor})


@login_required
def deferral_letter(request, pk):
    """PDF deferral notification letter for a deferred donor."""
    from django.http import HttpResponse
    from core.models import Branch
    donor = get_object_or_404(Donor, pk=pk)
    if donor.deferral_status == 'active':
        messages.info(request, "This donor is not currently deferred.")
        return redirect('donors:detail', pk=pk)

    branch_id = request.session.get('branch_id')
    try:
        branch_name = Branch.objects.get(pk=branch_id).name if branch_id else 'Blood Bank'
    except Branch.DoesNotExist:
        branch_name = 'Blood Bank'

    from core.pdf_reports import render_donor_deferral_letter_pdf
    pdf = render_donor_deferral_letter_pdf(donor, branch_name)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="deferral_letter_donor_{donor.pk}.pdf"'
    return resp


@login_required
def record_adverse_event(request, donation_pk):
    """Record or view a donor adverse event for a specific donation."""
    from .models import Donation, DonorAdverseEvent
    donation = get_object_or_404(Donation, pk=donation_pk)
    donor = donation.donor

    if hasattr(donation, 'adverse_event'):
        messages.info(request, "An adverse event is already recorded for this donation.")
        return redirect('donors:detail', pk=donor.pk)

    if request.method == 'POST':
        event = DonorAdverseEvent.objects.create(
            donation=donation,
            donor=donor,
            event_type=request.POST['event_type'],
            severity=request.POST['severity'],
            loss_of_consciousness=request.POST.get('loss_of_consciousness') == '1',
            injury=request.POST.get('injury') == '1',
            treatment=request.POST.get('treatment', '').strip(),
            outcome=request.POST['outcome'],
            reportable=request.POST.get('reportable') == '1',
            report_ref=request.POST.get('report_ref', '').strip(),
            recorded_by=request.user,
        )
        write_audit(
            actor=request.user,
            action='donor.adverse_event.record',
            entity_table='donors_donoradverseevent',
            entity_id=event.pk,
            after={
                'donation_id': donation.pk,
                'donor_id': donor.pk,
                'event_type': event.event_type,
                'severity': event.severity,
            },
        )
        messages.success(request, f"Adverse event recorded for donation #{donation.pk}.")
        return redirect('donors:detail', pk=donor.pk)

    from .models import DonorAdverseEvent as DAE
    return render(request, 'donors/record_adverse_event.html', {
        'donation': donation,
        'donor': donor,
        'event_types': DAE.TYPES,
        'severity_choices': DAE.SEVERITY,
        'outcome_choices': DAE.OUTCOMES,
    })


@login_required
def record_phenotype(request, pk):
    """Record or update extended red cell phenotype for a donor."""
    donor = get_object_or_404(Donor, pk=pk)
    if not has_permission(request.user, 'test.perform', request.session.get('branch_id')):
        messages.error(request, "Permission denied — Lab Technologist role required.")
        return redirect('donors:detail', pk=pk)

    existing = getattr(donor, 'phenotype', None)

    if request.method == 'POST':
        from django.utils import timezone as tz

        def _parse_tri(name):
            v = request.POST.get(name, '')
            if v == 'pos': return True
            if v == 'neg': return False
            return None

        kwargs = {a: _parse_tri(a) for a in DonorPhenotype.ANTIGEN_FIELDS}
        kwargs.update({
            'donor': donor,
            'typed_at': tz.now(),
            'typed_by': request.user,
            'method': request.POST.get('method', 'serology'),
            'notes': request.POST.get('notes', ''),
        })

        if existing:
            for k, v in kwargs.items():
                if k != 'donor':
                    setattr(existing, k, v)
            existing.save()
            pheno = existing
        else:
            pheno = DonorPhenotype.objects.create(**kwargs)

        write_audit(
            actor=request.user,
            action='donor.phenotype.record',
            entity_table='donors_donorphenotype',
            entity_id=pheno.pk,
            after={'donor': donor.pk, 'method': pheno.method, 'neg_set': list(pheno.antigen_negative_set().keys())},
        )

        # How many patients have antibodies this donor could serve
        from patients.models import PatientAntibody
        neg_antigens = list(pheno.antigen_negative_set().keys())
        matchable_patients = PatientAntibody.objects.filter(
            specificity__in=[f'anti-{a}' for a in neg_antigens],
            clinical_significance='significant',
            status='identified',
        ).values('patient').distinct().count()

        messages.success(request,
            f"Phenotype recorded — {len(neg_antigens)} antigen-negative specificities. "
            f"This donor could serve {matchable_patients} patient(s) with matching antibodies.")
        return redirect('donors:detail', pk=pk)

    return render(request, 'donors/phenotype_form.html', {
        'donor': donor,
        'existing': existing,
        'antigen_fields': DonorPhenotype.ANTIGEN_FIELDS,
        'methods': DonorPhenotype.METHODS,
        'antigen_systems': {
            'Rh': ['C','c','E','e'],
            'Kell': ['K','k'],
            'Duffy': ['Fya','Fyb'],
            'Kidd': ['Jka','Jkb'],
            'MNS': ['M','N','S','s'],
            'Lewis': ['Lea','Leb'],
            'P1PK': ['P1'],
        },
    })


@login_required
def donor_milestones(request):
    """List recent donor milestones — for certificate generation and recognition."""
    branch_id = request.session.get('branch_id')
    milestones = DonorMilestone.objects.filter(
        donor__registration_branch_id=branch_id
    ).select_related('donor').order_by('-achieved_at')

    type_filter = request.GET.get('type', '')
    if type_filter:
        milestones = milestones.filter(milestone_type=type_filter)

    pending_certificates = milestones.filter(certificate_generated=False)
    paginator = Paginator(milestones, 30)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'donors/milestones.html', {
        'page_obj': page,
        'pending_certificates': pending_certificates[:10],
        'type_filter': type_filter,
        'milestone_types': DonorMilestone.TYPES,
    })


@login_required
def lapsed_donors(request):
    """
    List donors who have not donated in the past 6 months.
    Blood banks lose ~20% of donors per year — proactive re-engagement is critical.
    """
    from datetime import timedelta
    branch_id = request.session.get('branch_id')
    try:
        months = int(request.GET.get('months', 6))
    except (ValueError, TypeError):
        months = 6
    cutoff = timezone.now().date() - timedelta(days=months * 30)

    # Donors registered at this branch with deferral_status not 'permanent_defer'
    # whose most recent donation is before the cutoff (or who have never donated)
    from django.db.models import Max, OuterRef, Subquery
    latest_donation = Donation.objects.filter(
        donor=OuterRef('pk')
    ).order_by('-donated_at').values('donated_at')[:1]

    qs = Donor.objects.filter(
        registration_branch_id=branch_id,
    ).exclude(
        deferral_status='permanent_defer',
    ).annotate(
        _latest_donated_at=Subquery(latest_donation)
    ).filter(
        _latest_donated_at__lt=cutoff,
    ).order_by('_latest_donated_at')

    # Also include donors who have never donated at all
    never_donated = Donor.objects.filter(
        registration_branch_id=branch_id,
        donations__isnull=True,
    ).exclude(deferral_status='permanent_defer')

    from itertools import chain
    all_lapsed = list(qs) + list(never_donated)

    blood_group_filter = request.GET.get('abo', '')
    if blood_group_filter:
        all_lapsed = [d for d in all_lapsed if d.blood_group_abo == blood_group_filter]

    if request.GET.get('format') == 'pdf':
        from core.pdf_reports import render_lapsed_donors_pdf
        from django.http import HttpResponse
        from core.models import Branch
        branch = Branch.objects.filter(pk=branch_id).first() if branch_id else None
        if not branch:
            messages.error(request, "Branch not found. Please re-select your branch.")
            return redirect('core:select_branch')
        pdf = render_lapsed_donors_pdf(all_lapsed, branch.name, months)
        resp = HttpResponse(pdf, content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="lapsed_donors_{branch.facility_code}.pdf"'
        return resp

    paginator = Paginator(all_lapsed, 30)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'donors/lapsed_donors.html', {
        'page_obj': page,
        'months': months,
        'abo_filter': blood_group_filter,
        'total_count': len(all_lapsed),
    })


@login_required
def blood_group_card_pdf(request, pk):
    """Generate a printable blood group ID card for a confirmed donor."""
    from django.http import HttpResponse
    from core.models import Branch
    from core.pdf_reports import render_donor_blood_group_card_pdf

    donor = get_object_or_404(Donor, pk=pk)

    if not donor.blood_group_abo or not donor.blood_group_rh:
        messages.warning(request, "Donor does not have a confirmed blood group on file yet.")
        return redirect('donors:detail', pk=pk)

    branch_id = request.session.get('branch_id')
    try:
        branch_name = Branch.objects.get(pk=branch_id).name if branch_id else 'Blood Bank'
    except Branch.DoesNotExist:
        branch_name = 'Blood Bank'

    pdf = render_donor_blood_group_card_pdf(donor, branch_name)
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="blood_group_card_donor_{donor.pk}.pdf"'
    return resp


@login_required
def start_lookback(request, pk):
    """Initiate a lookback campaign for a donor who tested TTI-positive."""
    from .models import Donor
    from transfusion.lookback import create_lookback_campaign
    donor = get_object_or_404(Donor, pk=pk)

    if not request.method == 'POST':
        # Show available test codes from their reactive results
        reactive_tests = []
        for donation in donor.donations.all():
            for result in donation.test_results.filter(result='reactive'):
                if result.test_code not in [t['code'] for t in reactive_tests]:
                    reactive_tests.append({'code': result.test_code, 'name': result.test.name if hasattr(result, 'test') else result.test_code})
        return render(request, 'donors/start_lookback.html', {
            'donor': donor,
            'reactive_tests': reactive_tests,
        })

    test_code = request.POST.get('test_code', '').strip()
    notes = request.POST.get('notes', '').strip()
    if not test_code:
        messages.error(request, "Test code is required.")
        return redirect('donors:detail', pk=pk)

    campaign, count = create_lookback_campaign(
        donor=donor,
        triggered_by_test=test_code,
        actor=request.user,
        notes=notes,
    )
    messages.warning(request, f"Lookback LB-{campaign.pk} created — {count} recipient(s) identified for notification.")
    return redirect('transfusion:lookback_detail', pk=campaign.pk)


# ---------------------------------------------------------------------------
# Donor Retention Campaigns
# ---------------------------------------------------------------------------

@login_required
def campaign_list(request):
    branch_id = request.session.get('branch_id')
    campaigns = RetentionCampaign.objects.filter(branch_id=branch_id).order_by('-created_at')
    status_filter = request.GET.get('status', '')
    if status_filter:
        campaigns = campaigns.filter(status=status_filter)
    paginator = Paginator(campaigns, 20)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'donors/campaign_list.html', {
        'page_obj': page,
        'status_filter': status_filter,
        'status_choices': RetentionCampaign.STATUS_CHOICES,
    })


@login_required
def campaign_create(request):
    branch_id = request.session.get('branch_id')
    if request.method == 'POST':
        from core.models import Branch
        branch = get_object_or_404(Branch, pk=branch_id)
        try:
            goal_donations = int(request.POST.get('goal_donations', 0) or 0)
        except (ValueError, TypeError):
            goal_donations = 0
        campaign = RetentionCampaign.objects.create(
            name=request.POST['name'],
            branch=branch,
            segment=request.POST['segment'],
            target_abo=request.POST.get('target_abo', ''),
            target_rh=request.POST.get('target_rh', ''),
            channel=request.POST['channel'],
            message_template=request.POST['message_template'],
            goal_donations=goal_donations,
            status='draft',
            start_date=request.POST.get('start_date') or None,
            end_date=request.POST.get('end_date') or None,
            notes=request.POST.get('notes', ''),
            created_by=request.user,
        )
        write_audit(
            actor=request.user,
            action='campaign.created',
            entity_table='donors_retentioncampaign',
            entity_id=campaign.pk,
            after={'name': campaign.name, 'segment': campaign.segment},
        )
        messages.success(request, f"Campaign '{campaign.name}' created.")
        return redirect('donors:campaign_detail', pk=campaign.pk)

    return render(request, 'donors/campaign_form.html', {
        'segment_choices': RetentionCampaign.SEGMENT_CHOICES,
        'channel_choices': RetentionCampaign.CHANNEL_CHOICES,
        'abo_choices': [('A','A'),('B','B'),('AB','AB'),('O','O')],
        'rh_choices': [('pos','Positive'),('neg','Negative')],
    })


@login_required
def campaign_detail(request, pk):
    campaign = get_object_or_404(RetentionCampaign, pk=pk)
    branch_id = request.session.get('branch_id')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'activate':
            campaign.status = 'active'
            campaign.save(update_fields=['status'])
            write_audit(
                actor=request.user,
                action='campaign.status_changed',
                entity_table='donors_retentioncampaign',
                entity_id=campaign.pk,
                before={'status': 'draft'},
                after={'status': 'active', 'name': campaign.name},
            )
            messages.success(request, "Campaign activated.")

        elif action == 'pause':
            old_status = campaign.status
            campaign.status = 'paused'
            campaign.save(update_fields=['status'])
            write_audit(
                actor=request.user,
                action='campaign.status_changed',
                entity_table='donors_retentioncampaign',
                entity_id=campaign.pk,
                before={'status': old_status},
                after={'status': 'paused', 'name': campaign.name},
            )
            messages.info(request, "Campaign paused.")

        elif action == 'close':
            old_status = campaign.status
            campaign.status = 'closed'
            campaign.save(update_fields=['status'])
            write_audit(
                actor=request.user,
                action='campaign.status_changed',
                entity_table='donors_retentioncampaign',
                entity_id=campaign.pk,
                before={'status': old_status},
                after={'status': 'closed', 'name': campaign.name},
            )
            messages.info(request, "Campaign closed.")

        elif action == 'enroll_lapsed':
            # Auto-enroll matching lapsed donors based on segment
            from datetime import timedelta
            from django.db.models import Max

            cutoff_map = {
                'lapsed_3m': 90,
                'lapsed_6m': 180,
                'lapsed_12m': 365,
            }
            days = cutoff_map.get(campaign.segment, 180)
            cutoff = timezone.now().date() - timedelta(days=days)

            qs = Donor.objects.filter(
                registration_branch_id=branch_id,
                last_donation_date__lt=cutoff,
            ).exclude(deferral_status='permanent_defer')

            if campaign.target_abo:
                qs = qs.filter(blood_group_abo=campaign.target_abo)
            if campaign.target_rh:
                qs = qs.filter(blood_group_rh=campaign.target_rh)
            if campaign.segment == 'high_value':
                qs = Donor.objects.filter(
                    registration_branch_id=branch_id,
                    total_donations__gte=10,
                ).exclude(deferral_status='permanent_defer')
            elif campaign.segment == 'new_never_returned':
                qs = Donor.objects.filter(
                    registration_branch_id=branch_id,
                    total_donations=1,
                ).exclude(deferral_status='permanent_defer')

            enrolled = 0
            for donor in qs:
                _, created = CampaignEnrollment.objects.get_or_create(
                    campaign=campaign, donor=donor
                )
                if created:
                    enrolled += 1

            messages.success(request, f"{enrolled} donor(s) enrolled.")
            write_audit(
                actor=request.user,
                action='campaign.enrolled_batch',
                entity_table='donors_retentioncampaign',
                entity_id=campaign.pk,
                after={'enrolled': enrolled},
            )

        elif action == 'update_enrollment':
            enroll_pk = request.POST.get('enrollment_id')
            enroll = get_object_or_404(CampaignEnrollment, pk=enroll_pk, campaign=campaign)
            new_status = request.POST.get('status')
            if new_status in dict(CampaignEnrollment.STATUS_CHOICES):
                old_status = enroll.status
                now = timezone.now()
                enroll.status = new_status
                enroll.updated_by = request.user
                enroll.outcome_notes = request.POST.get('notes', enroll.outcome_notes)
                if new_status == 'contacted' and not enroll.contacted_at:
                    enroll.contacted_at = now
                elif new_status == 'responded' and not enroll.responded_at:
                    enroll.responded_at = now
                elif new_status == 'donated' and not enroll.donated_at:
                    enroll.donated_at = now
                enroll.save()
                write_audit(
                    actor=request.user,
                    action='campaign.enrollment_updated',
                    entity_table='donors_campaignenrollment',
                    entity_id=enroll.pk,
                    before={'status': old_status},
                    after={'status': new_status, 'campaign_pk': campaign.pk},
                )
            return redirect('donors:campaign_detail', pk=campaign.pk)

        return redirect('donors:campaign_detail', pk=campaign.pk)

    enrollments = campaign.enrollments.select_related('donor').order_by('status', 'enrolled_at')
    status_filter = request.GET.get('estatus', '')
    if status_filter:
        enrollments = enrollments.filter(status=status_filter)

    paginator = Paginator(enrollments, 30)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'donors/campaign_detail.html', {
        'campaign': campaign,
        'page_obj': page,
        'enrollment_status_choices': CampaignEnrollment.STATUS_CHOICES,
        'estatus_filter': status_filter,
    })


@login_required
def dhq_create(request, pk):
    """
    Donor Health History Questionnaire — must be completed before every donation.
    AABB §5.5.1 / FDA 2023 / EU Directive 2004/33/EC Annex II.
    """
    donor = get_object_or_404(Donor, pk=pk)
    branch_id = request.session.get('branch_id')
    if donor.registration_branch_id != branch_id and not request.user.is_superuser:
        messages.error(request, "Permission denied.")
        return redirect('donors:list')

    if request.method == 'POST':
        def _bool(key):
            return request.POST.get(key) == '1'

        dhq = DonorHealthQuestionnaire.objects.create(
            donor=donor,
            completed_at=timezone.now(),
            completed_by=request.user,
            weight_kg=request.POST.get('weight_kg') or None,
            hb_g_dl=request.POST.get('hb_g_dl') or None,
            bp_systolic=request.POST.get('bp_systolic') or None,
            bp_diastolic=request.POST.get('bp_diastolic') or None,
            pulse=request.POST.get('pulse') or None,
            temperature_c=request.POST.get('temperature_c') or None,
            feeling_well=_bool('feeling_well'),
            recent_illness=_bool('recent_illness'),
            recent_illness_detail=request.POST.get('recent_illness_detail', ''),
            on_antibiotics=_bool('on_antibiotics'),
            on_other_medications=_bool('on_other_medications'),
            medications_detail=request.POST.get('medications_detail', ''),
            donated_elsewhere_recently=_bool('donated_elsewhere_recently'),
            donated_elsewhere_detail=request.POST.get('donated_elsewhere_detail', ''),
            recent_infection=_bool('recent_infection'),
            recent_infection_detail=request.POST.get('recent_infection_detail', ''),
            travel_risk=request.POST.get('travel_risk', 'none'),
            travel_detail=request.POST.get('travel_detail', ''),
            malaria_history=_bool('malaria_history'),
            tattoo_or_piercing_12m=_bool('tattoo_or_piercing_12m'),
            needlestick_12m=_bool('needlestick_12m'),
            sti_history=_bool('sti_history'),
            new_sexual_partner_3m=_bool('new_sexual_partner_3m'),
            sexual_contact_risk_3m=_bool('sexual_contact_risk_3m'),
            sex_for_money_or_drugs=_bool('sex_for_money_or_drugs'),
            iv_drug_use_ever=_bool('iv_drug_use_ever'),
            prior_transfusion=_bool('prior_transfusion'),
            prior_transfusion_date=request.POST.get('prior_transfusion_date') or None,
            prior_transplant=_bool('prior_transplant'),
            prior_transplant_detail=request.POST.get('prior_transplant_detail', ''),
            pregnancy_6m=_bool('pregnancy_6m'),
            cancer_history=_bool('cancer_history'),
            heart_disease_history=_bool('heart_disease_history'),
            bleeding_disorder=_bool('bleeding_disorder'),
            diabetes=_bool('diabetes'),
            cjd_risk_factor=_bool('cjd_risk_factor'),
            donor_signature=_bool('donor_signature'),
            staff_signature=_bool('staff_signature'),
            notes=request.POST.get('notes', ''),
        )

        # Auto-evaluate deferral triggers
        triggers = dhq.has_deferral_triggers()
        if triggers:
            dhq.outcome = 'deferred_temp'
            dhq.deferral_reasons = '\n'.join(f'• {t}' for t in triggers)
            dhq.save(update_fields=['outcome', 'deferral_reasons'])
            # Apply deferral to donor if not already deferred
            if donor.deferral_status == 'active':
                perm_triggers = [t for t in triggers if 'permanent' in t.lower()]
                donor.deferral_status = 'permanent_defer' if perm_triggers else 'temporary_defer'
                donor.deferral_reason = dhq.deferral_reasons
                donor.save(update_fields=['deferral_status', 'deferral_reason'])
            write_audit(
                actor=request.user,
                action='donor.dhq.deferral_triggered',
                entity_table='donors_donorhealthquestionnaire',
                entity_id=dhq.pk,
                after={'triggers': triggers, 'outcome': dhq.outcome},
            )
            messages.warning(request,
                f"DHQ completed — {len(triggers)} deferral trigger(s) found. "
                "Donor deferred. Review detail below before proceeding.")
            return redirect('donors:dhq_detail', pk=donor.pk, dhq_pk=dhq.pk)
        else:
            dhq.outcome = 'eligible'
            dhq.save(update_fields=['outcome'])
            write_audit(
                actor=request.user,
                action='donor.dhq.eligible',
                entity_table='donors_donorhealthquestionnaire',
                entity_id=dhq.pk,
                after={'outcome': 'eligible'},
            )
            messages.success(request, "DHQ completed — no deferral triggers. Donor eligible to proceed.")
            return redirect('donors:eligibility', pk=donor.pk)

    previous_dhqs = donor.health_questionnaires.order_by('-completed_at')[:3]
    return render(request, 'donors/dhq_form.html', {
        'donor': donor,
        'previous_dhqs': previous_dhqs,
        'travel_risk_choices': DonorHealthQuestionnaire.TRAVEL_RISK,
    })


@login_required
def dhq_detail(request, pk, dhq_pk):
    """View a completed DHQ."""
    donor = get_object_or_404(Donor, pk=pk)
    dhq = get_object_or_404(DonorHealthQuestionnaire, pk=dhq_pk, donor=donor)
    return render(request, 'donors/dhq_detail.html', {'donor': donor, 'dhq': dhq})


@login_required
def donor_dsr_view(request, pk):
    """
    Log and process a Data Subject Rights request for a donor.

    IMPORTANT: Erasure requests for donors with blood safety records are
    legally refused under EU Blood Directive 2002/98/EC Annex VI (30-year
    retention obligation). Marketing data is still erased. See privacy/dsr_handler.py.
    """
    if not request.user.is_staff:
        messages.error(request, "Only staff can process Data Subject Rights requests.")
        return redirect('donors:detail', pk=pk)

    donor = get_object_or_404(Donor, pk=pk)
    from privacy.models import DSRRequest

    existing = DSRRequest.objects.filter(subject=donor.subject).order_by('-requested_at')

    if request.method == 'POST':
        request_type = request.POST.get('request_type')
        if request_type not in dict(DSRRequest.TYPES):
            messages.error(request, "Invalid request type.")
            return redirect('donors:dsr', pk=pk)

        dsr = DSRRequest.objects.create(
            subject=donor.subject,
            request_type=request_type,
            status='received',
        )
        write_audit(
            actor=request.user,
            action='privacy.dsr.received',
            entity_table='privacy_dsrrequest',
            entity_id=dsr.pk,
            after={'type': request_type},
        )

        # Process immediately if erase or access
        if request_type in ('erase', 'access'):
            from privacy.dsr_handler import handle_erasure_request, handle_access_request
            try:
                if request_type == 'erase':
                    result = handle_erasure_request(dsr, actor=request.user)
                    decision = result.get('decision', '')
                    if decision == 'partial_erasure_legal_refusal':
                        messages.warning(
                            request,
                            "Erasure request partially refused: blood-safety traceability records "
                            "must be retained 30 years (EU Blood Directive 2002/98/EC). "
                            "Marketing data and contact information have been erased."
                        )
                    else:
                        messages.success(request, "Full erasure completed — no blood-safety records found.")
                else:
                    handle_access_request(dsr, actor=request.user)
                    messages.success(request, "Access report generated and DSR completed.")
            except Exception as exc:
                messages.error(request, f"Error processing DSR: {exc}")
        else:
            messages.info(request, f"DSR '{request_type}' logged. Assign to your DPO for manual handling.")

        return redirect('donors:dsr', pk=pk)

    return render(request, 'donors/dsr.html', {
        'donor': donor,
        'existing_dsrs': existing,
        'dsr_types': DSRRequest.TYPES,
    })

