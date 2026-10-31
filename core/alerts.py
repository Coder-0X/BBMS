"""
Software-only alerting. No hardware required.
Call check_all_alerts(branch) from a cron job or management command.
"""
from django.utils import timezone
from .models import Alert


def check_all_alerts(branch):
    """Run all alert checks for a branch and write new Alert rows."""
    _check_low_inventory(branch)
    _check_critical_stock_by_blood_group(branch)
    _check_near_expiry(branch)
    _check_pending_emergency_reviews(branch)
    _check_blood_group_discrepancies(branch)
    _check_deferred_donors_eligible_again(branch)
    _check_expired_units(branch)
    _check_ct_ratio(branch)
    _check_cold_chain(branch)
    _check_reagent_qc(branch)
    _check_equipment_calibration(branch)
    _check_ungrouped_units(branch)
    _check_sop_reviews(branch)
    _check_competency_overdue(branch)
    _check_nc_backlog(branch)
    _check_raadp_overdue(branch)
    _check_lookback_pending(branch)
    _check_committee_actions_overdue(branch)
    _check_hdfn_unreported(branch)
    _check_pbm_post_hb_gap(branch)
    _check_crossmatch_expiry(branch)


def _check_low_inventory(branch):
    from inventory.models import BloodUnit
    from .models import ConfigTarget

    targets = ConfigTarget.objects.filter(branch=branch)
    for target in targets:
        in_stock = BloodUnit.objects.filter(
            owner_branch=branch,
            component_class=target.component_class,
            status='available',
        ).count()

        # Rough daily demand estimate from last 14 days
        from django.db.models import Count
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=14)
        from transfusion.models import IssueTransaction
        issued = IssueTransaction.objects.filter(
            intended_branch=branch,
            blood_unit__component_class=target.component_class,
            issued_at__gte=cutoff,
        ).count()
        avg_daily = issued / 14 if issued else 0
        days_of_supply = (in_stock / avg_daily) if avg_daily > 0 else float('inf')

        if days_of_supply < target.target_days_of_supply:
            severity = 'critical' if days_of_supply < 1 else 'warning'
            _raise_alert(
                branch=branch,
                alert_type='low_inventory',
                severity=severity,
                message=(
                    f"{target.component_class} stock at {branch.name} is low "
                    f"({in_stock} units, ~{days_of_supply:.1f} days supply). "
                    f"Target is {target.target_days_of_supply} days."
                ),
                entity_table='core_configtarget',
                entity_id=target.pk,
            )


def _check_near_expiry(branch):
    from inventory.models import BloodUnit
    from .models import ConfigTarget

    targets = ConfigTarget.objects.filter(branch=branch)
    for target in targets:
        from datetime import timedelta
        window = timezone.now() + timedelta(hours=target.near_expiry_alert_hours)
        expiring = BloodUnit.objects.filter(
            owner_branch=branch,
            component_class=target.component_class,
            status='available',
            expiry_datetime__lte=window,
        )
        if expiring.exists():
            _raise_alert(
                branch=branch,
                alert_type='near_expiry',
                severity='warning',
                message=(
                    f"{expiring.count()} {target.component_class} unit(s) at {branch.name} "
                    f"expire within {target.near_expiry_alert_hours}h."
                ),
                entity_table='inventory_bloodunit',
                entity_id=0,
            )


def _check_pending_emergency_reviews(branch):
    from transfusion.models import EmergencyRelease
    pending = EmergencyRelease.objects.filter(
        request__branch=branch,
        signoff_status='pending',
    )
    for er in pending:
        _raise_alert(
            branch=branch,
            alert_type='pending_emergency_review',
            severity='critical',
            message=f"Emergency release #{er.pk} for patient #{er.patient_id} needs physician sign-off.",
            entity_table='transfusion_emergencyrelease',
            entity_id=er.pk,
        )


def _raise_alert(branch, alert_type, severity, message, entity_table=None, entity_id=None):
    """Create an alert only if one of the same type doesn't already exist (unacknowledged)."""
    from .models import Alert
    already_open = Alert.objects.filter(
        branch=branch,
        alert_type=alert_type,
        entity_table=entity_table,
        entity_id=entity_id,
        acknowledged_at__isnull=True,
    ).exists()
    if not already_open:
        alert = Alert.objects.create(
            alert_type=alert_type,
            branch=branch,
            severity=severity,
            message=message,
            entity_table=entity_table,
            entity_id=entity_id,
        )
        if severity in ('critical', 'warning'):
            from .email_notifications import send_alert_email
            send_alert_email(alert)


def _check_blood_group_discrepancies(branch):
    """Alert on unresolved patient blood group discrepancies at this branch."""
    from patients.models import PatientBloodGroup
    discrepant_count = PatientBloodGroup.objects.filter(
        is_discrepant=True,
        branch=branch,
    ).values('patient').distinct().count()
    if discrepant_count:
        _raise_alert(
            branch=branch,
            alert_type='blood_group_discrepancy',
            severity='warning',
            message=(
                f"{discrepant_count} patient(s) at {branch.name} have unresolved "
                "blood group discrepancies. Crossmatch is blocked until resolved."
            ),
            entity_table='patients_patientbloodgroup',
            entity_id=0,
        )


def _check_deferred_donors_eligible_again(branch):
    """Alert when temporarily deferred donors have passed their deferral end date."""
    from donors.models import Donor
    from datetime import date
    today = date.today()
    newly_eligible = Donor.objects.filter(
        registration_branch=branch,
        deferral_status='temporary_defer',
        deferral_until__lte=today,
    ).count()
    if newly_eligible:
        _raise_alert(
            branch=branch,
            alert_type='donor_deferral_lapsed',
            severity='info',
            message=(
                f"{newly_eligible} temporarily deferred donor(s) at {branch.name} "
                "have passed their deferral date and may be re-screened."
            ),
            entity_table='donors_donor',
            entity_id=0,
        )


def _check_expired_units(branch):
    """Alert when units have expired (status=expired) and not yet destroyed."""
    from inventory.models import BloodUnit
    count = BloodUnit.objects.filter(owner_branch=branch, status='expired').count()
    if count:
        _raise_alert(
            branch=branch,
            alert_type='unit_expired',
            severity='warning',
            message=(
                f"{count} unit(s) at {branch.name} have expired and are pending disposal. "
                "Mark them as destroyed once discarded."
            ),
            entity_table='inventory_bloodunit',
            entity_id=0,
        )


def _check_cold_chain(branch):
    """Alert on sensor offline, calibration overdue, and ongoing excursions."""
    try:
        from coldchain.models import StorageEquipment, SensorHealth, TemperatureExcursion
    except ImportError:
        return

    from datetime import timedelta
    late_threshold = timezone.now() - timedelta(minutes=15)

    for equip in StorageEquipment.objects.filter(branch=branch, status='active'):
        # Sensor offline alert
        try:
            health = equip.sensor_health
            if health.last_seen_at and health.last_seen_at < late_threshold:
                _raise_alert(
                    branch=branch,
                    alert_type='sensor_offline',
                    severity='critical',
                    message=(
                        f"Temperature sensor '{health.sensor_id}' on {equip.name} "
                        f"has not reported since {health.last_seen_at:%Y-%m-%d %H:%M} UTC."
                    ),
                    entity_table='coldchain_storageequipment',
                    entity_id=equip.pk,
                )
        except SensorHealth.DoesNotExist:
            pass

        # Calibration overdue
        if equip.is_overdue_calibration:
            _raise_alert(
                branch=branch,
                alert_type='calibration_overdue',
                severity='warning',
                message=(
                    f"Equipment '{equip.name}' calibration was due on "
                    f"{equip.calibration_due} — please schedule recalibration."
                ),
                entity_table='coldchain_storageequipment',
                entity_id=equip.pk,
            )

        # Ongoing excursion
        ongoing = TemperatureExcursion.objects.filter(equipment=equip, ended_at__isnull=True)
        for exc in ongoing:
            _raise_alert(
                branch=branch,
                alert_type='ongoing_excursion',
                severity='critical',
                message=(
                    f"ACTIVE temperature excursion on '{equip.name}' since "
                    f"{exc.started_at:%Y-%m-%d %H:%M} UTC. "
                    f"{'Units auto-quarantined.' if exc.auto_quarantine else 'Manual disposition required.'}"
                ),
                entity_table='coldchain_temperatureexcursion',
                entity_id=exc.pk,
            )


def _check_critical_stock_by_blood_group(branch):
    """
    Alert when any ABO/Rh combination is completely out of stock or critically low.
    Zero stock of any type, especially O-neg, is a patient safety issue.
    """
    from inventory.models import BloodUnit
    from transfusion.models import IssueTransaction
    from datetime import timedelta

    ABO_TYPES = ['O', 'A', 'B', 'AB']
    RH_TYPES  = ['neg', 'pos']
    COMPONENT = 'RBC'  # Primarily for RBC — the most critical

    for abo in ABO_TYPES:
        for rh in RH_TYPES:
            count = BloodUnit.objects.filter(
                owner_branch=branch,
                component_class=COMPONENT,
                status='available',
                abo_type=abo,
                rh_d_type=rh,
            ).count()

            # Calculate avg daily demand for this group
            cutoff = timezone.now() - timedelta(days=14)
            issued = IssueTransaction.objects.filter(
                intended_branch=branch,
                blood_unit__component_class=COMPONENT,
                blood_unit__abo_type=abo,
                blood_unit__rh_d_type=rh,
                issued_at__gte=cutoff,
            ).count()
            avg_daily = issued / 14 if issued else 0.5  # Assume 0.5 units/day minimum for low-demand groups

            days_supply = count / avg_daily if avg_daily > 0 else float('inf')
            label = f"{abo}{'−' if rh == 'neg' else '+'}"

            if count == 0:
                _raise_alert(
                    branch=branch,
                    alert_type='critical_stock',
                    severity='critical',
                    message=(
                        f"ZERO STOCK: No {COMPONENT} {label} units available at {branch.name}. "
                        f"Initiate emergency cross-site request immediately."
                    ),
                    entity_table='inventory_bloodunit',
                    entity_id=hash(f"{branch.pk}-{abo}-{rh}-zero") % 2147483647,
                )
            elif days_supply < 1.0 and avg_daily > 0:
                _raise_alert(
                    branch=branch,
                    alert_type='critical_stock',
                    severity='warning',
                    message=(
                        f"CRITICAL LOW: {COMPONENT} {label} at {branch.name} — "
                        f"{count} unit(s), ~{days_supply:.1f} days supply. "
                        f"Consider cross-site transfer request."
                    ),
                    entity_table='inventory_bloodunit',
                    entity_id=hash(f"{branch.pk}-{abo}-{rh}-low") % 2147483647,
                )


def _check_reagent_qc(branch):
    """Alert when reagent QC is overdue or has failed."""
    try:
        from quality.models import Reagent
    except ImportError:
        return

    for reagent in Reagent.objects.filter(active=True):
        status = reagent.qc_status(branch.pk)
        lot = reagent.current_lot()

        if status == 'fail':
            _raise_alert(
                branch=branch,
                alert_type='qc_failure',
                severity='critical',
                message=(
                    f"QC FAILURE: Reagent '{reagent.name}' failed QC at {branch.name}. "
                    f"Do not use until a passing QC run is recorded."
                ),
                entity_table='quality_reagent',
                entity_id=reagent.pk,
            )
        elif status == 'overdue':
            _raise_alert(
                branch=branch,
                alert_type='reagent_overdue_qc',
                severity='warning',
                message=(
                    f"QC OVERDUE: Reagent '{reagent.name}' at {branch.name} "
                    f"has not had QC recorded within the required {reagent.qc_interval_hours}h interval."
                ),
                entity_table='quality_reagent',
                entity_id=reagent.pk,
            )

        if lot and lot.is_expired():
            _raise_alert(
                branch=branch,
                alert_type='reagent_overdue_qc',
                severity='critical',
                message=(
                    f"EXPIRED LOT: Reagent '{reagent.name}' lot {lot.lot_number} "
                    f"at {branch.name} is expired. Do not use."
                ),
                entity_table='quality_reagentlot',
                entity_id=lot.pk,
            )


def _check_equipment_calibration(branch):
    """Alert when equipment calibration is overdue."""
    try:
        from quality.models import EquipmentCalibration
    except ImportError:
        return

    for cal in EquipmentCalibration.objects.filter(branch=branch):
        if cal.is_overdue():
            _raise_alert(
                branch=branch,
                alert_type='equipment_calibration_due',
                severity='warning',
                message=(
                    f"CALIBRATION OVERDUE: Equipment '{cal.name}' ({cal.asset_id}) "
                    f"at {branch.name} was due for calibration on {cal.next_due}."
                ),
                entity_table='quality_equipmentcalibration',
                entity_id=cal.pk,
            )


def _check_ct_ratio(branch):
    """Alert when any component's C:T ratio exceeds the target (default >2.5 = inefficient)."""
    from core.reports import blood_utilization_report
    from .models import ConfigTarget
    data = blood_utilization_report(branch, days=30)
    ct_map = data.get('crossmatch_to_transfusion_ratio', {})
    for component, ratio in ct_map.items():
        if ratio is None:
            continue
        target = ConfigTarget.objects.filter(branch=branch, component_class=component).first()
        threshold = float(getattr(target, 'max_ct_ratio', None) or 2.5)
        if ratio > threshold:
            _raise_alert(
                branch=branch,
                alert_type='ct_ratio_high',
                severity='warning',
                message=(
                    f"{component} C:T ratio at {branch.name} is {ratio:.2f} "
                    f"(threshold {threshold:.1f}) over the last 30 days — "
                    "consider reviewing crossmatch ordering practices."
                ),
                entity_table='core_configtarget',
                entity_id=0,
            )


def _check_ungrouped_units(branch):
    """
    Alert when blood units have been in quarantine for >24h without a recorded blood grouping.
    AABB requires units to be ABO/Rh typed before release; ungrouped units block crossmatch.
    """
    from inventory.models import BloodUnit
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(hours=24)
    ungrouped = BloodUnit.objects.filter(
        owner_branch=branch,
        status__in=['quarantined', 'in_testing'],
        created_at__lte=cutoff,
        abo_type='',  # blank ABO = not yet typed
    )
    count = ungrouped.count()
    if count:
        _raise_alert(
            branch=branch,
            alert_type='ungrouped_units',
            severity='warning',
            message=(
                f"{count} blood unit(s) at {branch.name} have been in quarantine for >24h "
                "without a blood group recorded. Units cannot be crossmatched until typed. "
                "Go to Donor Detail → Blood Grouping to record ABO/Rh D typing."
            ),
            entity_table='inventory_bloodunit',
            entity_id=0,
        )


def _check_sop_reviews(branch):
    """Alert when SOPs are overdue for their mandatory periodic review."""
    try:
        from quality.models import StandardOperatingProcedure
    except ImportError:
        return
    overdue = StandardOperatingProcedure.objects.filter(
        branch=branch,
        status='active',
        next_review_due__lt=timezone.now().date(),
    )
    count = overdue.count()
    if count:
        _raise_alert(
            branch=branch,
            alert_type='sop_review_overdue',
            severity='warning',
            message=(
                f"{count} SOP(s) at {branch.name} are overdue for periodic review "
                "(ISO 15189:2022 requires at minimum annual SOP review). "
                "Go to Quality → SOP Register to review and update."
            ),
            entity_table='quality_standardoperatingprocedure',
            entity_id=0,
        )


def _check_competency_overdue(branch):
    """Alert when staff competency re-assessments are overdue."""
    try:
        from quality.models import StaffCompetency
    except ImportError:
        return
    overdue = StaffCompetency.objects.filter(
        branch=branch,
        reassessment_due__lt=timezone.now().date(),
        outcome__in=['competent', 'competent_supervised'],
    )
    count = overdue.count()
    if count:
        _raise_alert(
            branch=branch,
            alert_type='competency_overdue',
            severity='warning',
            message=(
                f"{count} staff competency record(s) at {branch.name} are overdue for re-assessment "
                "(ISO 15189:2022 clause 6.2 requires annual competency re-assessment). "
                "Go to Quality → Staff Competency to record new assessments."
            ),
            entity_table='quality_staffcompetency',
            entity_id=0,
        )


def _check_nc_backlog(branch):
    """Alert when non-conformances have been open for > 30 days without closure."""
    try:
        from quality.models import NonConformance
        from datetime import timedelta
    except ImportError:
        return
    cutoff = timezone.now() - timedelta(days=30)
    backlog = NonConformance.objects.filter(
        branch=branch,
        status__in=['open', 'under_review', 'capa_open', 'capa_verify'],
        reported_at__lte=cutoff,
    )
    count = backlog.count()
    if count:
        severity = 'critical' if count >= 5 else 'warning'
        _raise_alert(
            branch=branch,
            alert_type='nc_backlog',
            severity=severity,
            message=(
                f"{count} non-conformance(s) at {branch.name} have been open for >30 days "
                "without closure. ISO 15189:2022 requires timely CAPA resolution. "
                "Go to Quality → Non-Conformance / CAPA to review."
            ),
            entity_table='quality_nonconformance',
            entity_id=0,
        )


def _check_raadp_overdue(branch):
    """Alert when RhD-negative pregnant women have missed their scheduled Anti-D dose."""
    try:
        from patients.models import AntenatalRecord
    except ImportError:
        return
    from datetime import date as _date
    today = timezone.now().date()
    overdue_count = 0
    for anc in AntenatalRecord.objects.filter(branch=branch, outcome='ongoing', is_rh_d_negative=True):
        if not anc.requires_raadp():
            continue
        for label, weeks, due_date in anc.raadp_schedule():
            already_given = anc.anti_d_doses.filter(indication=label).exists()
            if not already_given and due_date <= today:
                overdue_count += 1
    if overdue_count:
        _raise_alert(
            branch=branch,
            alert_type='raadp_overdue',
            severity='critical',
            message=(
                f"{overdue_count} RAADP dose(s) overdue at {branch.name}. "
                "RhD-negative pregnant patients require Routine Antenatal Anti-D Prophylaxis "
                "at 28 and 34 weeks. Go to Patients → Antenatal Records."
            ),
            entity_table='patients_antenatalrecord',
            entity_id=0,
        )


def _check_lookback_pending(branch):
    """Alert when there are open lookback campaigns with pending patient notifications."""
    try:
        from transfusion.models import LookbackCampaign, LookbackNotification
    except ImportError:
        return
    pending = LookbackNotification.objects.filter(
        campaign__donor__registration_branch=branch,
        campaign__status__in=('open', 'notified'),
        status='pending',
    ).count()
    if pending:
        _raise_alert(
            branch=branch,
            alert_type='lookback_pending',
            severity='critical',
            message=(
                f"{pending} lookback notification(s) at {branch.name} are still pending. "
                "Patients who may have received potentially infectious blood must be notified urgently. "
                "Go to Transfusion → Lookback Campaigns."
            ),
            entity_table='transfusion_lookbacknotification',
            entity_id=0,
        )


def _check_committee_actions_overdue(branch):
    """Alert when transfusion committee action items are overdue."""
    try:
        from quality.models import CommitteeAction
    except ImportError:
        return
    overdue = [
        a for a in CommitteeAction.objects.filter(
            meeting__branch=branch, status__in=('open', 'in_progress'),
        ) if a.is_overdue()
    ]
    count = len(overdue)
    if count:
        _raise_alert(
            branch=branch,
            alert_type='committee_action_overdue',
            severity='warning',
            message=(
                f"{count} transfusion committee action item(s) at {branch.name} are overdue. "
                "Go to Quality → Transfusion Committee to review."
            ),
            entity_table='quality_committeeaction',
            entity_id=0,
        )


def _check_hdfn_unreported(branch):
    """Alert when a severe HDFN case (exchange transfusion) has not been reported to haemovigilance."""
    from patients.models import HaemolyticDiseaseCase
    unreported = HaemolyticDiseaseCase.objects.filter(
        mother__blood_requests__branch=branch,
        exchange_transfusion_done=True,
        reported_to_haemovigilance=False,
    ).distinct().count()
    if unreported:
        _raise_alert(
            branch=branch,
            alert_type='hdfn_unreported',
            severity='critical',
            message=(
                f"{unreported} severe HDFN case(s) with exchange transfusion at {branch.name} "
                "have not been reported to haemovigilance (SHOT). Report immediately."
            ),
            entity_table='patients_haemolyticdiseasecase',
            entity_id=0,
        )


def _check_pbm_post_hb_gap(branch):
    """Alert when >30% of RBC requests in the last 14 days lack post-transfusion Hb documentation."""
    from datetime import timedelta as _td
    from django.utils import timezone
    from transfusion.models import BloodRequest
    cutoff = timezone.now() - _td(days=14)
    rbc_qs = BloodRequest.objects.filter(
        branch=branch,
        component_class='RBC',
        requested_ts__gte=cutoff,
        units_transfused__gt=0,
    )
    total = rbc_qs.count()
    if total < 5:
        return
    missing = rbc_qs.filter(post_outcome__isnull=True).count()
    gap_pct = round(missing / total * 100)
    if gap_pct > 50:
        _raise_alert(
            branch=branch,
            alert_type='pbm_post_hb_gap',
            severity='warning',
            message=(
                f"{missing}/{total} RBC requests ({gap_pct}%) in the last 14 days at {branch.name} "
                "lack post-transfusion Hb documentation. PBM programme target: ≥50% compliance."
            ),
            entity_table='transfusion_bloodrequest',
            entity_id=0,
        )


def _check_crossmatch_expiry(branch):
    """
    Alert when crossmatched units have samples expiring within 12 hours.
    Per AABB: a sample used for electronic/serological crossmatch is valid for 72 hours
    if the patient has been transfused or pregnant within the past 3 months.
    If the sample expires, the unit can no longer be issued without a new crossmatch.
    """
    from datetime import timedelta
    from inventory.models import BloodUnit
    from transfusion.models import Crossmatch

    now = timezone.now()
    warn_window = now + timedelta(hours=12)

    # Find units in 'crossmatched' status at this branch
    crossmatched_units = BloodUnit.objects.filter(
        owner_branch=branch,
        status='crossmatched',
    )

    expiring_count = 0
    for unit in crossmatched_units:
        # Find the most recent compatible crossmatch for this unit
        xm = (
            Crossmatch.objects.filter(
                blood_unit=unit,
                result__in=['compatible', 'electronic_release'],
            )
            .select_related('sample')
            .order_by('-performed_at')
            .first()
        )
        if xm and xm.sample.validity_expiry:
            if now < xm.sample.validity_expiry <= warn_window:
                expiring_count += 1

    if expiring_count:
        _raise_alert(
            branch=branch,
            alert_type='crossmatch_expiring',
            severity='warning',
            message=(
                f"{expiring_count} crossmatched unit(s) at {branch.name} have pre-transfusion "
                "sample(s) expiring within 12 hours. Issue units promptly or obtain new samples."
            ),
            entity_table='inventory_bloodunit',
            entity_id=0,
        )
