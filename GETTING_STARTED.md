# Getting Started

## 1. Set up environment

```bash
cp .env.example .env
# Edit .env with your database credentials and a real SECRET_KEY
```

## 2. Install dependencies

```bash
pip install -r requirements.txt
```

## 3. Create the database

```bash
# In psql:
CREATE DATABASE bloodbank;
CREATE USER bloodbank_user WITH PASSWORD 'yourpassword';
GRANT ALL PRIVILEGES ON DATABASE bloodbank TO bloodbank_user;
```

## 4. Generate and run migrations

```bash
python manage.py makemigrations core accounts audit compliance privacy donors inventory patients transfusion
python manage.py migrate
```

## 5. Create a superuser

```bash
python manage.py createsuperuser
```

## 6. Start the dev server

```bash
python manage.py runserver
```

Admin panel: http://localhost:8000/admin/

## 7. Set up cron alert checks (instead of a background worker)

Add this to your crontab (`crontab -e` on Linux/Mac):
```
*/5 * * * * cd /path/to/bloodbank-app && python manage.py run_alerts
```

On Windows, use Task Scheduler to run the same command every 5 minutes.

## Phase 0 — what's built

- [x] Custom User model with Argon2id passwords
- [x] TOTP MFA (setup + verify flow)
- [x] Idle + absolute session timeout middleware
- [x] Role → Permission system with SoD conflict tracking
- [x] Break-glass emergency access sessions
- [x] Append-only hash-chained audit log
- [x] Electronic signatures with payload binding
- [x] Compliance jurisdiction / ruleset / rule engine
- [x] Privacy: encrypted identity, consent records, DSR requests
- [x] HashiCorp Vault integration (falls back to dev key if Vault not running)
- [x] DID generation with Luhn check digit
- [x] Branch / facility management
- [x] Software alerts: low inventory, near-expiry, pending reviews
- [x] `run_alerts` management command (cron-friendly, no daemon needed)

## Phase 1 — what's built

- [x] Donor model + eligibility check + adverse events
- [x] Donation recording with consent (ConsentRecord)
- [x] `compliance.engine.check_donor_eligibility()` runs before every donation
- [x] TTI test results — reactive result auto-quarantines all units (inside `DonationTestResult.save`)
- [x] `transfusion.testing.record_test_result()` — wraps test recording with e-signature + audit
- [x] Blood unit model with 15-state machine, `abo_type`, `rh_d_type`, all `is_*` processing flags
- [x] `inventory.state_machine.transition_unit()` — atomic status changes with audit trail
- [x] `inventory.state_machine.seed_transitions()` — populates the allowed transition table
- [x] Patient model with MPI UUID, merge support, pseudonymized PII
- [x] Append-only `PatientBloodGroup` — discrepancy detection blocks electronic crossmatch
- [x] Lifelong `PatientAntibody` — even evanescent antibodies stay forever
- [x] `PatientTransfusionRequirement` — standing special requirements (irradiated, CMV-neg, etc.)
- [x] `Sample` model — 3-day rule expiry for recently-transfused / pregnant patients
- [x] `AntibodyScreen` + `AntibodyIdentification` — positive panel auto-writes PatientAntibody
- [x] `BloodRequest` + `Crossmatch` (IS, AHG, electronic) with e-signatures
- [x] `transfusion.issue.issue_unit()` — SELECT FOR UPDATE NOWAIT, ABO check, SoD, special reqs
- [x] `EmergencyRelease` — bypass crossmatch with physician justification + retrospective sign-off
- [x] `IssueTransaction` — immutable record of every issue event
- [x] Views + URLs for all four Phase 1 apps
- [x] Admin for all Phase 1 models

## After Phase 1 migrations

Seed the state machine transition table once:

```bash
python manage.py shell -c "from inventory.state_machine import seed_transitions; seed_transitions()"
```

Seed test definitions (TTI tests):

```python
# In shell or a data migration
from transfusion.models import TestDefinition
tests = [
    ('HIV_AG_AB', 'HIV Ag/Ab Combo', 'HIV-1/2', 'ELISA'),
    ('HBsAg', 'Hepatitis B Surface Antigen', 'HBV', 'ELISA'),
    ('anti_HCV', 'Hepatitis C Antibody', 'HCV', 'ELISA'),
    ('VDRL', 'Syphilis (VDRL/RPR)', 'T. pallidum', 'RPR'),
    ('HIV_NAT', 'HIV Nucleic Acid Test', 'HIV-1', 'NAT'),
    ('HBV_NAT', 'HBV Nucleic Acid Test', 'HBV', 'NAT'),
    ('HCV_NAT', 'HCV Nucleic Acid Test', 'HCV', 'NAT'),
]
for code, name, pathogen, method in tests:
    TestDefinition.objects.get_or_create(test_code=code, defaults={'name': name, 'pathogen': pathogen, 'method': method})
```

## Phase 2 — what's built

- [x] `templates/base.html` — full site shell with nav, messages, stat boxes, badge system
- [x] Dashboard (`/dashboard/`) — alerts, inventory summary by component, pending emergency signoffs
- [x] All donor templates: register, detail, eligibility screen, record donation
- [x] All inventory templates: unit list (filterable), unit detail with status history, record processing, change status, initiate transfer, label print
- [x] All patient templates: register, detail (blood group history, antibody history, special reqs), add blood group, add antibody, add requirement
- [x] All transfusion templates: new request, request detail, collect sample, record TTI, antibody screen, crossmatch, issue unit, emergency release, emergency signoff
- [x] `inventory/create_units.py` — whole blood separation + apheresis unit creation with DID generation, UnitLineage tracking
- [x] `inventory/labels.py` — Code 128 barcode generation (python-barcode, ISO/IEC 15417, no license) + label print logging
- [x] `templates/inventory/separate_components.html` — component selection UI
- [x] `templates/inventory/label.html` — printable blood unit label with barcode image
- [x] `core/views.py` — dashboard view with inventory stats
- [x] `python-barcode[images]` added to requirements.txt
- [x] Root URL `/` redirects to `/dashboard/`

## Phase 3 — what's built

- [x] `api/` app — DRF serializers + read-only viewsets for all models
- [x] API endpoints at `/api/v1/`: branches, components, donors, units, patients, requests, samples, transactions, alerts
- [x] `GET /api/v1/units/available/?abo=A&rh=pos&component_class=RBC&branch=1` — ABO-compatible unit search
- [x] `GET /api/v1/patients/{id}/compatible_units/` — respects patient special requirements
- [x] `GET /api/v1/units/{id}/lineage/` — vein-to-vein ancestor/descendant tree
- [x] `POST /api/v1/alerts/{id}/acknowledge/` — alert acknowledgement endpoint
- [x] `inventory/recall.py` — recursive CTE-based unit lookup + `execute_recall()` with full audit trail
- [x] Recall management UI at `/inventory/recall/`
- [x] `transfusion/haemovigilance.py` — `record_reaction()` with grade-based auto-alerting
- [x] `TransfusionReaction` model in `transfusion/models.py` — full reaction/haemovigilance record
- [x] Transfusion reaction recording UI at `/transfusion/transaction/{id}/reaction/`
- [x] `core/reports.py` — blood utilization, inventory age (FEFO), donor stats, TTI positivity, reaction report
- [x] Reports dashboard at `/reports/`
- [x] `core/management/commands/seed_data.py` — seeds ComponentTypes (13), TestDefinitions (11), and state transitions
- [x] `python manage.py seed_data` — one-shot setup command

## Setup after all migrations

```bash
python manage.py makemigrations core accounts audit compliance privacy donors inventory patients transfusion api
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_data
```

## Phase 4 — what's built

- [x] Auth templates: `login.html`, `mfa_setup.html`, `mfa_verify.html`, `mfa_recovery_codes.html`, `logout_confirm.html`, `reauth.html`
- [x] Donor list view (`/donors/`) with pagination (25 per page) and name/deferral filter
- [x] Patient list view (`/patients/`) with pagination (25 per page) and name/ABO filter
- [x] Blood unit list (`/inventory/units/`) with DID search + pagination (30 per page)
- [x] PDF report export (`/reports/<type>/pdf/`) via ReportLab (BSD licence, free)
  - Utilization, Inventory Age, Donor Stats, TTI Positivity, Haemovigilance reaction reports
  - All 5 report types have PDF export links on the reports page
- [x] Blood group discrepancy investigation workflow (`/patients/<pk>/discrepancy/`)
  - Resolve (clears flag, unblocks electronic crossmatch) or Escalate (keeps block, creates audit)
- [x] MSBOS management UI (`/transfusion/msbos/`) — add, edit, delete schedule entries per branch
- [x] Transfer receive UI (`/inventory/transfers/`) — pending transfers list + accept/reject with audit
- [x] Branch management UI (`/branches/`) — create branches, switch active branch per session
- [x] `reportlab>=4.0` added to `requirements.txt`
- [x] Nav updated: Donors, Patients, MSBOS, Branches, Switch Branch links

## Phase 5 — what's built

- [x] Password change view (`/accounts/password/change/`) — logs out user after change
- [x] User management UI (`/accounts/users/`) — staff-only; list, create, assign/revoke roles, activate/deactivate, unlock accounts
- [x] Audit log viewer (`/audit/`) — staff-only; paginated, filterable by action/actor/table
- [x] Alert management page (`/alerts/`) — list, filter, individual or bulk acknowledge
- [x] PIL (Product Information Leaflet) PDF per unit (`/inventory/units/<did>/pil.pdf`) via ReportLab
  - PIL download button added to unit detail page
- [x] MPI merge workflow (`/patients/<pk>/merge/`) — merge duplicate records; reassigns all clinical data to surviving record, marks source as `merged`
- [x] `raised_at` → `created_at` bug fixed in Alert queries (dashboard + alerts view)
- [x] Nav expanded: Alerts, Users (staff), Audit (staff), Password, Merge / Discrepancy on patient detail

## Phase 6 — what's built

- [x] Cross-site blood request (`/inventory/cross-site-request/`) — FEFO unit selection, auto-initiates Transfer; appears in Pending Transfers for receipt
- [x] `inventory/cross_site.py` — `create_cross_site_request()` with SELECT FOR UPDATE NOWAIT + audit
- [x] Patient traceability report (`/patients/<pk>/traceability/`) — full transfusion history table + PDF export
- [x] `render_patient_traceability_pdf()` added to `core/pdf_reports.py`
- [x] Role management UI (`/accounts/roles/`) — list roles + permissions
- [x] Role create UI (`/accounts/roles/new/`) — assign permissions at creation time
- [x] Permission management UI (`/accounts/permissions/`) — add/list permission codes
- [x] SoD conflict management UI (`/accounts/sod/`) — add/remove separation-of-duties conflicts
- [x] `DEPLOYMENT.md` — full production runbook (Nginx, Gunicorn, PostgreSQL, Vault, systemd, cron, backup, security checklist)

## Phase 7 — what's built

- [x] SoD enforcement wired into `user_detail_view` assign_role action — blocks role assignment if any permission in the role conflicts with user's current permissions; clears permission cache on success
- [x] Donor deferral letter PDF (`/donors/<pk>/deferral-letter.pdf`) — formal A4 letter with letterhead, ref number, reason, deferral period, and safety notice; button shown on donor detail only when deferred
- [x] `.env.example` updated — documents ENCRYPTION_KEY, BLIND_INDEX_KEY, Vault params, session timeouts, and cron setup hint
- [x] Crossmatch form shows compatible units — `new_crossmatch` GET with `?request_id=` pre-loads available units at current branch filtered by ABO/Rh compatibility rules and patient special requirements (leukoreduced, irradiated, CMV-neg, washed); "Select" button autofills the DID field
- [x] ABO compatibility helpers `_compatible_abo_donors()` and `_compatible_rh_donors()` — standard transfusion medicine rules (Rh-neg patients receive Rh-neg only)
- [x] `run_alerts` improved — two new alert types: blood group discrepancy (unresolved discrepancies blocking crossmatch) and donor deferral lapsed (temporarily deferred donors whose date has passed)
- [x] `core/models.py` Alert.TYPES extended with `blood_group_discrepancy` and `donor_deferral_lapsed`
- [x] Bug fix: low inventory check now queries `IssueTransaction.issued_at` instead of non-existent `BloodUnit.issued_at`
- [x] Bug fix: `IssueTransaction.issued_by` (correct field) — was referenced as `issuer` in traceability template and PDF report; fixed in both places
- [x] `render_donor_deferral_letter_pdf()` added to `core/pdf_reports.py`

## Phase 8 — what's built

- [x] `seed_data` command expanded — now also seeds: ComplianceJurisdiction, demo Branch (DEM), RefFacility, 15 Permissions, and 5 default Roles (Donor Technician, Lab Technologist, Blood Bank Officer, Physician, Administrator) with permissions pre-assigned
- [x] `request_detail.html` — each issued unit now shows a "Record Reaction" button; uses correct `issues` context variable (was `issue_transactions`); selects `issued_by` properly
- [x] Crossmatch form improved — shows compatible units table with ABO/Rh, volume, expiry, processing flags; "Select" button autofills DID field
- [x] `issue.html` improved — explains that either a Crossmatch ID or Emergency Release ID is required
- [x] `api/serializers.py` — `AlertSerializer` fixed: `raised_at` → `created_at`
- [x] `base.html` — added `input[type=datetime-local]` to CSS input style rule (needed for reaction form)
- [x] Bug fix: `IssueTransaction` field `issued_by` (not `issuer`) — fixed in `patients/views.py`, `core/pdf_reports.py`, `templates/patients/traceability.html`
- [x] Bug fix: `core/alerts.py` — low inventory demand now queries `IssueTransaction.issued_at`, not non-existent `BloodUnit.issued_at`

## Final architecture summary

```
BloodBank LIS — what is covered:
├── Auth: Argon2id passwords, TOTP MFA, session timeouts, brute-force lockout
├── Donor management: registration, eligibility, adverse events, DID generation, deferral letter PDF
├── Inventory: 15-state machine, Code 128 barcodes, FEFO, component creation, transfers, PIL PDF
├── Patients: pseudonymized PII, blood group history (append-only), antibody tracking, merge
├── Transfusion: crossmatch (IS/AHG/electronic), compatible-unit pre-selection, SoD enforcement
├── Issue: SELECT FOR UPDATE NOWAIT, ABO check, special requirements, dual e-signature
├── Emergency: break-glass release, retrospective crossmatch, physician signoff
├── Haemovigilance: TransfusionReaction, grade-based auto-alerts, recall (recursive CTE)
├── Reports: 5 report types + PDF export (ReportLab), patient traceability PDF, deferral letter
├── Alerts: 7 alert types, run_alerts cron command, ack/bulk-ack UI
├── API: DRF read-only viewsets + compatible unit search + lineage endpoint
├── Audit: hash-chained append-only log, electronic signatures, viewer UI
├── Security: AES-256-GCM field encryption, Vault KMS, blind indexes, SoD enforcement at role assignment
├── Admin UIs: branch, user, role, permission, SoD, MSBOS, alert, audit log
└── Deployment: DEPLOYMENT.md runbook, .env.example
```

## Phase 9 — final quality pass

- [x] `privacy/models.py` — added `display_name` property to `SubjectIdentity` that decrypts `name_enc` on demand with per-instance cache (used in donor list template)
- [x] `donors/views.py` — eligibility view key names aligned with engine (`hb_g_dl`, `days_since_last_donation`, `bp_diastolic`, `pulse`)
- [x] `templates/donors/eligibility.html` — added diastolic BP and pulse fields; corrected hemoglobin field name
- [x] `.env.example` — SESSION_IDLE_TIMEOUT and SESSION_ABSOLUTE_TIMEOUT are in minutes (matching the middleware), not seconds
- [x] `inventory/views.py` — audit log after transfer accept now correctly says `status: 'received'` not `'completed'`
- [x] `api/serializers.py` — `AlertSerializer.fields` fixed: `raised_at` → `created_at`
- [x] All major cross-cutting bugs found and fixed: display_name, issuer→issued_by, raised_at→created_at, icontains→blind_index, BloodUnit.issued_at→IssueTransaction.issued_at

## Setup commands

```bash
pip install -r requirements.txt
python manage.py makemigrations core accounts audit compliance privacy donors inventory patients transfusion api
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_data
python manage.py runserver
```

## Phase 10 — world-class improvements (Session 3, 2026-06-17)

### P4 — Transfusion Administration (Bedside)

- [x] `TransfusionAdministration` model in `transfusion/models.py`
  - Fields: blood_unit, patient, issue (OneToOne), bedside_verify_pass, patient_scan_id, unit_scan_did, admin_staff_1, admin_staff_2, start_at, completed_at, volume_given_ml, outcome (4 choices), vitals_json, branch, notes, esign, created_at
- [x] `transfusion/migrations/0002_transfusion_administration.py` — migration applied
- [x] `TransfusionAdministration` registered in `transfusion/admin.py` (immutable after creation)
- [x] `record_administration` view (`/transfusion/issue/<pk>/administer/`) — captures bedside scans, pre/post vitals, outcome; writes audit log; warns on identity check failure
- [x] `templates/transfusion/record_administration.html` — bedside protocol checklist, scan inputs, vitals grid, outcome selector
- [x] `transfusion/urls.py` — added `issue/<int:issue_pk>/administer/` URL (`record_administration`)
- [x] `templates/transfusion/request_detail.html` — issued units table now shows "Record" button per issue; shows "Recorded" badge + "ID Check Failed" warning badge; colspan updated to 6

### P5 — Enhanced Donor Eligibility Engine

- [x] `compliance/engine.py` — `_HARDCODED_MINIMUMS` list: WHO/AABB minimums (age 18–65, weight ≥50 kg, Hb ≥12.5 g/dL, BP systolic 100–180, BP diastolic 60–100, pulse 60–100, donation interval ≥56 days)
- [x] `_apply_hardcoded_minimums()` — applies minimums when branch has no active ruleset; each failure includes WHO/AABB citation
- [x] `check_donor_eligibility()` — now runs deferral check first (permanent/temporary), then applies ruleset or hardcoded minimums; `failures` list is properly threaded through
- [x] `donors/views.py` — `eligibility_screen` now passes `deferral_status` and `sex` to donor_data; on failure, re-renders form with `failures` context (instead of blind redirect); defers donor only if previously `active`
- [x] `templates/donors/eligibility.html` — failure panel with table showing rule_kind, message, and citation (WHO/AABB standard); shown above the form when failures exist

### P5 — Donor Adverse Event Recording

- [x] `donors/views.py` — `record_adverse_event` view at `/donors/donation/<pk>/adverse-event/`; guards against duplicates (one per donation); creates DonorAdverseEvent; writes audit log
- [x] `donors/urls.py` — added `donation/<int:donation_pk>/adverse-event/` URL
- [x] `templates/donors/record_adverse_event.html` — form with event type, severity, outcome, treatment, checkboxes for LOC/injury/reportable, authority report ref
- [x] `templates/donors/detail.html` — donation history table now has "Record AE" button per donation; shows "Adverse Event" badge if already recorded

### P7.2 — Patient Crossmatch History

- [x] `patients/views.py` — `patient_detail` now fetches last 20 crossmatches via `Crossmatch.objects.filter(request__patient=patient)` and passes `crossmatches` to template
- [x] `templates/patients/detail.html` — new "Crossmatch History" card below blood group history showing: Request #, Unit DID, method, result badge (green/red/yellow), tech name, date

### P7.3 — Inventory Enhanced Filtering

- [x] `inventory/views.py` — `unit_list` gains rh_filter (`rh_d_type`), component_filter (`component_class`), near_expiry (`expiry_datetime__lte` + hours cutoff); passes `component_classes` to template
- [x] `templates/inventory/unit_list.html` — filter bar extended with Rh D dropdown (Pos/Neg/Weak D), Component dropdown (from `component_classes`), Near Expiry dropdown (24h/48h/72h/7 days); pagination links updated to carry all filter params

### P7.4 — Blood Request List View

- [x] `transfusion/views.py` — `request_list` view: branch-filtered, filterable by urgency/outcome/component, paginated 25/page
- [x] `transfusion/urls.py` — added `request/` URL (`request_list`)
- [x] `templates/transfusion/request_list.html` — table with urgency/outcome badges, physician, date, view button; filter bar at top
- [x] `templates/base.html` — "Request List" link added to Clinical dropdown in navbar

### Migration command

```bash
python manage.py migrate transfusion
# (migration 0002_transfusion_administration already applied)
```
