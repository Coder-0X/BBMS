# Blood Bank LIS — Deep Research Report 2026
> Compiled 2026-06-29 | Sources: web-verified + standards knowledge (AABB, WHO, FDA, ISO, BCSH, SHOT)
> Project constraint: zero licensing budget, portfolio/academic scope, domestic deployment

---

## PART 1 — BLOOD BANK LIS TECHNICAL STANDARDS & REQUIREMENTS

---

### 1.1 AABB Technical Manual (22nd Edition, 2023) — Key Software Requirements

The AABB Technical Manual 22nd edition (current as of 2026) sets the gold standard for US blood bank software. Key requirements for LIS:

#### Pretransfusion Testing Chain (Chapter 12)
Every compatible-unit release requires this chain in order:
1. **ABO/Rh typing** of the patient sample (current draw)
2. **Historical ABO check** — compare with any prior ABO on file; discrepancy → holds until resolved
3. **Antibody screen** (indirect antiglobulin test or gel)
4. **Crossmatch** — immediate spin (IS), AHG (Coombs), or electronic (computer)
5. **Special requirement matching** — irradiated, CMV-neg, leukoreduced, antigen-neg

#### Two-ABO Determination Rule
- Blood group must be confirmed by two independent determinations before issuing group-specific blood
- "Independent" = two separate samples drawn at different times, tested by different staff
- Alternatively: one current sample + one historical result on record in the LIS
- Discrepancy between the two → mandatory discrepancy investigation before any group-specific issue
- Emergency exception: O-neg emergency release with mandatory retrospective resolution
- **LIS enforcement**: Block group-specific issue if `confirmed_abo_count < 2` in patient blood group table

#### Electronic Crossmatch Eligibility (AABB/BSH Criteria)
All FOUR gates must pass to use electronic XM:
1. Patient has ≥2 concordant ABO/Rh results on file (no discrepancy history)
2. Current antibody screen = negative
3. No clinically significant historical antibody (even if currently non-reactive)
4. Unit ABO/Rh has been confirmed by the blood bank (typed on receipt)

Failure of any gate → mandatory serological crossmatch (IS or AHG).

#### Sample Validity
- Type & Screen sample valid: **3 days** (72 hours) from collection for patients transfused or pregnant in past 3 months
- Outpatients with no recent transfusion/pregnancy: up to 3 days still recommended
- Sample expiry must be enforced in the LIS crossmatch POST endpoint

#### Antibody Identification
- Any reactive antibody screen → full panel identification required
- Historical significant antibodies must be flagged for life (even if currently non-detectable on screen)
- Anti-K, anti-c, anti-E, anti-Jka, anti-Fyb etc. — must force antigen-negative unit selection permanently

---

### 1.2 WHO Blood Safety Guidelines

WHO Global Action Plan for Blood Safety 2016-2025 (and successor 2025+ framework) establishes:

#### Core BECS Requirements (WHO/BS/2018.04)
- Electronic blood establishment computer system (BECS) as mandatory infrastructure for any national blood service
- Minimum data set: donor identity, donation history, TTI results, component processing, distribution/transfusion, adverse events, recall capability
- Traceability requirement: vein-to-vein in both directions (donor → patient and patient → donor)
- Data retention: minimum 30 years for transfusion records (WHO aligns with EU directive)

#### WHO Blood Component Quality Requirements
| Component | Storage Temp | Max Age | Special |
|-----------|-------------|---------|---------|
| RBC | +2 to +6°C | 42 days (SAGM) / 35 days (CPD) | |
| Platelets | +20 to +24°C, agitation | 5 days (7 with pathogen reduction) | |
| FFP | ≤−25°C | 24 months | |
| Cryoprecipitate | ≤−25°C | 24 months | |
| Granulocytes | +20 to +24°C | 24h | Irradiate |

#### WHO Haemovigilance Framework
- All serious adverse reactions reportable to national haemovigilance system
- Categories: acute haemolytic, delayed haemolytic, TACO, TRALI, allergic, anaphylactic, septic, TA-GvHD, PTP, FNHTR
- Severity scale: S1 (non-severe) to S4 (fatal)
- Imputability (causality): NA/0 (excluded) to 3 (definite)

---

### 1.3 FDA 21 CFR Part 606 & Part 11 Requirements

#### 21 CFR Part 606 — Current Good Manufacturing Practice (Blood Banks)
- §606.100: Written procedures for all operations (SOPs)
- §606.122: Equipment qualification and calibration records
- §606.145: Compatibility testing — all results must be recorded
- §606.160: Records — must be retained for 10 years minimum (longer if required by state)
- §606.171: Reporting of product deviations to FDA
- All records must be attributable, legible, contemporaneous, original (ALCOA+)

#### 21 CFR Part 11 — Electronic Records & Electronic Signatures
For a Django LIS to meet Part 11:

**Technical controls required:**
- System access controls (unique user ID + password or MFA)
- Audit trail: computer-generated, timestamp-stamped, operator-identified
- Record sequences with date/time of operator entries and actions (cannot be disabled)
- Authority checks on access
- Device checks to ensure input device integrity

**Electronic signatures must:**
- Be unique to one individual (no shared accounts)
- Be linked to their respective electronic record (cryptographic binding)
- Contain printed name, date/time, meaning (reviewed/approved/witnessed)
- Non-biometric e-sigs require: ID code + password at each signing

**Our implementation status**: Hash-chained audit log + ElectronicSignature model with HMAC-bound content hash ✅

#### FDA BECS 510(k) Guidance (2024 Update)
- Blood establishment computer software is a Class II medical device (510(k) required for commercial sale in US)
- Portfolio/academic use: no 510(k) needed
- Key predicate devices: SafeTrace Tx (Haemonetics), HCLL (Mediware), Cerner BloodBank
- Required for clearance: software lifecycle documentation (IEC 62304), hazard analysis (IEC 14971), usability testing (IEC 62366)

---

### 1.4 ISO 15189:2022 — Medical Laboratories Requirements

Key clauses affecting blood bank LIS:

| Clause | Requirement | Our Coverage |
|--------|------------|--------------|
| 6.2 | Competence of personnel | StaffCompetency model ✅ |
| 7.4 | Examination procedures (SOPs) | SOP Management module ✅ |
| 7.7 | Nonconforming work | NonConformance + CAPA ✅ |
| 8.6 | Quality indicators | Quality Indicators Report ✅ |
| 8.7 | Internal audit | InternalAudit + AuditFinding ✅ |
| 8.8 | Management review | TransfusionCommittee ✅ |

Critical for LIS: Clause 5.10 (reporting of results) requires that LIS reports are unambiguous, include reference intervals, and are traceable to the authorized person who released them.

---

### 1.5 EU Blood Directives

#### Directive 2002/98/EC (Blood Safety Directive)
- Mandatory traceability: each blood component traceable from donor to recipient and back, for 30 years
- Mandatory haemovigilance reporting: serious adverse reactions and events
- Notification to competent authority within 24h for serious adverse reactions

#### Directive 2005/62/EC (Technical Requirements Annex)
- Blood establishment computer system must be validated before use
- IQ/OQ/PQ validation required (see Section 2.1)
- Any system change triggers re-validation of affected functions
- Data backup and disaster recovery mandatory
- User access levels and audit trail mandatory

#### ISBT 128 vs Code 128 — The Licensing Reality

**What requires ICCBBA licensing (paid):**
- The ISBT 128 application identifier structure (flag characters, product codes)
- Official ISBT 128 product description codes (PDCs) — the 6-character codes like E0140AT
- ISBT 128 donation identification number (DIN) format registration
- ISBT 128 donor unit label format

**What is free (no license needed):**
- Code 128 barcode symbology itself (ISO/IEC 15417) — entirely free standard
- Code 128 encoding libraries (python-barcode MIT licensed ✅ confirmed)
- GS1-128 (formerly EAN-128) — free for non-blood use, GS1 membership needed for GS1 prefixes
- Your own custom DID format encoded in Code 128 — fully free
- python-barcode supports Code 128 natively ✅ confirmed

**Our approach**: 12-character custom DID with Luhn check, encoded as Code 128 — fully defensible for domestic non-accredited use.

---

### 1.6 SHOT (Serious Hazards of Transfusion) — 2023 Annual Report Categories

SHOT 2023 (UK) reported 3,744 reports. Key categories our system must capture:

| Category | Code | Count 2023 | LIS Tracking |
|----------|------|-----------|--------------|
| Incorrect Blood Component Transfused | IBCT | 893 | TransfusionReaction ✅ |
| Wrong Blood in Tube (WBIT) | WBIT | 1,119 | BloodGroupDiscrepancyInvestigation ✅ |
| Near Miss | NM | 586 | Haemovigilance dashboard ✅ |
| Transfusion-Associated Circulatory Overload | TACO | 286 | Reaction type ✅ |
| Transfusion-Related Acute Lung Injury | TRALI | 42 | Reaction type ✅ |
| Transfusion-Associated GvHD | TA-GvHD | 2 | — (rare, track via special req) |
| Febrile Non-Haemolytic Reaction | FNHTR | 179 | Reaction type ✅ |
| Post-Transfusion Purpura | PTP | 8 | — |
| Haemolytic Disease of the Fetus/Newborn | HDFN | tracked | HaemolyticDiseaseCase ✅ |

**WBIT is the #1 event** (1,119 reports). Our bedside PWA two-scan verification directly addresses this.

---

### 1.7 FHIR R4 Blood Bank Resources

Our current FHIR facade covers the basics. Full R4 implementation should include:

#### BiologicallyDerivedProduct (BDP)
```json
{
  "resourceType": "BiologicallyDerivedProduct",
  "id": "unit-DID-here",
  "identifier": [{"system": "urn:local:did", "value": "DID-XXXXXXXXXXXX"}],
  "productCategory": "cells",
  "productCode": {"coding": [{"system": "urn:local:component", "code": "RBC"}]},
  "status": "available",
  "collection": {
    "collector": {"reference": "Practitioner/staff-id"},
    "collectedDateTime": "2026-01-15T09:00:00Z"
  },
  "processing": [
    {"description": "Leukoreduced", "procedure": {"coding": [{"code": "leukoreduced"}]}}
  ],
  "storage": [
    {"temperature": 4.0, "scale": "celsius", "duration": {"start": "2026-01-15", "end": "2026-02-26"}}
  ]
}
```

#### fhir.resources Python Library (VERIFIED ✅)
- BSD license, zero cost
- `pip install fhir.resources` — supports R5, R4B, STU3 via Pydantic V2
- R4B (version 4.3.0) includes `BiologicallyDerivedProduct` resource
- **Recommendation**: upgrade our FHIR facade to use `fhir.resources` for validated serialization

---

### 1.8 HL7 v2.5.1 Blood Bank Messages

For LIS interoperability with hospital systems:

| Message | Trigger | Use |
|---------|---------|-----|
| ADT^A01 | Patient admit | Create patient record |
| ADT^A04 | Patient register | Create patient record |
| ADT^A08 | Patient update | Update demographics |
| ADT^A40 | Patient merge | MPI merge workflow |
| OML^O21 | Laboratory order (generic) | Blood request from HIS |
| OML^O33 | Laboratory order (specimen in multiple containers) | Multi-sample crossmatch |
| ORU^R01 | Results | TTI results, blood group, crossmatch |
| ORM^O01 | General order | Blood product order from OR/ICU |

**python-hl7 library** (VERIFIED ✅): MIT licensed, parses HL7 v2.x, no FHIR support.
For our portfolio use, manual HL7 serialization or python-hl7 is sufficient.

**Key HL7 segment for blood bank:**
- OBX segment carries blood group, antibody screen result, crossmatch result
- SPM segment describes specimen (sample for crossmatch)
- SAC segment for specimen container/aliquot tracking

---

### 1.9 Blood Component Irradiation Standards (BCSH/AABB)

#### Dose
- **Minimum**: 25 Gy to the central portion of the pack (BCSH/AABB)
- **Maximum**: 50 Gy (BCSH); some guidelines say 50 Gy to minimize red cell damage
- Our model enforces 25–50 Gy validation ✅

#### Post-Irradiation Expiry
| Component | Pre-Irradiation Expiry | Post-Irradiation Rule |
|-----------|----------------------|----------------------|
| RBC | 42 days from collection | 14 days from irradiation OR original expiry, whichever sooner |
| Granulocytes | 24h | Irradiate and use ASAP |
| Platelets | 5 days | No post-irradiation expiry reduction (BCSH) |
| FFP | 24 months | Irradiation not required/applicable |

Our `irradiate_unit` view reduces RBC expiry to 14 days post-irradiation ✅

#### Who MUST receive irradiated products (BCSH 2012)
- All patients with congenital T-cell deficiency
- Severe combined immunodeficiency (SCID)
- Hodgkin lymphoma (all stages)
- Allogeneic haematopoietic stem cell transplant (all life after)
- Autologous HSCT (6 months before through post-transplant)
- Fludarabine, cladribine, deoxycoformycin recipients
- ALL HLA-matched or directed donations
- Neonates receiving exchange or IUT transfusion
- Infants up to 6 months post-term (for exchange transfusion)

---

### 1.10 Cold Chain Standards

#### WHO Performance Qualification Specifications (PQS)
- E003 series: blood cold chain equipment qualification
- Storage temperature loggers: 0.5°C accuracy, ≥8,000 data points, NIST-traceable calibration

#### IATA P650 (Dangerous Goods Regulations - Blood)
- Classification: UN 3373 Biological Substance Category B (for non-infectious diagnostic specimens)
- Packaging: primary receptacle + secondary + outer (triple packaging)
- Temperature maintenance documentation required for transport

#### Cold Chain LIS Requirements
- Sensor heartbeat monitoring (alert if no reading for >15 min)
- Calibration tracking (annual minimum)
- Auto-excursion detection + auto-quarantine of affected units
- Unit return check (blood issued and returned must have temp verified)
- Shipment cold chain logger data attached to transfer records

---

### 1.11 Neonatal Transfusion Requirements

Based on BCSH 2004/2016 guidelines and AABB:

#### Irradiation
- All cellular products for neonates and infants <4 months post-term who received IUT
- Exchange transfusion: mandatory irradiation
- Top-up transfusion: irradiation if any of: IUT history, severe immunodeficiency, HLA-matched, directed from relative

#### CMV Status
- CMV-seronegative OR leukodepleted (WBC <1×10^6/unit) considered equivalent for CMV risk reduction
- UK practice: leukodepleted = CMV-safe (no CMV-negative requirement needed if leukodepleted)
- AABB: either CMV-negative or leukodepleted acceptable

#### Age of Unit
- BCSH: neonatal top-up RBC ideally <5 days old (to maximize 2,3-DPG content)
- Exchange transfusion: ≤5 days old strongly preferred
- Our NeonatalTransfusionOrder model tracks max volume (15 mL/kg top-up, 160 mL/kg exchange) ✅

#### Volume
- Top-up: 10–20 mL/kg (maximum 20 mL/kg per transfusion)
- Exchange: 160–200 mL/kg (two-volume exchange)

---

### 1.12 Massive Transfusion Protocol (MTP) — Current Evidence

#### Ratio Evidence (PROPPR Trial 2015 + subsequent data)
- The PROPPR trial (JAMA 2015): 1:1:1 (plasma:platelets:RBC) reduced 24h mortality vs 1:1:2
- Current consensus: 1:1:1 ratio target, accepting 1:1:2 in practice
- Note: Some guidelines (Australian MJA 2024) use 2:1:1 RBC:FFP:PLT ratio notation

#### MTP Trigger Criteria (ABC Score)
Assessment of Blood Consumption (ABC) Score ≥2 → activate MTP:
- Systolic BP ≤90 mmHg (+1)
- Heart rate ≥120 bpm (+1)
- Penetrating mechanism (+1)
- Positive FAST exam (+1)

Alternative: Shock Index (HR/SBP) ≥1.0 as trigger

#### Haemostatic Adjuncts
- Tranexamic acid: ≤3h from injury (CRASH-2 trial evidence)
- Fibrinogen concentrate or cryoprecipitate if fibrinogen <1.5–2.0 g/L
- Our MTPActivation model tracks stand-down and retrospective XM ✅

---

### 1.13 Patient Blood Management (PBM) — Current Standards

#### Restrictive Transfusion Thresholds (AABB 2023 / JAMA 2023)
Based on 45 RCTs with 20,599 adults:
- Stable hospitalized adults: transfuse if Hb <7 g/dL
- ICU/cardiac surgery: 7–8 g/dL depending on clinical status
- Active ACS: ≤8 g/dL (more liberal threshold evidence-based)
- Single-unit policy: transfuse one unit, re-assess before second

#### WHO PBM Declaration (2010 + 2023 update)
World Health Assembly resolution WHA63.12 endorses PBM as essential practice.
Key pillars:
1. Optimise RBC mass (pre-op anaemia treatment, ESA, IV iron)
2. Minimise blood loss (surgical technique, cell salvage, antifibrinolytics)
3. Optimise tolerance of anaemia (normovolaemia, oxygen delivery)

Our PBM dashboard tracks: coverage%, compliance%, Hb increment, trigger bands ✅

---

## PART 2 — BLOOD BANK SOFTWARE TESTING & VALIDATION

---

### 2.1 Computer System Validation (CSV) Framework

#### IQ/OQ/PQ Framework (FDA Guidance / GAMP 5)

**Installation Qualification (IQ)**
Verifies the system is installed correctly:
- Hardware specifications met (CPU, RAM, disk, OS version)
- Software installed at correct version (Django 5.x, PostgreSQL 16.x, Python 3.12.x)
- Configuration files present and correct (settings.py, .env, nginx.conf)
- Required Python packages installed at pinned versions (requirements.txt frozen)
- Database migration state: `python manage.py showmigrations` all ✅
- Static files collected: `python manage.py collectstatic` completes without error
- Document: IQ protocol executed by, date, system version, pass/fail per item

**Operational Qualification (OQ)**
Verifies the system performs as designed:
- All functional test cases pass (see Section 2.2)
- All safety-critical paths tested with both valid and boundary inputs
- Error handling tested (invalid input, missing required fields, DB errors)
- User roles and permissions verified for every protected view
- Audit trail entries created for all audited actions
- Electronic signatures cryptographically bind to record content
- Document: OQ protocol with test case ID, expected result, actual result, pass/fail

**Performance Qualification (PQ)**
Verifies the system performs in the actual use environment:
- Load test: simulate peak simultaneous users (see Section 2.4)
- Stress test: system degrades gracefully at 2x peak load (no data corruption)
- Failover test: simulate database disconnect and reconnect
- Cold chain data ingest at maximum sensor rate
- Document: PQ protocol with performance benchmarks

#### Traceability Matrix
Map every requirement (REQ-X01, REQ-D01, etc.) to:
- Test case ID(s) that verify it
- Code file and function that implements it
- IQ/OQ/PQ phase where it is tested

---

### 2.2 Safety-Critical Test Scenarios (Mandatory)

These tests are non-negotiable. Failure = system unsafe to deploy.

#### TC-S01: ABO Incompatible Issue Prevention
```
Setup: Patient A+ with confirmed blood group. Unit B+ available.
Action: Attempt to issue B+ unit to A+ patient.
Expected: IssueError raised, unit NOT issued, audit entry created.
Verify: BloodUnit status unchanged (still 'available'), no IssueTransaction created.
```

#### TC-S02: Double-Issue Prevention (Concurrency)
```
Setup: One unit 'available'. Two staff members attempt simultaneous issue.
Action: Two concurrent requests to issue_unit() for same blood_unit_id.
Expected: Exactly one succeeds, one receives IssueError("unit locked").
Verify: Exactly one IssueTransaction created. Unit status = 'issued'.
Method: Use threading.Thread or Django test client with concurrent requests.
```

#### TC-S03: Expired Unit Blocking
```
Setup: RBC unit with expiry_date = yesterday.
Action: Attempt to issue via issue_unit().
Expected: IssueError("unit expired"), unit NOT issued.
Verify: Unit status unchanged, no IssueTransaction. Transition log unchanged.
```

#### TC-S04: Quarantined Unit Blocking
```
Setup: Unit in status 'quarantined' (e.g. TTI reactive).
Action: Attempt to issue.
Expected: StateTransitionError or IssueError — cannot transition quarantined → issued.
Verify: Unit remains quarantined. Database-level CHECK constraint also prevents this.
```

#### TC-S05: Recalled Unit Blocking
```
Setup: Unit that has been recalled (status='recalled').
Action: Attempt to issue.
Expected: Hard block — cannot issue recalled unit under any circumstances.
```

#### TC-S06: Special Requirements Enforcement
```
Setup: Patient requires irradiated units (PatientTransfusionRequirement).
       Non-irradiated RBC unit available.
Action: Attempt to issue non-irradiated unit.
Expected: IssueError with "patient requires irradiated units".
Verify: Issue of irradiated unit to same patient succeeds.
```

#### TC-S07: Antibody-Driven Block at Issue
```
Setup: Patient has anti-K antibody in history.
       Unit with K+ antigen (antigen_negative_set does NOT include 'K').
Action: Attempt to issue K+ unit to anti-K patient.
Expected: IssueError("unit incompatible with patient antibody: anti-K").
Verify: K-negative unit issues successfully.
```

#### TC-S08: Two-ABO Rule Enforcement at Issue
```
Setup: Patient with only 1 confirmed ABO determination on file.
Action: Attempt to issue group-specific (non-O-neg) unit.
Expected: Block — "insufficient ABO determinations".
Verify: After adding 2nd concordant ABO, issue succeeds.
```

#### TC-S09: Emergency Uncrossmatched Release Audit
```
Setup: Emergency situation — no crossmatch on file.
Action: Emergency release of O-neg unit via emergency_release view.
Expected: Succeeds with O-neg unit, EmergencyRelease record created,
          retrospective XM reminder alert created.
Verify: AuditLog entry with action='emergency_release', ElectronicSignature present.
```

#### TC-S10: Reactive TTI Result Lockout
```
Setup: Unit in 'in_testing'. Record reactive HIV result.
Action: Attempt to clear to 'available'.
Expected: StateTransitionError — reactive TTI prevents release.
Verify: Unit auto-quarantined, Alert of type 'reactive_tti' created.
```

#### TC-S11: Separation of Duties at Issue
```
Setup: User U1 collected the donation. Same U1 attempts to issue the unit.
Action: issue_unit() called with actor=U1 who also collected.
Expected: SoDError — collector cannot also be issuer.
Verify: No IssueTransaction created.
```

#### TC-S12: Sample Validity in Crossmatch
```
Setup: Patient sample collected 4 days ago (expired, >72h).
Action: Attempt to add crossmatch against this sample.
Expected: ValidationError — "sample expired (3-day rule)".
Verify: No Crossmatch record created.
```

---

### 2.3 Full Test Suite Structure

#### Infrastructure Setup
```
requirements-test.txt:
  pytest==8.x
  pytest-django==4.x
  factory_boy==3.x
  Faker==25.x
  hypothesis==6.x
  coverage==7.x
  pytest-cov==5.x
  pytest-xdist==3.x  (parallel test execution)
  locust==2.x        (load testing)
  bandit==1.x        (security static analysis)
```

#### conftest.py — Shared Fixtures
```python
# tests/conftest.py
import pytest
from django.contrib.auth import get_user_model
from tests.factories import (
    BranchFactory, UserFactory, DonorFactory, PatientFactory,
    BloodUnitFactory, DonationFactory
)

@pytest.fixture
def branch(db):
    return BranchFactory()

@pytest.fixture
def staff_user(db, branch):
    return UserFactory(branch=branch)

@pytest.fixture
def available_rbc(db, branch):
    return BloodUnitFactory(
        status='available',
        component_class='RBC',
        branch=branch,
        expiry_date=timezone.now().date() + timedelta(days=30),
    )

@pytest.fixture
def patient_a_pos(db, branch):
    p = PatientFactory(branch=branch)
    # Add 2 concordant ABO determinations
    PatientBloodGroupFactory(patient=p, abo='A', rh_d='pos', is_discrepant=False)
    PatientBloodGroupFactory(patient=p, abo='A', rh_d='pos', is_discrepant=False)
    return p
```

#### Layer 0 — Pure Unit Tests (no DB, instant)
Files: `tests/unit/test_abo_logic.py`, `tests/unit/test_forecasting.py`, `tests/unit/test_holt_winters.py`, `tests/unit/test_luhn.py`

```python
# test all 8×8 ABO compatibility matrix
# test all Holt-Winters edge cases
# test Luhn DID checksum validation
# test compliance rule evaluation (mock rule objects)
```

#### Layer 1 — Model Unit Tests (with DB)
Files per app: `tests/models/test_patient_models.py`, `tests/models/test_donor_models.py`, etc.

```python
# Patient.effective_blood_group() fallback logic
# Patient.current_blood_group() returns latest non-discrepant result
# BloodUnit.is_expired() for edge cases (boundary day, UTC midnight)
# Donor.is_eligible_to_donate() all deferral combinations
# Donor.category() — all thresholds
# Donor.next_milestone() — all thresholds
# SubjectIdentity.display_name — decrypt roundtrip
# AuditLog chain integrity (hash chain validation)
# ElectronicSignature.verify() — correct key, tampered content
# PatientPhenotype.required_negative_antigens() — all antibody scenarios
# DonorPhenotype.antigen_negative_set() propagation
# Donation.has_deferral_triggers() — each trigger individually
# RetentionCampaign.response_rate(), conversion_rate()
# HaemolyticDiseaseCase.is_severe() — all severity levels
```

#### Layer 2 — State Machine Tests
File: `tests/test_state_machine.py`

```python
# All valid transitions: available→reserved, reserved→crossmatched, crossmatched→issued, issued→transfused
# All forbidden transitions: issued→available, transfused→available, etc.
# Expired unit cannot transition to any active state
# Quarantined→available blocked if TTI reactive
# Database CHECK constraint test: attempt raw SQL INSERT with invalid transition
```

#### Layer 3 — View / Integration Tests
Files per app: `tests/integration/test_donor_views.py`, etc.

```python
# All views: authentication required (redirect to login if not authenticated)
# All views: permission required (403 if wrong role)
# Donor registration: POST → Donor created, ConsentRecord created, SubjectIdentity encrypted
# Blood request: POST → BloodRequest created, audit entry, redirect
# Crossmatch: POST with valid sample → Crossmatch created; with expired sample → error
# Issue: POST → IssueTransaction created, unit status=issued, audit, e-signature
# Emergency release: POST → EmergencyRelease, O-neg only, audit
# Irradiate: POST → ProcessingEvent, expiry recalculated, e-signature
# MTP activate: POST → MTPActivation, O-neg check, alert
# Antenatal Anti-D: overdue alert created correctly
```

#### Layer 4 — API Tests (DRF)
File: `tests/api/test_drf_endpoints.py`

```python
# GET /api/v1/units/ — paginated, auth required
# POST /api/v1/temperature/ — idempotent (same UUID = no duplicate)
# POST /api/v1/temperature/ — out of range → excursion created, units quarantined
# POST /api/v1/bedside/verify/ — correct pair → pass; ABO mismatch → stop
# GET /fhir/Patient/{id} — valid FHIR R4 JSON
# GET /fhir/BiologicallyDerivedProduct/{did} — valid FHIR R4 JSON
```

#### Layer 5 — Security Tests
File: `tests/security/test_security.py`

```python
# CSRF token required on all POST views
# XSS: inject <script> in donor name → stored encrypted, rendered escaped
# SQL injection: malicious DID in URL → parameterised query, no injection
# Horizontal privilege escalation: user from branch A cannot view branch B data
# SoD: collector cannot issue
# Permission boundary: technician cannot approve NC (requires QA role)
# Session fixation: session rotates on login
# Password policy: rejects common passwords
# MFA bypass: cannot access sensitive views without TOTP if MFA enrolled
# Audit log immutability: cannot UPDATE or DELETE audit_logs via ORM
```

#### Layer 6 — Audit & Cryptography Tests
File: `tests/test_audit.py`

```python
# write_audit() creates AuditLog with correct fields
# Hash chain: log[n].prev_hash == SHA256(log[n-1].content)
# Hash chain tamper: modify a record → verify_chain() returns False at that point
# ElectronicSignature: created with correct user, action, content hash
# verify_signature(): correct returns True; tampered content returns False
# Encryption roundtrip: encrypt(x) → decrypt() → x, for name/NID/contact
# Blind index: same input → same hash (deterministic); different input → different hash
```

#### Layer 7 — Compliance Engine Tests
File: `tests/test_compliance.py`

```python
# All 20+ deferral rules: each one individually triggers correct deferral
# Minimum age rule: 17/18 boundary
# Minimum weight: <50kg blocked
# Minimum Hb: <12.5 g/dL (female), <13.0 g/dL (male) blocked
# Donation interval: <56 days from last whole blood blocked
# Temporary deferral: deferral_until in future → blocked
# Permanent deferral: never eligible
# Medical director override: overrides temporary but not permanent
```

#### Layer 8 — Analytics Tests
File: `tests/test_analytics.py`

```python
# build_daily_facts: correct aggregation for each component class
# Holt-Winters: sufficient history → forecast length correct
# Holt-Winters: constant series → constant forecast
# Holt-Winters: no negative forecasts
# check_shortages: stock below threshold → Alert created
# KPI calculations: wastage%, C:T ratio, all edge cases (division by zero)
```

#### Layer 9 — Cold Chain Tests
File: `tests/test_coldchain.py` (expand existing)

```python
# Temperature in range → no excursion
# Temperature out of range → TemperatureExcursion created
# Out of range → affected units in equipment → auto-quarantined
# Sensor offline > 15 min → sensor_offline Alert
# Calibration overdue → alert
# Idempotent ingest: same reading_uuid → no duplicate log entry
# Shipment cold chain: excursion detected → ShipmentColdChain.excursion_detected=True
```

#### Layer 10 — Haemovigilance & Clinical Tests
File: `tests/test_haemovigilance.py`

```python
# TransfusionReaction.is_serious() — severity threshold
# Haemovigilance dashboard: reaction rate per 1000 calculated correctly
# HDFN: severity levels and is_severe()
# MTP: O-neg pre-check alert when stock low
# Anti-D RAADP overdue alert fired at correct timing
# PBM: post_hb_gap alert when >50% RBC requests lack post-Hb in 14d
# Post-transfusion outcome: hb_increment() calculation
```

---

### 2.4 Performance & Load Testing

#### Expected Volume for a Mid-Sized Blood Bank
- 500–2,000 units processed per month
- Peak: 20–50 simultaneous active users (multi-branch)
- Crossmatch transaction volume: 30–100 per day
- Temperature log ingest: 1 reading per sensor per 5 min, up to 50 sensors = 10/min

#### Locust Load Test Scenarios
```python
# locustfile.py
class BloodBankUser(HttpUser):
    wait_time = between(1, 3)

    @task(5)
    def view_dashboard(self):
        self.client.get("/")

    @task(3)
    def view_inventory(self):
        self.client.get("/inventory/units/")

    @task(2)
    def crossmatch_workflow(self):
        # POST crossmatch → GET result → POST lock unit
        ...

    @task(1)
    def temperature_ingest(self):
        self.client.post("/api/v1/temperature/", json={...})
```

#### Performance Targets
| Operation | Target P50 | Target P99 |
|-----------|-----------|-----------|
| Dashboard load | <200ms | <500ms |
| Inventory list (paginated) | <300ms | <800ms |
| issue_unit() transaction | <500ms | <1000ms |
| Crossmatch POST | <300ms | <700ms |
| Temperature ingest API | <100ms | <300ms |
| PDF generation (report) | <2000ms | <5000ms |

#### Concurrency Test (Double-Issue Prevention)
```python
# tests/test_concurrency.py
from concurrent.futures import ThreadPoolExecutor

def test_double_issue_prevention(db, available_rbc, patient_a_pos, staff_user):
    results = []
    def attempt_issue():
        try:
            from transfusion.issue import issue_unit
            result = issue_unit(available_rbc.pk, patient_a_pos.pk, ...)
            results.append('success')
        except Exception as e:
            results.append(f'fail: {e}')

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(attempt_issue) for _ in range(2)]
        for f in futures:
            f.result()

    successes = [r for r in results if r == 'success']
    assert len(successes) == 1, f"Expected exactly 1 success, got {successes}"
    available_rbc.refresh_from_db()
    assert available_rbc.status == 'issued'
```

---

### 2.5 Security Testing

#### Static Analysis
```bash
bandit -r bloodbank-app/ -ll  # check for common security issues
safety check                   # check dependencies for known CVEs
```

#### OWASP Top 10 Checklist for Blood Bank LIS
| Risk | Our Mitigation | Test Method |
|------|---------------|------------|
| A01 Broken Access Control | @permission_required on every view | Test each view without permission |
| A02 Cryptographic Failures | Argon2id passwords, AES-256-GCM PII | Unit test decrypt roundtrip |
| A03 Injection | ORM parameterized queries | Fuzzing DID field with SQL |
| A04 Insecure Design | SoD, two-person rules, e-signatures | TC-S11 SoD test |
| A05 Security Misconfiguration | DEBUG=False, ALLOWED_HOSTS, HSTS | Config audit |
| A06 Vulnerable Components | `safety check` | CI pipeline |
| A07 Auth Failures | TOTP MFA, session timeout, lockout | Auth test suite |
| A08 Software Integrity | Hash-chained audit log | TC-Audit tamper test |
| A09 Logging Failures | Audit log all sensitive actions | Verify audit entries |
| A10 SSRF | No outbound HTTP from app | N/A for this architecture |

---

### 2.6 Database Constraint Tests

```python
# tests/test_db_constraints.py
from django.db import connection, IntegrityError

def test_blood_unit_status_check_constraint(db):
    """PostgreSQL CHECK constraint prevents invalid status values."""
    with connection.cursor() as cur:
        with pytest.raises(Exception):  # IntegrityError or DataError
            cur.execute("""
                INSERT INTO inventory_bloodunit (status, ...)
                VALUES ('invalid_status', ...)
            """)

def test_audit_log_no_update(db, audit_entry):
    """Audit log rows cannot be updated after creation."""
    with connection.cursor() as cur:
        with pytest.raises(Exception):
            cur.execute(
                "UPDATE audit_auditlog SET action = 'tampered' WHERE id = %s",
                [audit_entry.pk]
            )
```

---

## PART 3 — FUNDING SOURCES FOR BLOOD BANK HEALTH TECHNOLOGY PROJECTS

---

### 3.1 Open Source / Technology Grants (Best Fit for Solo Developer)

#### NLnet Foundation — NGI (Next Generation Internet)
- **Programs**: NGI0 Commons Fund, NGI0 Entrust, NGI Search
- **Award range**: €5,000–€50,000 (milestone-based, typical €25k)
- **Eligibility**: Open source software projects; individual developers welcome
- **Key requirement**: Project must be fully open source (OSI-approved license)
- **Application**: Rolling deadlines — 1st of every even-numbered month (Feb, Apr, Jun, Aug, Oct, Dec)
- **URL**: https://nlnet.nl/apply/
- **Fit**: HIGH — blood bank LIS as open source health infrastructure fits NGI0 Commons Fund perfectly
- **Notes**: Netherlands-based but funds globally. No citizenship restriction. Very accessible process.

#### Mozilla Foundation — MOSS (Mozilla Open Source Support)
- **Track**: Foundational Technology, Mission Partners
- **Award range**: $10,000–$500,000
- **Eligibility**: Significant open source projects; no for-profit requirement
- **URL**: https://www.mozilla.org/en-US/moss/
- **Fit**: MEDIUM — healthcare open source angle; not explicitly health-focused

#### Open Technology Fund (OTF)
- **Programs**: Core Infrastructure Fund, Fellowships
- **Award range**: Up to $900,000/year (Core Infrastructure); $80,000 (Fellowship)
- **Eligibility**: Global; open source; focus on internet freedom and access
- **URL**: https://www.opentech.fund/
- **Fit**: LOW-MEDIUM — primarily internet freedom; blood bank LIS is stretch but access-to-health-data angle possible

---

### 3.2 NIH Grants (US — Requires US Institution or SBIR Eligibility)

#### NHLBI SBIR/STTR Program
- **Mechanism**: R43 (Phase I, up to $250k / 6mo), R44 (Phase II, up to $1.5M / 2yr)
- **Focus**: Heart, lung, blood, sleep disorders technology
- **Blood relevance**: Transfusion medicine, blood safety technology, donor management
- **Eligibility**: US small business (<500 employees) for SBIR; university partnership for STTR
- **Parent announcements**: PA-24-222 (SBIR), PA-24-223 (STTR) — rolling submissions
- **URL**: https://www.nhlbi.nih.gov/sbir
- **Fit**: HIGH (for US entities) — blood safety software directly in scope

#### NLM (National Library of Medicine) R01/R21
- **Program**: Biomedical Informatics and Data Science
- **Focus**: Health data standards, clinical informatics, EHR systems
- **FHIR-aligned LIS work would fit NLM R21 exploratory research grants
- **Award**: R21 up to $275k over 2 years
- **URL**: https://www.nlm.nih.gov/ep/GrantTrainIntro.html
- **Fit**: MEDIUM-HIGH — FHIR-based blood bank LIS is biomedical informatics

#### NIBIB (National Institute of Biomedical Imaging and Bioengineering)
- **Focus**: Point-of-care diagnostics, biosensors, medical devices + software
- **Bedside verification technology could qualify
- **URL**: https://www.nibib.nih.gov/funding-opportunities

---

### 3.3 Global Health / International Funding

#### Gates Foundation — Grand Challenges
- **Relevant challenge**: Global Health — diagnostics, blood safety in LMICs
- **Award**: Exploration grants $100k; Full grants up to $1M
- **Eligibility**: Global; academic/nonprofit/individual
- **URL**: https://gcgh.grandchallenges.org/
- **Fit**: MEDIUM-HIGH — blood bank LIS for low/middle-income countries is explicitly in scope
- **Strategy**: Frame as "open-source blood bank LIS for sub-Saharan Africa/South Asia"

#### Wellcome Trust — Digital Technologies Initiative
- **Focus**: Digital health, data infrastructure, open science
- **Award**: Varies; discovery awards up to £200k; investigator awards up to £3M
- **Eligibility**: Global; academic institutions primarily; some open to individuals via host institution
- **URL**: https://wellcome.org/grant-funding
- **Fit**: MEDIUM — digital health infrastructure angle

#### WHO/PAHO Collaborative Research Grants
- **WHO**: Collaborating Centre designation (institutional); small grants through regional offices
- **PAHO**: Fund for the Americas; targets blood safety in Latin America/Caribbean
- **URL**: https://www.paho.org/en/blood-safety
- **Fit**: MEDIUM — requires institutional affiliation, but blood safety is explicitly priority

#### Global Fund — Blood Safety Component
- **Access**: Via national programs (not direct to individuals)
- **Blood safety**: Part of health system strengthening grants
- **Strategy**: Partner with a national blood service or NGO as implementing partner
- **URL**: https://www.theglobalfund.org/en/applying-for-funding/

#### USAID Development Innovation Ventures (DIV)
- **Award stages**: Stage 1 ($25k–$250k pilot), Stage 2 ($250k–$1.5M), Stage 3 ($1.5M–$15M)
- **Focus**: Breakthrough innovations for global development including health
- **Eligibility**: US and non-US organizations; individuals through host org
- **Note**: DIV was restructured in 2025 following USAID changes; check current status
- **URL**: https://www.usaid.gov/div
- **Fit**: MEDIUM — global health technology innovation in LMICs

---

### 3.4 EU Funding

#### Horizon Europe — Health Cluster (Cluster 1)
- **Budget**: €8.3 billion for health (2021–2027)
- **2026 Work Programme**: Research and Innovation Actions (RIA), Innovation Actions (IA)
- **Relevant calls**: Digital health, health data spaces, rare diseases, blood disorders
- **Minimum consortium**: Usually 3 partners from 3 EU member states (solo developer → partner with university)
- **Award**: Typically €3–15M for full RIA; smaller calls for cascade funding
- **URL**: https://hadea.ec.europa.eu/programmes/horizon-europe/health_en
- **Cascade funding**: Sub-grants through EIC Pathfinder projects (€50k–€200k for SMEs/startups)
- **Fit**: MEDIUM — needs EU consortium; blood safety data infrastructure is relevant

#### European Health Data Space (EHDS)
- New regulation (2024) creating framework for cross-border health data
- Implementation grants available through Member States + EU Commission
- Blood bank interoperability (FHIR) directly relevant

---

### 3.5 Startup Accelerators & Innovation Programs

#### Y Combinator
- **Investment**: $500k (standard deal, 2024)
- **Equity**: ~7%
- **Healthcare track**: Regular acceptance of health tech startups
- **Fit**: MEDIUM — needs commercial product; portfolio project needs productization first
- **URL**: https://www.ycombinator.com/apply

#### Techstars Health
- **Investment**: $120k for 6% equity
- **Focus**: Digital health, medical devices, health IT
- **URL**: https://www.techstars.com/accelerators/healthcare
- **Fit**: MEDIUM-HIGH if commercialized

#### Rock Health
- **Digital health seed fund**: $500k–$1.5M seed investments
- **Focus**: US-based digital health startups
- **URL**: https://rockhealth.com/
- **Fit**: MEDIUM for US-based commercialization

#### AABB Foundation Grants
- **Focus**: Transfusion medicine research and education
- **Award**: Typically $25k–$75k research grants
- **Eligibility**: AABB members and collaborators; academic and professional
- **URL**: https://www.aabb.org/research/aabb-foundation
- **Fit**: HIGH — directly in scope; blood bank LIS and safety research

---

### 3.6 African / Developing World Specific

#### African Development Bank (AfDB) — Health Sector
- Funds national blood services infrastructure in sub-Saharan Africa
- Partners: Usually government health ministries, not individuals directly
- **Strategy**: Approach national blood services (e.g. SANBS in South Africa, KNBTS in Kenya) to include your LIS as part of an AfDB-funded digital health project

#### World Bank — Health Nutrition & Population (HNP)
- Country-level grants for health system strengthening
- Digital health components included in many HNP projects
- **URL**: https://www.worldbank.org/en/topic/health

---

### 3.7 Priority Action Plan for Funding

Ranked by accessibility for solo developer with working prototype:

| Rank | Source | Amount | Timeline | Action |
|------|--------|--------|----------|--------|
| 1 | NLnet Foundation | €5k–€50k | Apply next even month | Open source the repo, apply to NGI0 Commons Fund |
| 2 | AABB Foundation | $25k–$75k | Annual cycle | Become AABB affiliate member, submit research proposal |
| 3 | Gates Grand Challenges | $100k | Quarterly | Frame for LMIC blood safety; apply exploration grant |
| 4 | NLM R21 (via university) | $275k/2yr | Feb/Jun/Oct | Find university collaborator, submit as PI or co-I |
| 5 | NHLBI SBIR Phase I | $250k/6mo | Rolling | Register US LLC or partner with small business |
| 6 | Techstars Health | $120k + mentorship | Annual cohort | Productize, apply for cohort |
| 7 | Wellcome Trust | £50k–£200k | Rolling | Via host institution |

---

## APPENDIX: Library Inventory (Zero-Cost, Verified)

| Library | License | Use in Project | Verified |
|---------|---------|---------------|----------|
| python-barcode | MIT | Code 128 barcode generation | ✅ |
| fhir.resources | BSD | FHIR R4/R5 Python models | ✅ |
| python-hl7 | MIT | HL7 v2.x parsing | ✅ |
| ReportLab | BSD | PDF generation | ✅ |
| cryptography | Apache 2.0 | AES-256-GCM, HMAC | ✅ |
| Django | BSD | Web framework | ✅ |
| djangorestframework | BSD | REST API | ✅ |
| psycopg2 | LGPL | PostgreSQL adapter | ✅ |
| pyotp | MIT | TOTP/HOTP MFA | ✅ |

---

*This report should be re-verified against primary sources before any contractual or regulatory claim. Standards clause numbers and threshold values (especially AABB, BCSH, FDA) should be checked against the current edition of each standard before deployment.*
