# Blood Bank LIS — Comprehensive A-Z Test Plan
> Django 5.x + PostgreSQL | Project: bloodbank-app
> Generated 2026-06-29 | Covers: unit → integration → safety → security → performance → IQ/OQ/PQ

---

## SECTION 0 — TEST INFRASTRUCTURE SETUP

### 0.1 Install Test Dependencies

Add to `requirements-test.txt`:
```
pytest==8.3.*
pytest-django==4.9.*
pytest-xdist==3.6.*          # parallel workers
pytest-cov==5.0.*            # coverage
factory_boy==3.3.*           # model factories
Faker==25.*
hypothesis==6.100.*          # property-based testing
locust==2.28.*               # load testing
bandit==1.8.*                # security static analysis
safety==3.*                  # dependency CVE check
```

### 0.2 pytest.ini / pyproject.toml
```ini
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "bloodbank.settings_test"
addopts = "--reuse-db -x --tb=short"
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"
```

### 0.3 settings_test.py
```python
from bloodbank.settings import *
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'bloodbank_test',
        'USER': 'postgres',
        'PASSWORD': 'postgres',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']  # fast
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
CELERY_TASK_ALWAYS_EAGER = True  # if Celery added later
```

### 0.4 Factory Definitions
```python
# tests/factories.py
import factory
from factory.django import DjangoModelFactory
from django.utils import timezone
from datetime import timedelta

class BranchFactory(DjangoModelFactory):
    class Meta:
        model = 'core.Branch'
    name = factory.Sequence(lambda n: f'Branch {n}')
    code = factory.Sequence(lambda n: f'BR{n:03d}')

class UserFactory(DjangoModelFactory):
    class Meta:
        model = 'accounts.User'
    username = factory.Sequence(lambda n: f'user{n}')
    email = factory.LazyAttribute(lambda o: f'{o.username}@test.local')
    password = factory.PostGenerationMethodCall('set_password', 'testpass123')

class SubjectIdentityFactory(DjangoModelFactory):
    class Meta:
        model = 'privacy.SubjectIdentity'
    subject_type = 'donor'

class DonorFactory(DjangoModelFactory):
    class Meta:
        model = 'donors.Donor'
    subject = factory.SubFactory(SubjectIdentityFactory, subject_type='donor')
    sex = 'M'
    dob = factory.LazyFunction(lambda: timezone.now().date().replace(year=1990))
    blood_group_abo = 'O'
    blood_group_rh = 'pos'
    deferral_status = 'active'
    registration_branch = factory.SubFactory(BranchFactory)
    created_by = factory.SubFactory(UserFactory)

class DonationFactory(DjangoModelFactory):
    class Meta:
        model = 'donors.Donation'
    donor = factory.SubFactory(DonorFactory)
    branch = factory.LazyAttribute(lambda o: o.donor.registration_branch)
    donated_at = factory.LazyFunction(timezone.now)
    donation_type = 'whole_blood'
    collected_by = factory.SubFactory(UserFactory)
    consent = factory.SubFactory('tests.factories.ConsentRecordFactory')

class BloodUnitFactory(DjangoModelFactory):
    class Meta:
        model = 'inventory.BloodUnit'
    donation = factory.SubFactory(DonationFactory)
    did = factory.Sequence(lambda n: f'DID{n:012d}')
    component_class = 'RBC'
    abo_type = 'O'
    rh_d_type = 'neg'
    status = 'available'
    branch = factory.SubFactory(BranchFactory)
    expiry_date = factory.LazyFunction(
        lambda: (timezone.now() + timedelta(days=42)).date()
    )

class PatientFactory(DjangoModelFactory):
    class Meta:
        model = 'patients.Patient'
    subject = factory.SubFactory(SubjectIdentityFactory, subject_type='patient')
    sex = 'M'
    registration_branch = factory.SubFactory(BranchFactory)
    created_by = factory.SubFactory(UserFactory)
```

### 0.5 Run Commands
```bash
# Full suite
pytest --cov=. --cov-report=html -n auto

# Safety critical only
pytest tests/ -m safety_critical -v

# Single app
pytest tests/test_issue_logic.py -v

# Load test
locust -f tests/locustfile.py --host=http://localhost:8000 --users=50 --spawn-rate=5 -t 60s

# Security scan
bandit -r . -x .venv,tests/ -ll
safety check -r requirements.txt
```

---

## SECTION A — PURE UNIT TESTS (No Database)

### A.1 ABO Compatibility Matrix
**File**: `tests/unit/test_abo_compatibility.py`
**Coverage target**: 100% branch coverage of `transfusion/issue.py::_check_abo_compatibility`

| Test | Input | Expected |
|------|-------|----------|
| A-01 | O- unit → any patient | Compatible (universal donor) |
| A-02 | AB+ unit → AB+ patient | Compatible |
| A-03 | AB+ unit → O- patient | Incompatible (ABO mismatch) |
| A-04 | A+ unit → B+ patient | Incompatible |
| A-05 | A+ unit → A- patient | Incompatible (Rh mismatch) |
| A-06 | A- unit → A+ patient | Compatible (Rh neg into pos OK) |
| A-07 | O+ unit → O- patient | Incompatible (Rh+) |
| A-08 | No blood group on patient | Only O- compatible |
| A-09 | All 4 ABO × 2 Rh = 8 donor types × 8 recipient types | Full 64-cell matrix |

### A.2 Compatible Label List
**File**: `tests/unit/test_compatible_labels.py`
**Coverage**: `transfusion/views.py::_compatible_label_list`

| Test | Input | Expected |
|------|-------|----------|
| B-01 | O- patient | ['O−'] only |
| B-02 | AB+ patient | All 8 types |
| B-03 | A+ patient | A+, A−, O+, O− |
| B-04 | B- patient | B−, O− |

### A.3 Holt-Winters Forecasting
**File**: `tests/unit/test_forecasting.py` (expand existing)
**Coverage**: `analytics/forecasting.py`

| Test | Scenario | Expected |
|------|----------|----------|
| C-01 | <14 data points (2 seasons) | Falls back to mean forecast |
| C-02 | 56-point series, n_ahead=14 | Returns exactly 14 values |
| C-03 | No negative forecasts | min(forecast) >= 0.0 |
| C-04 | Constant input series | Constant output |
| C-05 | Trending up series | Forecast > mean of series |
| C-06 | MASE auto-select | Selects best model |
| C-07 | Zero-demand week | Handles zeros without division error |

### A.4 Luhn / DID Checksum
**File**: `tests/unit/test_did.py`

| Test | Scenario | Expected |
|------|----------|----------|
| D-01 | Valid 12-char DID | is_valid_did() → True |
| D-02 | Corrupted last digit | is_valid_did() → False |
| D-03 | Wrong length | is_valid_did() → False |
| D-04 | generate_did() uniqueness (1000 iterations) | All unique |

### A.5 Compliance Rules Engine
**File**: `tests/unit/test_compliance.py`

| Test | Rule | Expected |
|------|------|----------|
| E-01 | Age < 17 | FAIL — too young |
| E-02 | Age = 17 | PASS |
| E-03 | Weight < 50 kg | FAIL |
| E-04 | Weight = 50 kg | PASS |
| E-05 | Hb < 12.5 g/dL (female) | FAIL |
| E-06 | Hb < 13.0 g/dL (male) | FAIL |
| E-07 | Last donation < 56 days ago (whole blood) | FAIL |
| E-08 | Last donation = 56 days ago | PASS |
| E-09 | Permanently deferred | FAIL (no override) |
| E-10 | Temporarily deferred (future date) | FAIL |
| E-11 | Temporary deferral expired | PASS |
| E-12 | On antibiotics | FAIL |
| E-13 | Pregnancy in past 6 months | FAIL |
| E-14 | IV drug use ever | FAIL (permanent) |
| E-15 | CJD risk factor | FAIL (permanent) |
| E-16 | Prior transfusion < 4 months | FAIL |
| E-17 | All clear | PASS |

---

## SECTION B — MODEL UNIT TESTS (Database Required)

### B.1 Patient Models
**File**: `tests/models/test_patient_models.py`

| Test | Model/Method | Scenario | Expected |
|------|-------------|----------|----------|
| M-P-01 | Patient.effective_blood_group() | Lab confirmed exists | Returns lab result |
| M-P-02 | Patient.effective_blood_group() | No lab, declared ABO | Returns declared (source='declared') |
| M-P-03 | Patient.effective_blood_group() | No lab, no declared | Returns None |
| M-P-04 | Patient.current_blood_group() | Two results, one discrepant | Returns latest non-discrepant |
| M-P-05 | Patient.current_blood_group() | Only discrepant result | Returns None (cannot use) |
| M-P-06 | PatientBloodGroup append-only | Cannot delete or update status field | IntegrityError / custom check |
| M-P-07 | PatientAntibody.clinical_significance | Anti-K = significant | Returns True |
| M-P-08 | PatientPhenotype.required_negative_antigens() | Patient has anti-K, anti-E | Returns {'K', 'E'} set |
| M-P-09 | PatientPhenotype.antigen_absent_set() | Rh C absent, K present | Returns {'C': True} |
| M-P-10 | HaemolyticDiseaseCase.is_severe() | Severity=severe | Returns True |
| M-P-11 | HaemolyticDiseaseCase.is_severe() | Severity=mild | Returns False |
| M-P-12 | AntenatalRecord | EDD in past | RAADP overdue check |

### B.2 Donor Models
**File**: `tests/models/test_donor_models.py`

| Test | Model/Method | Scenario | Expected |
|------|-------------|----------|----------|
| M-D-01 | Donor.category | 0 donations | 'new' |
| M-D-02 | Donor.category | 10 donations | 'committed' |
| M-D-03 | Donor.category | 25 donations | 'veteran' |
| M-D-04 | Donor.next_milestone | 4 donations | ('fifth', 1) |
| M-D-05 | Donor.is_eligible_to_donate | permanent defer | False |
| M-D-06 | Donor.is_eligible_to_donate | temp defer, future date | False |
| M-D-07 | Donor.is_eligible_to_donate | temp defer, past date | True |
| M-D-08 | Donor.check_and_create_milestones | 10 donations | DonorMilestone(tenth) created |
| M-D-09 | Donor.check_and_create_milestones | called twice | No duplicate milestone |
| M-D-10 | DonorPhenotype.antigen_negative_set | K=False, E=True | {'K': True} (only explicitly neg) |
| M-D-11 | DonorPhenotype._propagate_to_units | save phenotype | BloodUnit.antigen_negative_set updated |
| M-D-12 | DonorAdverseEvent | FK to Donation | OneToOne enforced |
| M-D-13 | Donation.has_deferral_triggers | IV drug use | Returns reason string |
| M-D-14 | RetentionCampaign.response_rate() | 3 responded of 10 | 30.0 |
| M-D-15 | RetentionCampaign.conversion_rate() | 1 donated of 10 | 10.0 |
| M-D-16 | CampaignEnrollment unique_together | Same donor + campaign twice | IntegrityError |

### B.3 Inventory Models
**File**: `tests/models/test_inventory_models.py`

| Test | Model/Method | Scenario | Expected |
|------|-------------|----------|----------|
| M-I-01 | BloodUnit.is_expired() | expiry = today | Not expired (expires at end of day) |
| M-I-02 | BloodUnit.is_expired() | expiry = yesterday | Expired |
| M-I-03 | BloodUnit.is_expired() | expiry = tomorrow | Not expired |
| M-I-04 | State machine: valid transition | available → reserved | Success |
| M-I-05 | State machine: invalid transition | issued → available | StateTransitionError |
| M-I-06 | State machine: transfused → any | All forbidden | StateTransitionError |
| M-I-07 | State machine: destroyed → any | All forbidden | StateTransitionError |
| M-I-08 | ComponentType | Missing required fields | IntegrityError |
| M-I-09 | ProcessingEvent | Links to BloodUnit correctly | FK enforced |

### B.4 Transfusion Models
**File**: `tests/models/test_transfusion_models.py`

| Test | Model/Method | Scenario | Expected |
|------|-------------|----------|----------|
| M-T-01 | Sample.is_valid() | Sample drawn today | True |
| M-T-02 | Sample.is_valid() | Sample drawn 3 days ago | False (>72h) |
| M-T-03 | Sample.is_valid() | Sample drawn exactly 72h ago | False (expired) |
| M-T-04 | Crossmatch | method='electronic' with AHG result | Validation error |
| M-T-05 | BloodRequest | urgency choices enforced | |
| M-T-06 | PostTransfusionOutcome.hb_increment() | pre=8.5, post=10.5 | 2.0 |
| M-T-07 | PostTransfusionOutcome.hb_increment() | No pre-Hb on file | None |

### B.5 Privacy & Encryption
**File**: `tests/models/test_privacy.py`

| Test | Scenario | Expected |
|------|----------|----------|
| M-Pr-01 | Encrypt "John Smith" → decrypt | Returns "John Smith" |
| M-Pr-02 | Encrypt None → decrypt | Returns '' (no crash) |
| M-Pr-03 | Blind index deterministic | blind_index("test") called twice | Same hash both times |
| M-Pr-04 | Blind index distinct | blind_index("A") ≠ blind_index("B") | True |
| M-Pr-05 | SubjectIdentity.display_name | No name_enc | Returns "Subject #N" |
| M-Pr-06 | SubjectIdentity.display_name | Encrypted name | Returns decrypted name |
| M-Pr-07 | ConsentRecord append-only | Withdraw = new row, not update | withdrawn_at set, not deleted |
| M-Pr-08 | DSRRequest status transitions | Workflow completeness | All states reachable |

### B.6 Audit & Electronic Signature
**File**: `tests/models/test_audit.py`

| Test | Scenario | Expected |
|------|----------|----------|
| M-A-01 | write_audit() basic | AuditLog row created with correct fields | |
| M-A-02 | write_audit() hash chain | log[n].prev_hash == SHA256(log[n-1].to_bytes()) | |
| M-A-03 | Chain tamper detection | Modify a row → verify_chain() fails at that row | |
| M-A-04 | verify_chain() on clean log | Returns True, reports no errors | |
| M-A-05 | ElectronicSignature.verify() | Correct content → True | |
| M-A-06 | ElectronicSignature.verify() | Modified content → False | |
| M-A-07 | ElectronicSignature fields | user, action, content_hash, signed_at all required | |
| M-A-08 | Audit log no-delete | ORM delete() raises PermissionError or DB trigger | |

---

## SECTION C — SAFETY-CRITICAL TESTS (Mandatory — All Must Pass)

### C.1 Issue Safety Chain
**File**: `tests/safety/test_issue_safety.py`
**Marker**: `@pytest.mark.safety_critical`

| ID | Test Name | Description |
|----|-----------|-------------|
| S-01 | test_abo_incompatible_issue_blocked | B+ unit → A+ patient → IssueError |
| S-02 | test_rh_positive_unit_blocked_for_rh_neg_patient | O+ → O- → IssueError |
| S-03 | test_expired_unit_blocked | Unit with expiry=yesterday → IssueError |
| S-04 | test_quarantined_unit_blocked | Unit status=quarantined → IssueError |
| S-05 | test_recalled_unit_blocked | Unit status=recalled → IssueError |
| S-06 | test_failed_qc_unit_blocked | Unit status=failed_qc → IssueError |
| S-07 | test_in_testing_unit_blocked | Unit status=in_testing → IssueError |
| S-08 | test_destroyed_unit_blocked | Unit status=destroyed → IssueError |
| S-09 | test_irradiation_requirement_enforced | Patient requires irradiated; non-irradiated unit → IssueError |
| S-10 | test_cmv_requirement_enforced | Patient requires CMV-neg; CMV+ unit → IssueError |
| S-11 | test_leukoreduced_requirement_enforced | Patient requires leukoreduced; non-LR unit → IssueError |
| S-12 | test_antigen_negative_requirement_enforced | Anti-K patient; K+ unit → IssueError |
| S-13 | test_antibody_block_historical | Anti-K in history, not on current screen; K+ unit → IssueError |
| S-14 | test_two_abo_rule | Patient with 1 ABO determination; group-specific unit → IssueError |
| S-15 | test_two_abo_rule_passes_with_two | Patient with 2 concordant ABO; group-specific → succeeds |
| S-16 | test_sod_collector_cannot_issue | Collector attempts to issue own donation → SoDError |
| S-17 | test_sod_tester_cannot_issue | TTI tester attempts to issue → SoDError |
| S-18 | test_directed_donation_wrong_patient | Directed unit; attempted for different patient → IssueError |
| S-19 | test_autologous_cannot_go_allogeneic | Autologous pre-deposit; attempted for any other patient → IssueError |
| S-20 | test_neonatal_non_irradiated_blocked | Neonatal order; non-irradiated unit → IssueError |
| S-21 | test_emergency_release_only_o_neg | Emergency release requested for A+ unit → IssueError (must use O-) |

### C.2 Double-Issue Prevention (Concurrency)
**File**: `tests/safety/test_concurrency.py`

| ID | Test | Expected |
|----|------|----------|
| C-01 | Two threads, same unit, simultaneous | Exactly 1 IssueTransaction, 1 raises IssueError |
| C-02 | Two processes (using subprocess), same unit | Same as above |
| C-03 | Unit reserved for XM; second reservation attempt | Error — unit already reserved |
| C-04 | Crossmatch result recorded; unit still in reserved | Correct; double-record attempt fails |

### C.3 Crossmatch Safety
**File**: `tests/safety/test_crossmatch_safety.py`

| ID | Test | Expected |
|----|------|----------|
| XM-01 | Expired sample in crossmatch POST | ValidationError — sample expired |
| XM-02 | Electronic XM: 1 ABO determination | Gate fails — insufficient ABO history |
| XM-03 | Electronic XM: positive antibody screen | Gate fails — screen positive |
| XM-04 | Electronic XM: historical antibody | Gate fails — clinical antibody on record |
| XM-05 | Electronic XM: unit ABO unconfirmed | Gate fails — unit not typed |
| XM-06 | Electronic XM: all gates pass | Crossmatch records method='electronic' |
| XM-07 | ABO discrepancy present | Block electronic XM, block issue |

### C.4 State Machine Safety
**File**: `tests/safety/test_state_machine.py`

Every invalid transition must raise `StateTransitionError` or equivalent:

| From | To | Expected |
|------|----|----------|
| issued | available | BLOCKED |
| issued | reserved | BLOCKED |
| transfused | available | BLOCKED |
| transfused | issued | BLOCKED |
| destroyed | any | BLOCKED (all) |
| quarantined | available | BLOCKED (if TTI reactive) |
| discarded | any | BLOCKED (all) |

Every valid transition succeeds and creates a UnitStateTransition record.

### C.5 TTI Lockout
**File**: `tests/safety/test_tti_lockout.py`

| ID | Test | Expected |
|----|------|----------|
| TTI-01 | Reactive HIV result → unit auto-quarantined | Status = 'quarantined', Alert created |
| TTI-02 | Reactive HBsAg result → unit auto-quarantined | Same |
| TTI-03 | Reactive HCV result → unit auto-quarantined | Same |
| TTI-04 | All TTI clear → unit can proceed to available | No block |
| TTI-05 | One reactive, others clear → still quarantined | Reactive = block |
| TTI-06 | Quarantined unit (TTI reactive) → cannot move to available | StateTransitionError |

---

## SECTION D — INTEGRATION TESTS (Full Request/Response)

### D.1 Donor Workflow
**File**: `tests/integration/test_donor_workflow.py`

| Test | Flow | Assertions |
|------|------|------------|
| INT-D-01 | Register donor → POST /donors/register/ | Donor + SubjectIdentity + ConsentRecord created |
| INT-D-02 | Register donor without consent | 400 error, no Donor created |
| INT-D-03 | Record donation → POST /donors/donation/record/ | Donation created, consent FK valid |
| INT-D-04 | Record adverse event → POST /donors/donation/N/adverse-event/ | DonorAdverseEvent created |
| INT-D-05 | Enroll in retention campaign | CampaignEnrollment created, status='enrolled' |
| INT-D-06 | Update enrollment status | Status updated, audit entry created |
| INT-D-07 | Donor deferral letter PDF | Returns 200, Content-Type: application/pdf |
| INT-D-08 | Donor BG card PDF | Returns 200 only if ABO confirmed |

### D.2 Blood Unit Workflow
**File**: `tests/integration/test_unit_workflow.py`

| Test | Flow | Assertions |
|------|------|------------|
| INT-U-01 | Create unit → POST | BloodUnit created, status='quarantined' |
| INT-U-02 | Record TTI → clear → available | Unit status='available' |
| INT-U-03 | Irradiate unit → POST | ProcessingEvent created, expiry recalculated |
| INT-U-04 | Irradiate: dose < 25 Gy | Validation error |
| INT-U-05 | Irradiate: dose > 50 Gy | Validation error |
| INT-U-06 | Near-expiry filter | /inventory/near-expiry/?hours=72 returns correct units |
| INT-U-07 | Antigen match search | /inventory/units/antigen-match/ returns only compatible units |
| INT-U-08 | Transfer unit between branches | BloodUnit.branch updated, UnitTransfer record created |

### D.3 Transfusion Workflow
**File**: `tests/integration/test_transfusion_workflow.py`

| Test | Flow | Assertions |
|------|------|------------|
| INT-T-01 | New blood request → POST | BloodRequest created, audit entry |
| INT-T-02 | New crossmatch → POST | Crossmatch created, unit reserved |
| INT-T-03 | Lock unit for XM → POST | Unit status='reserved' |
| INT-T-04 | Unlock unit → POST | Unit status='available' |
| INT-T-05 | Issue unit → POST | IssueTransaction created, unit='issued', e-signature |
| INT-T-06 | Record bedside administration | TransfusionAdministration created |
| INT-T-07 | Record transfusion reaction | TransfusionReaction created, SHOT flag if serious |
| INT-T-08 | Record post-transfusion outcome | PostTransfusionOutcome created, hb_increment calculated |
| INT-T-09 | Emergency release flow | EmergencyRelease created, O-neg only, retrospective alert |
| INT-T-10 | Lookback initiation | LookbackCampaign created, LookbackNotification per patient |
| INT-T-11 | Dose calculator | GET with weight=70, component=RBC → correct units estimate |

### D.4 Patient Workflow
**File**: `tests/integration/test_patient_workflow.py`

| Test | Flow | Assertions |
|------|------|------------|
| INT-P-01 | Register patient | Patient + SubjectIdentity created |
| INT-P-02 | Record blood group | PatientBloodGroup appended |
| INT-P-03 | Record discrepant blood group | is_discrepant=True, investigation alert |
| INT-P-04 | Record antibody | PatientAntibody created |
| INT-P-05 | Record phenotype | PatientPhenotype created with e-sign |
| INT-P-06 | Withdraw phenotype consent | Phenotype.consent_withdrawn=True |
| INT-P-07 | Patient BG card PDF | Returns valid PDF |
| INT-P-08 | MPI merge | Patient A merged into B, all references updated |
| INT-P-09 | Antenatal record create | AntenatalRecord + schedule created |
| INT-P-10 | Anti-D prophylaxis record | AntiDProphylaxis created, FMH calculated |
| INT-P-11 | HDFN case create | HaemolyticDiseaseCase created |
| INT-P-12 | Therapeutic phlebotomy | TherapeuticPhlebotomy created |

### D.5 Quality Workflow
**File**: `tests/integration/test_quality_workflow.py`

| Test | Flow | Assertions |
|------|------|------------|
| INT-Q-01 | Create NonConformance | NC-YYYY-NNNN auto-number assigned |
| INT-Q-02 | NC status progression | open → under_review → capa_open → capa_verify → closed |
| INT-Q-03 | NC cannot skip state | open → closed directly → ValidationError |
| INT-Q-04 | Create SOP | StandardOperatingProcedure + SOPVersion created |
| INT-Q-05 | Approve SOP version | E-signature required; sets active_version |
| INT-Q-06 | Internal audit with finding | AuditFinding created, NC raised from finding |
| INT-Q-07 | Staff competency record | StaffCompetency created; assessor ≠ assessee enforced |
| INT-Q-08 | Staff competency self-assess blocked | Error if assessor == assessee |
| INT-Q-09 | New lot validation: pass | NewLotValidation status=approved, lot released |
| INT-Q-10 | New lot validation: fail | Status=rejected, NC auto-created |
| INT-Q-11 | Transfusion committee | Committee created, e-signed minutes |
| INT-Q-12 | Quality indicators report | All 8 KPIs calculated, no division errors |

### D.6 Cold Chain Workflow
**File**: `tests/integration/test_coldchain_workflow.py`

| Test | Flow | Assertions |
|------|------|------------|
| INT-CC-01 | Temperature POST in range | TemperatureLog created, no excursion |
| INT-CC-02 | Temperature POST out of range | TemperatureExcursion created, affected units quarantined |
| INT-CC-03 | Temperature POST duplicate UUID | Idempotent — no second log row |
| INT-CC-04 | Sensor offline >15 min | sensor_offline Alert created by run_alerts |
| INT-CC-05 | Calibration overdue | calibration_overdue Alert created |
| INT-CC-06 | Equipment excursion ongoing | ongoing_excursion Alert persists |
| INT-CC-07 | Unit return check — temp ok | UnitReturnCheck.decision='accepted' |
| INT-CC-08 | Unit return check — temp high | UnitReturnCheck.decision='quarantine' |

---

## SECTION E — API TESTS (DRF Endpoints)

### E.1 REST API
**File**: `tests/api/test_api.py`

| Test | Endpoint | Assertions |
|------|----------|------------|
| API-01 | GET /api/v1/units/ (no auth) | 401 Unauthorized |
| API-02 | GET /api/v1/units/ (with token) | 200, paginated list |
| API-03 | GET /api/v1/units/?status=available | Filtered correctly |
| API-04 | POST /api/v1/temperature/ (valid) | 201 Created, TemperatureLog created |
| API-05 | POST /api/v1/temperature/ (duplicate UUID) | 200 or 201, no duplicate |
| API-06 | POST /api/v1/temperature/ (missing field) | 400 with field error |
| API-07 | POST /api/v1/bedside/verify/ (match) | {"result": "PASS"} |
| API-08 | POST /api/v1/bedside/verify/ (ABO mismatch) | {"result": "STOP", "reason": "ABO..."} |
| API-09 | POST /api/v1/bedside/verify/ (unknown patient) | 404 |
| API-10 | POST /api/v1/bedside/verify/ (unknown unit) | 404 |

### E.2 FHIR Facade
**File**: `tests/api/test_fhir.py`

| Test | Endpoint | Assertions |
|------|----------|------------|
| FHIR-01 | GET /fhir/metadata | Valid FHIR CapabilityStatement JSON |
| FHIR-02 | GET /fhir/Patient/{id} | Valid FHIR R4 Patient resource |
| FHIR-03 | GET /fhir/Patient/99999 | 404 FHIR OperationOutcome |
| FHIR-04 | GET /fhir/BiologicallyDerivedProduct/{did} | Valid FHIR R4 BDP resource |
| FHIR-05 | GET /fhir/AuditEvent | Returns array of AuditEvent resources |

---

## SECTION F — PERMISSION & AUTHENTICATION TESTS

**File**: `tests/security/test_permissions.py`

### F.1 Authentication Enforcement
Every protected view returns 302 (redirect to login) when not authenticated:
- Test against list of all URL patterns (auto-generated from urls.py)
- Exception: /login/, /api/v1/ (token auth), /fhir/ (token auth), /bedside/ (session)

### F.2 Role-Based Access Control
| View | Required Permission | Test: wrong role → 403 |
|------|--------------------|-----------------------|
| issue_unit | blood.issue | Tech without permission |
| manage_users | accounts.manage | Regular technician |
| approve_nc | quality.approve_nc | Collector role |
| irradiate_unit | inventory.irradiate | Read-only role |
| donor_detail | donors.view_donor | Unauthenticated |
| transfusion_committee | quality.committee | Donor technician |

### F.3 Branch Isolation
| Test | Scenario | Expected |
|------|----------|----------|
| BRANCH-01 | User from Branch A views Branch A unit | 200 |
| BRANCH-02 | User from Branch A views Branch B unit | 403 or 404 |
| BRANCH-03 | User from Branch A views Branch B patient | 403 or 404 |
| BRANCH-04 | Admin (all-branch) views any branch | 200 |

---

## SECTION G — SECURITY TESTS

**File**: `tests/security/test_security.py`

| ID | Test | Method | Expected |
|----|------|--------|----------|
| SEC-01 | XSS in donor name | POST name="<script>alert(1)</script>" | Stored encrypted, rendered HTML-escaped |
| SEC-02 | XSS in unit DID | GET /inventory/units/<script>/ | 404, no script reflected |
| SEC-03 | SQL injection in search | GET ?q=' OR '1'='1 | Parameterized query, no injection |
| SEC-04 | CSRF on POST views | POST without CSRF token | 403 Forbidden |
| SEC-05 | Session fixation | GET session before login, POST login | Session key rotates on login |
| SEC-06 | Password common list | POST password="password123" | Rejected by Django password validator |
| SEC-07 | Concurrent login | Same user, two sessions | Both valid (or session limit enforced) |
| SEC-08 | Audit log DELETE | ORM delete() or raw SQL DELETE | Exception raised |
| SEC-09 | Audit log UPDATE | Raw SQL UPDATE | Exception raised or DB trigger blocks |
| SEC-10 | PII not in URL | GET any URL | No name/NID in query string |
| SEC-11 | PII not in HTTP logs | Django request logging | name_enc/contact_enc not plaintext |
| SEC-12 | API token not in URL | GET endpoints | Token via header only, not ?token= |
| SEC-13 | Bandit scan | bandit -r . -ll | No HIGH severity findings |
| SEC-14 | safety check | safety check -r requirements.txt | No known CVEs in dependencies |

---

## SECTION H — ALERT SYSTEM TESTS

**File**: `tests/test_alerts.py`

| Alert Type | Trigger Condition | Test |
|------------|------------------|------|
| near_expiry | RBC expiring in <72h | Unit created with expiry=now+48h → alert |
| reagent_low_stock | lots < minimum_lots | Lots below threshold → alert on dashboard |
| open_crossmatch | Crossmatch >4h unresolved | Alert created after 4h |
| sample_expired | Sample >72h old | Alert when active requests have expired samples |
| ungrouped_units | Quarantined unit >24h without ABO | Alert created |
| sensor_offline | No reading for >15 min | Alert from run_alerts |
| calibration_overdue | Calibration date past | Alert from run_alerts |
| pbm_post_hb_gap | >50% RBC requests without post-Hb in 14d | Alert on PBM dashboard |
| raadp_overdue | RAADP schedule passed | Alert from run_alerts |
| lookback_pending | LookbackNotification not actioned | Alert |
| nc_backlog | NC open >30 days | Alert from run_alerts |
| sop_review_overdue | SOP review date passed | Alert |
| competency_overdue | Staff competency expired | Alert |
| hdfn_unreported | ET case not SHOT-reported | Alert |
| committee_action_overdue | Committee action past due date | Alert |

---

## SECTION I — MANAGEMENT COMMAND TESTS

**File**: `tests/test_management_commands.py`

| Command | Test Scenario | Expected |
|---------|--------------|----------|
| run_alerts | Fresh DB with no alerts | Completes without error |
| run_alerts | Near-expiry unit exists | Alert.objects.filter(type='near_expiry').exists() |
| run_alerts | Sensor offline | sensor_offline Alert created |
| run_alerts | RAADP overdue | raadp_overdue Alert created |
| build_daily_facts | 30 days of donation data | DemandFactDaily rows created |
| build_daily_facts --all-history | Empty DB | Completes without error |
| check_shortages | Stock below threshold | forecast_shortage Alert created |
| donor_engagement | Lapsed donors exist | Lapsed count reported |
| seed_data | Run twice | Idempotent (no duplicates) |
| seed_data | Creates default branches | Branch.objects.count() >= 1 |

---

## SECTION J — REPORT & PDF TESTS

**File**: `tests/test_reports.py`

| Report | Test | Expected |
|--------|------|----------|
| TAT Report | GET /core/reports/tat/ | 200, avg/median/P90 per urgency shown |
| TAT Report | No data | 200, graceful "no data" display |
| Haemovigilance | GET /transfusion/haemovigilance/ | 200, reaction rate calculated |
| Quality Indicators | GET /core/reports/quality-indicators/ | 200, all 8 KPIs present |
| PBM Dashboard | GET /transfusion/reports/pbm/ | 200, coverage% calculated |
| Analytics Dashboard | GET /analytics/ | 200, KPI cards rendered |
| Donor BG Card PDF | GET /donors/N/bg-card.pdf | 200, application/pdf |
| Patient BG Card PDF | GET /patients/N/bg-card.pdf | 200, application/pdf |
| Deferral Letter PDF | GET /donors/N/deferral-letter.pdf | 200, application/pdf |
| Patient Traceability PDF | GET /patients/N/traceability.pdf | 200, application/pdf |

---

## SECTION K — PROPERTY-BASED TESTS (Hypothesis)

**File**: `tests/property/test_properties.py`

```python
from hypothesis import given, settings
from hypothesis import strategies as st

@given(abo=st.sampled_from(['A','B','AB','O']), rh=st.sampled_from(['pos','neg']))
def test_effective_blood_group_never_crashes(abo, rh):
    """effective_blood_group() never raises for any valid ABO/Rh."""
    from patients.models import Patient
    p = MagicMock()
    p.abo = abo
    p.rh_d = rh
    p.current_blood_group.return_value = None
    p.effective_blood_group = Patient.effective_blood_group.__get__(p)
    result = p.effective_blood_group()  # must not raise
    assert result is not None or (abo == '' and rh == '')

@given(series=st.lists(st.floats(min_value=0, max_value=100), min_size=20, max_size=200))
def test_holt_winters_never_produces_negative(series):
    from analytics.forecasting import _holt_winters_additive
    _, forecast, _ = _holt_winters_additive(series, season_length=7, n_ahead=14)
    assert all(v >= 0.0 for v in forecast)

@given(weight=st.floats(min_value=1, max_value=200))
def test_dose_calculator_never_crashes(weight):
    """Dose calculator handles any weight without crashing."""
    # call the dose calc logic with any float weight
    ...
```

---

## SECTION L — IQ/OQ/PQ VALIDATION DOCUMENTATION

### L.1 Installation Qualification (IQ) Checklist

```
IQ-001  Python version ≥ 3.12.0                    □
IQ-002  Django version ≥ 5.0.0                     □
IQ-003  PostgreSQL version ≥ 16.0                  □
IQ-004  All packages in requirements.txt installed  □
IQ-005  All migrations applied: showmigrations ✓   □
IQ-006  Static files collected without error        □
IQ-007  .env file present with all required keys   □
IQ-008  SECRET_KEY ≥ 50 chars, not default        □
IQ-009  DEBUG = False in production                □
IQ-010  ALLOWED_HOSTS configured correctly         □
IQ-011  Database connection reachable              □
IQ-012  Media root writable by application user    □
IQ-013  Log directory writable                     □
IQ-014  Backup cron configured                     □
IQ-015  run_alerts cron configured                 □
IQ-016  build_daily_facts cron configured          □
IQ-017  HTTPS certificate valid                    □
IQ-018  HSTS header present in response            □
IQ-019  CSP header configured                      □
IQ-020  seed_data run and confirmed                □
```

### L.2 Operational Qualification (OQ) — Test Protocol

For each test case in Sections A–K:
- Execute test case with documented input
- Record actual result
- Compare to expected result  
- Sign off: Tester name, date, result (PASS/FAIL)

OQ sign-off page template:
```
OQ Protocol: Blood Bank LIS v___.___
System: [hostname/IP]
Test Environment: [development/staging/production]
Tester: _____________________ Date: __________
Witness: ___________________ Date: __________

Safety-critical tests (Sections C.1–C.5): ALL must PASS
[ ] S-01 through S-21: ___ of 21 passed
[ ] C-01 through C-04: ___ of 4 passed
[ ] XM-01 through XM-07: ___ of 7 passed
[ ] TTI-01 through TTI-06: ___ of 6 passed

Functional tests (Sections D–J): ___ of ___ passed
Security tests (Section G): ___ of ___ passed

OVERALL: [ ] PASS  [ ] FAIL
If FAIL: deviation report number: ___________
```

### L.3 Performance Qualification (PQ) — Production Environment Tests

```
PQ-001  20 concurrent users: avg response <500ms   □
PQ-002  issue_unit() under load: <1000ms P99        □
PQ-003  Temperature ingest 10/min: no dropped events □
PQ-004  Audit log 10,000 entries: chain valid       □
PQ-005  PDF generation under load: <5000ms P99     □
PQ-006  DB failover: reconnects within 30s          □
PQ-007  Session after restart: users remain logged in □
PQ-008  Backup restore test: data intact            □
```

### L.4 Traceability Matrix (Template)

| Requirement ID | Description | Code Location | Test Case IDs | IQ/OQ/PQ |
|---------------|-------------|--------------|--------------|----------|
| REQ-X01 | Two-ABO rule | transfusion/issue.py:_check_two_abo | S-08, S-15 | OQ |
| REQ-X02 | Sample validity | transfusion/views.py:new_crossmatch | XM-01 | OQ |
| REQ-X03 | ABO compatible issue | transfusion/issue.py:_check_abo | S-01, S-02 | OQ |
| REQ-X04 | Special requirements | transfusion/issue.py:_check_special | S-09–S-12 | OQ |
| REQ-X05 | Electronic XM gates | transfusion/views.py:_check_electronic | XM-02–06 | OQ |
| REQ-S01 | Double-issue prevention | transfusion/issue.py SELECT FOR UPDATE | C-01, C-02 | OQ+PQ |
| REQ-S02 | Reactive TTI lockout | inventory/state_machine.py | TTI-01–05 | OQ |
| REQ-S03 | SoD at issue | transfusion/issue.py:_check_sod | S-16, S-17 | OQ |
| REQ-CC01 | Cold chain excursion | coldchain/models.py, api/views.py | INT-CC-02 | OQ |
| REQ-A01 | Audit trail immutability | audit/models.py | M-A-08, SEC-08 | OQ |
| REQ-P11 | Electronic signatures | audit/models.py:ElectronicSignature | M-A-05–07 | OQ |
| REQ-P11 | Unique user IDs | accounts/models.py | F.1 auth tests | OQ |
| ... | ... | ... | ... | ... |

---

## SECTION M — CI/CD PIPELINE

### M.1 Recommended GitHub Actions Workflow

```yaml
# .github/workflows/test.yml
name: Blood Bank LIS Test Suite

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: bloodbank_test
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-test.txt

      - name: Security scan (Bandit)
        run: bandit -r . -x .venv,tests/ -ll

      - name: Dependency CVE check
        run: safety check -r requirements.txt

      - name: Run safety-critical tests first
        run: pytest tests/ -m safety_critical -v --tb=long
        env:
          DJANGO_SETTINGS_MODULE: bloodbank.settings_test

      - name: Run full test suite
        run: pytest --cov=. --cov-report=xml --cov-fail-under=80 -n auto
        env:
          DJANGO_SETTINGS_MODULE: bloodbank.settings_test

      - name: Upload coverage
        uses: codecov/codecov-action@v4
```

### M.2 Coverage Targets

| Module | Min Coverage |
|--------|-------------|
| transfusion/issue.py | 100% |
| inventory/state_machine.py | 100% |
| audit/models.py | 95% |
| compliance/engine.py | 90% |
| analytics/forecasting.py | 90% |
| Overall | 80% |

---

## APPENDIX: Test Execution Summary

Quick reference to run each test layer:

```bash
# Layer 0: Pure unit tests (fastest, no DB)
pytest tests/unit/ -v

# Layer 1: Model tests
pytest tests/models/ -v

# Layer 2: Safety-critical ONLY (run first, must all pass)
pytest -m safety_critical -v --tb=long

# Layer 3: Integration
pytest tests/integration/ -v

# Layer 4: API
pytest tests/api/ -v

# Layer 5: Security
pytest tests/security/ -v
bandit -r . -ll

# Layer 6: Performance (requires running server)
locust -f tests/locustfile.py --host=http://localhost:8000

# Full suite with coverage
pytest --cov=. --cov-report=html -n auto
open htmlcov/index.html
```
