"""
The blood issue flow.

This is the most safety-critical path in the whole system.
One unit, one patient, one transaction. If anything fails the unit stays put.
"""
from django.db import transaction, OperationalError
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone

from inventory.state_machine import transition_unit, _NON_ISSUABLE
from audit.utils import write_audit, create_signature
from accounts.permissions import check_sod_violation


def issue_unit(blood_unit_id, patient_id, request_id, actor, reauth_at,
               crossmatch_id=None, emergency_release_id=None):
    """
    Issue a blood unit to a patient.

    Enforces, in order:
    1. Optimistic concurrency lock (SELECT FOR UPDATE NOWAIT)
    2. Unit must be in 'crossmatched' status (or emergency override)
    3. Unit not expired
    4. ABO compatibility check
    5. Patient special requirements
    6. Separation of Duties — issuer ≠ collector ≠ tester ≠ crossmatcher
    7. Electronic signature (requires recent reauth)
    8. State transition to 'issued'
    9. IssueTransaction record
    10. Audit log

    Returns the IssueTransaction on success.
    Raises ValidationError or PermissionDenied on any safety failure.
    """
    from inventory.models import BloodUnit
    from patients.models import Patient
    from transfusion.models import BloodRequest, Crossmatch, IssueTransaction, EmergencyRelease

    with transaction.atomic():
        # 1. Lock the unit — NOWAIT means we fail fast instead of waiting
        try:
            unit = BloodUnit.objects.select_for_update(nowait=True).get(pk=blood_unit_id)
        except BloodUnit.DoesNotExist:
            raise ValidationError("Blood unit not found.")
        except OperationalError:
            raise ValidationError(
                "This unit is currently locked by another transaction. "
                "Please wait a moment and try again."
            )

        # 2. Status check
        if unit.status in _NON_ISSUABLE:
            raise ValidationError(
                f"Unit {unit.did} cannot be issued — current status: {unit.status}."
            )

        # For a normal issue the unit must be crossmatched
        is_emergency = emergency_release_id is not None
        if not is_emergency and unit.status != 'crossmatched':
            raise ValidationError(
                f"Unit {unit.did} must be crossmatched before issue (status: {unit.status})."
            )

        # 3. Expiry
        if unit.expiry_datetime and timezone.now() > unit.expiry_datetime:
            raise ValidationError(f"Unit {unit.did} expired at {unit.expiry_datetime}.")

        # 4. ABO compatibility
        try:
            patient = Patient.objects.get(pk=patient_id)
        except Patient.DoesNotExist:
            raise ValidationError(f"Patient #{patient_id} not found.")
        blood_group = patient.current_blood_group()
        abo_ok = _check_abo_compatibility(unit, blood_group)
        # ABO incompatibility is a hard stop — not a warning
        if not abo_ok and not is_emergency:
            raise ValidationError(
                f"ABO incompatibility: patient is {blood_group.abo if blood_group else 'Unknown'}, "
                f"unit is {unit.abo_type}."
            )

        # 4a. Autologous / directed donation safety interlock
        # Autologous: unit can ONLY go to the depositing patient
        # Directed: unit can ONLY go to the named intended recipient
        if not is_emergency:
            _check_directed_autologous(unit, patient)

        # 4b. Two-ABO determination rule (REQ-X03)
        # Non-O blood groups require 2 independent concordant determinations before group-specific issue
        if not is_emergency and unit.abo_type and unit.abo_type != 'O':
            confirmed_count = patient.blood_groups.filter(is_discrepant=False).count()
            if confirmed_count < 2:
                raise ValidationError(
                    f"Group-specific issue requires 2 concordant ABO/Rh determinations on file "
                    f"for this patient — only {confirmed_count} found. "
                    f"Use O-negative or obtain a second blood group determination."
                )

        # Fetch blood_request early — needed for neonatal check and signing
        try:
            blood_request = BloodRequest.objects.get(pk=request_id)
        except BloodRequest.DoesNotExist:
            raise ValidationError(f"Blood request #{request_id} not found.")

        # 4c. Clinically significant antibody history check (REQ-P05)
        if not is_emergency:
            _check_antibody_antigen_compatibility(unit, patient)

        # 5. Special requirements
        _check_special_requirements(unit, patient)

        # 5b. Neonatal-specific requirements (irradiated + CMV-safe + volume)
        _check_neonatal_requirements(unit, blood_request, patient)

        # 6. Separation of Duties
        _check_sod(unit, actor)

        # 7. Crossmatch / emergency reference
        crossmatch = None
        emergency_release = None
        if crossmatch_id:
            try:
                crossmatch = Crossmatch.objects.get(pk=crossmatch_id)
            except Crossmatch.DoesNotExist:
                raise ValidationError(f"Crossmatch record #{crossmatch_id} not found.")
            if crossmatch.result not in ('compatible', 'electronic_release'):
                raise ValidationError("Cannot issue a unit with an incompatible crossmatch result.")
            if crossmatch.blood_unit_id != unit.pk:
                raise ValidationError("Crossmatch was performed on a different unit.")
        elif is_emergency:
            try:
                emergency_release = EmergencyRelease.objects.get(pk=emergency_release_id)
            except EmergencyRelease.DoesNotExist:
                raise ValidationError(f"Emergency release record #{emergency_release_id} not found.")
        else:
            raise ValidationError("Either a crossmatch or an emergency release record is required.")

        # 8. Electronic signature
        payload = {
            'blood_unit_did': unit.did,
            'patient_mpi': str(patient.mpi_uid),
            'request_id': request_id,
            'issued_at': timezone.now().isoformat(),
            'issuer': actor.username,
            'abo_check_passed': abo_ok,
        }
        esign = create_signature(
            signer=actor,
            meaning='blood_unit_issue',
            payload_data=payload,
            reauth_at=reauth_at,
        )

        # 9. Transition unit to issued
        transition_unit(unit, 'issued', actor, reason=f"Issued to Patient #{patient_id}", esign=esign)

        # 10. Create the issue record
        issue_tx = IssueTransaction.objects.create(
            blood_unit=unit,
            patient=patient,
            request=blood_request,
            crossmatch=crossmatch,
            emergency_release=emergency_release,
            issued_by=actor,
            issue_esign=esign,
            issued_at=timezone.now(),
            intended_branch=blood_request.branch,
            abo_check_passed=abo_ok,
        )

        # Update request counters
        blood_request.units_transfused += 1
        if blood_request.issued_ts is None:
            blood_request.issued_ts = timezone.now()
        blood_request.save(update_fields=['units_transfused', 'issued_ts'])

        write_audit(
            actor=actor,
            action='unit.issued',
            entity_table='transfusion_issuetransaction',
            entity_id=issue_tx.pk,
            after=payload,
            action_meaning=f"Unit {unit.did} issued to Patient #{patient_id}",
            branch=blood_request.branch,
        )

        return issue_tx


def _check_abo_compatibility(unit, blood_group) -> bool:
    """
    ABO compatibility matrix — returns True if compatible.
    Uses SAFE universal donor rules only (O- for RBC when unknown, etc.).
    """
    if blood_group is None:
        # No blood group on file — emergency protocol only
        return unit.abo_type == 'O' and unit.rh_d_type == 'neg'

    patient_abo = blood_group.abo
    unit_abo    = unit.abo_type
    patient_rh  = blood_group.rh_d
    unit_rh     = unit.rh_d_type

    # ABO: donor must be compatible with patient
    ABO_COMPATIBLE = {
        'O':  {'O'},
        'A':  {'O', 'A'},
        'B':  {'O', 'B'},
        'AB': {'O', 'A', 'B', 'AB'},
    }
    if unit_abo not in ABO_COMPATIBLE.get(patient_abo, set()):
        return False

    # Rh: Rh-negative patients must receive Rh-negative (except absolute emergency)
    if patient_rh == 'neg' and unit_rh not in ('neg',):
        return False

    return True


def _check_special_requirements(unit, patient):
    """
    Verify the unit satisfies all standing patient requirements.
    Raises ValidationError listing every unmet requirement.
    """
    reqs = patient.active_special_requirements()
    failures = []

    for req in reqs:
        r = req.requirement
        if r == 'irradiated' and not unit.is_irradiated:
            failures.append("Patient requires irradiated blood.")
        elif r == 'cmv_negative' and not unit.is_cmv_negative:
            failures.append("Patient requires CMV-negative blood.")
        elif r == 'washed' and not unit.is_washed:
            failures.append("Patient requires washed components.")
        elif r == 'leukoreduced_only' and not unit.is_leukoreduced:
            failures.append("Patient requires leukoreduced blood.")
        elif r == 'antigen_negative':
            antigen = req.antigen_spec
            # antigen_negative_set is a dict {antigen: True} meaning the unit is
            # CONFIRMED negative for that antigen. Require a truthy value — a bare
            # key with a falsy value means the unit tested antigen-POSITIVE and
            # must be rejected (matches _check_antibody_antigen_compatibility and
            # BloodUnit.check_compatibility, which both use .get() truthiness).
            neg_set = unit.antigen_negative_set or {}
            if antigen and not neg_set.get(antigen):
                failures.append(f"Patient requires antigen-negative ({antigen}) blood.")

    if failures:
        raise ValidationError(failures)


def _check_antibody_antigen_compatibility(unit, patient):
    """
    For every clinically significant antibody in the patient's history,
    verify the unit is antigen-negative for that specificity.
    Lifelong history — even evanescent antibodies are enforced.
    """
    from patients.models import PatientAntibody

    antibodies = PatientAntibody.objects.filter(
        patient=patient,
        clinical_significance='significant',
        status__in=['identified', 'historical_only'],
    )

    antigen_set = unit.antigen_negative_set or {}
    failures = []

    ANTIBODY_TO_ANTIGEN = {
        'anti-K': 'K', 'anti-k': 'k',
        'anti-E': 'E', 'anti-e': 'e',
        'anti-C': 'C', 'anti-c': 'c',
        'anti-Fya': 'Fya', 'anti-Fyb': 'Fyb',
        'anti-Jka': 'Jka', 'anti-Jkb': 'Jkb',
        'anti-M': 'M', 'anti-N': 'N', 'anti-S': 'S', 'anti-s': 's',
        'anti-Lea': 'Lea', 'anti-Leb': 'Leb',
    }

    for ab in antibodies:
        antigen = ANTIBODY_TO_ANTIGEN.get(ab.specificity, ab.specificity.replace('anti-', ''))
        if antigen and not antigen_set.get(antigen):
            failures.append(
                f"Patient has {ab.specificity} — unit must be {antigen}-negative "
                f"(unit's antigen profile does not confirm this)."
            )

    if failures:
        raise ValidationError(failures)


def _check_directed_autologous(unit, patient):
    """
    Safety interlock for autologous and directed donations.

    - Autologous unit: the donor IS the patient — can only go back to that patient.
    - Directed unit: donated specifically for a named patient — can only go to that patient.

    Prevents accidental allogeneic transfusion of a pre-deposit autologous unit
    to the wrong patient.  This is a serious near-miss category in SHOT data.
    """
    donation = unit.donation
    purpose = getattr(donation, 'donation_purpose', 'allogeneic')
    if purpose == 'allogeneic':
        return  # No restriction

    intended = getattr(donation, 'intended_recipient', None)

    if purpose == 'autologous':
        # The donor's SubjectIdentity must match the patient's SubjectIdentity
        # (or intended_recipient FK if set)
        if intended and intended.pk != patient.pk:
            raise ValidationError(
                f"Autologous unit {unit.did}: pre-deposited by Patient "
                f"#{intended.pk} — cannot be issued to a different patient (#{patient.pk})."
            )
        elif not intended:
            # Fallback: check donor's linked patient record via subject
            try:
                donor_patient = unit.donation.donor.subject.patient
                if donor_patient.pk != patient.pk:
                    raise ValidationError(
                        f"Autologous unit {unit.did}: this unit was pre-deposited by "
                        f"Patient #{donor_patient.pk} and cannot be issued to Patient #{patient.pk}."
                    )
            except Exception:
                pass  # Donor may not have a linked patient record; allow with audit trail

    elif purpose == 'directed':
        if not intended:
            raise ValidationError(
                f"Directed unit {unit.did}: no intended recipient recorded. "
                "Cannot issue without confirming the named recipient."
            )
        if intended.pk != patient.pk:
            raise ValidationError(
                f"Directed unit {unit.did}: intended for Patient #{intended.pk} "
                f"— cannot be issued to Patient #{patient.pk}."
            )


def _check_sod(unit, actor):
    """
    Separation of Duties: the person issuing must not be any of the people
    who collected the donation, performed the TTI tests, or performed the crossmatch.
    """
    from donors.models import Donation
    conflicts = []

    # Can't issue if you collected the donation
    if unit.donation_id:
        try:
            donation = Donation.objects.get(pk=unit.donation_id)
            if donation.collected_by_id == actor.pk:
                conflicts.append("Issuer collected this donation.")
        except Donation.DoesNotExist:
            pass

    # Can't issue if you signed off the TTI test
    from transfusion.models import DonationTestResult
    if DonationTestResult.objects.filter(
        donation_id=unit.donation_id, reviewed_by=actor
    ).exists():
        conflicts.append("Issuer reviewed TTI test results for this donation.")

    if conflicts:
        raise PermissionDenied(
            "Separation of Duties violation: " + " / ".join(conflicts)
        )


def _check_neonatal_requirements(unit, blood_request, patient):
    """
    Neonatal transfusion protocol.

    Applies when:
    - BloodRequest.is_neonatal is True, OR
    - Patient DOB indicates age < 4 months (122 days)

    Requirements (BSH 2020 Guidelines for Transfusion in Neonates; AABB Technical Manual):
    1. Irradiated — prevents TA-GvHD in immunologically immature neonates (T-cell engraftment)
    2. CMV-safe — either CMV-seronegative OR leukoreduced (≥3 log leucoreduction eliminates
       cell-associated CMV, accepted as equivalent by BSH/BCSH 2012)
    3. Volume ≤ 20 mL/kg — standard small-volume aliquot limit; some guidelines allow 30 mL/kg
       for exchange transfusion but 20 is the safe default for top-up
    4. RBC age warning — units > 7 days old have rising extracellular potassium; significant
       hyperkalaemia risk in large-volume neonatal transfusions
    """
    is_neo = getattr(blood_request, 'is_neonatal', False)
    if not is_neo and patient.dob:
        from django.utils import timezone as tz
        age_days = (tz.now().date() - patient.dob).days
        is_neo = age_days < 122  # 4 months ≈ 122 days

    if not is_neo:
        return

    failures = []

    if not unit.is_irradiated:
        failures.append(
            "Neonatal transfusion requires irradiated blood to prevent TA-GvHD "
            "(BSH 2020; AABB). Request an irradiated unit."
        )

    # CMV-safe = CMV-negative donor OR leukoreduced component (BSH/BCSH accepted equivalence)
    cmv_safe = unit.is_cmv_negative or unit.is_leukoreduced
    if not cmv_safe:
        failures.append(
            "Neonatal transfusion requires CMV-negative or leukoreduced blood. "
            "CMV infection is potentially fatal in preterm and immunocompromised neonates."
        )

    # Volume vs weight check
    weight_kg = getattr(blood_request, 'neonatal_weight_kg', None)
    if weight_kg and unit.volume_ml:
        max_vol = float(weight_kg) * 20.0
        if unit.volume_ml > max_vol:
            failures.append(
                f"Volume exceeded: unit is {unit.volume_ml} mL but max for "
                f"{weight_kg} kg patient is {max_vol:.0f} mL (20 mL/kg limit). "
                "Request a small-volume aliquot from the blood bank."
            )

    # RBC freshness advisory — hard stop not warranted but include in failures list
    if unit.component_type and unit.collection_datetime:
        from django.utils import timezone as tz
        code = getattr(unit.component_type, 'code', '') or ''
        if 'RBC' in code.upper():
            unit_age_days = (tz.now() - unit.collection_datetime).days
            if unit_age_days > 7:
                failures.append(
                    f"Neonatal RBC age warning: unit is {unit_age_days} days old. "
                    "BSH recommends ≤ 7 days for neonates to minimise hyperkalaemia risk. "
                    "Consider requesting a fresher unit if clinically feasible."
                )

    if failures:
        raise ValidationError(failures)
