# Blood Bank LIS — World-Class Improvement Plan
> Auto-generated 2026-06-17. Reference: REQUIREMENTS-BEST.md + REQUIREMENTS-EASY.md
> Django/Python stack (NOT PHP as in requirements docs — same logic applies)
> Zero licensing cost. All free/open standards.

---

## CURRENT STATUS (as of 2026-06-18 — Session 7 complete)

### Phases 0–1 COMPLETE ✅
- Patient registry (persistent, append-only blood groups, antibodies, requirements)
- Donor management + donations + TTI testing + reactive lockout
- Blood unit state machine with full transition table
- Pre-transfusion chain: sample validity, crossmatch (IS/AHG/electronic)
- Blood issue: SELECT FOR UPDATE + SoD + e-signature + IssueTransaction
- Emergency release pathway
- Recall/look-back workflow (basic)
- Code 128 label printing
- Audit logging (hash chain)
- Electronic signatures
- Multi-branch support + transfers
- Compliance ruleset engine (skeleton)
- MFA (TOTP)
- Privacy/PII encryption (SubjectIdentity)
- MSBOS
- Hemovigilance (TransfusionReaction)
- KPI reports (basic)

### COMPLETED SESSION 1 (2026-06-17)
- ✅ Patient blood type + Rh recorded at registration (Patient.abo/rh_d fields)
- ✅ Patient.effective_blood_group() fallback for pre-lab declared type
- ✅ Crossmatch UI redesign: patient blood type header with compatible types
- ✅ Lock-unit-for-XM workflow (available → reserved → crossmatch result → crossmatched or back to available)
- ✅ Sample validity check in crossmatch POST (3-day rule)
- ✅ Electronic XM eligibility gates (two-ABO rule, neg screen, no antibodies, unit ABO confirmed)
- ✅ Two-ABO determination rule at issue (transfusion/issue.py)
- ✅ Antibody-antigen compatibility check at issue (_check_antibody_antigen_compatibility)

### COMPLETED SESSION 9 (2026-06-18)
- ✅ Post-Transfusion Outcome (PBM Programme completion — transfusion/models.py, migration 0009)
  - PostTransfusionOutcome model: post-Hb, date, clinical_response, further_transfusion_planned
  - hb_increment() method: computed vs pre-Hb from linked TransfusionGuidelineCheck
  - record_post_outcome view: update_or_create; linked from request_detail "Post-Hb" button
  - pbm_dashboard view: coverage%, compliance%, outcome%, avg Hb increment, trigger distribution bands
  - PBM dashboard template with KPI hero cards + Hb trigger chart + non-compliant/below-expected tables
  - New alerts: pbm_post_hb_gap (>50% of transfused RBC requests lack post-Hb in 14d)
  - Nav: PBM Dashboard under Clinical → Transfusion
- ✅ Directed/Autologous Donation UI (donors/views.py + record_donation.html)
  - record_donation.html: donation_purpose dropdown (allogeneic/autologous/directed) + patient ID field
  - JavaScript toggles recipient field visible for autologous/directed only
  - record_donation view saves donation_purpose + intended_recipient_id from POST
- ✅ Patient Detail Enhancements (patients/views.py + templates/patients/detail.html)
  - patient_detail() now passes antenatal_records (last 5) + tp_history (last 5)
  - Female patients show antenatal / TP side-by-side grid; male patients show TP only if records exist
  - "HDFN Case" button shown for female patients; "BG Card PDF" button for all patients
- ✅ HDFN Case Tracking (patients/models.py, migration 0009)
  - HaemolyticDiseaseCase model: mother/neonate FK, causative antibody, DAT, bilirubin, severity (4 levels)
  - Treatment fields: phototherapy, exchange transfusion, IUT, IVIg
  - SHOT haemovigilance reporting flag; severity helpers (is_severe())
  - hdfn_list, hdfn_create, hdfn_detail views; severity/outcome filters; link-neonate action
  - Templates: hdfn_list.html, hdfn_form.html, hdfn_detail.html
  - Alert: hdfn_unreported — ET cases not reported to SHOT/haemovigilance
  - Nav: HDFN Cases under Clinical → Patients
  - References: BCSH 2014, NICE CG133, BSH HDFN Guidelines 2016
- ✅ Patient Blood Group Card PDF (patients/views.py + core/pdf_reports.py)
  - render_patient_blood_group_card_pdf(): A6 wallet card, ABO/Rh, antibodies, special requirements
  - Shows "Declared" vs "Lab Confirmed" badge; printed date
  - patient_blood_group_card_pdf view + URL /patients/<pk>/bg-card.pdf
  - "BG Card PDF" button on patient_detail.html
- ✅ Transfusion Dose Calculator (/transfusion/tools/dose-calculator/)
  - Weight-based dose calculation for RBC, PLT, FFP, CRYO
  - Neonatal mode (10–20 mL/kg) vs adult mode (unit-based increments)
  - RBC: units needed = (target Hb − pre Hb) / 1.0; PLT: ATD estimate; CRYO: pool estimate from fibrinogen
  - Clinical reference table (AABB/BSH triggers and doses) embedded
  - Nav: Dose Calculator under Clinical → Transfusion

### COMPLETED SESSION 8 (2026-06-18)
- ✅ Lookback Campaign Initiation View (/transfusion/lookback/initiate/)
  - Pathogen window periods: HIV 45d, HCV 70d, HBV 82d, HTLV 51d, Syphilis 30d (configurable override)
  - Auto-identifies prior donations in window period; traces all transfused units to patients
  - Creates LookbackCampaign + LookbackNotification records; SHOT/WHO/MHRA compliant
  - Fixed lookback_list template (broken Django filter calls); fixed branch filter query
- ✅ Therapeutic Phlebotomy Module (patients migration 0008)
  - TherapeuticPhlebotomy model: haemochromatosis, polycythaemia vera, porphyria etc.
  - Pre/post Hb, Haematocrit, ferritin, vitals; disposition (discard/manufacture)
  - tp_list, tp_schedule, tp_detail views + templates; BCSH 2008 guidelines
- ✅ Directed & Autologous Donation (donors migration 0004)
  - donation_purpose field (allogeneic/autologous/directed) + intended_recipient FK
  - Safety interlock in issue.py: _check_directed_autologous() hard-blocks wrong-patient issue
  - Prevents accidental allogeneic transfusion of autologous pre-deposit (SHOT near-miss category)
- ✅ Antenatal Anti-D Programme (patients migration 0008)
  - AntenatalRecord model: EDD, maternal ABO/RhD, partner RhD, RAADP schedule, outcome
  - AntiDProphylaxis model: 9 indications, batch/expiry, Kleihauer-Betke + FMH calculation
  - Auto-computes FMH volume from Kleihauer %; alerts if FMH >4 mL (extra dose needed)
  - antenatal_list, antenatal_create, antenatal_detail views + templates; RCOG/BCSH 2014
  - RAADP overdue banner on list page; postnatal 72h warning on delivery
- ✅ Transfusion Committee Module (quality migration 0007)
  - TransfusionCommittee + CommitteeAction models; ISO 15189:2022 clause 8.8
  - committee_list, committee_create, committee_detail views + templates
  - Meeting minutes recording + e-signature approval; action item tracking; overdue alerts
- ✅ New alert checks: _check_raadp_overdue, _check_lookback_pending, _check_committee_actions_overdue
  - 3 new alert types: raadp_overdue, lookback_pending, committee_action_overdue

### COMPLETED SESSION 7 (2026-06-18)
- ✅ Antigen-Matched Unit Search (/inventory/units/antigen-match/)
  - Finds ABO-compatible units satisfying all required-negative antigens from patient phenotype + antibodies
  - FEFO sort, shows antigen-negative set tags, attributes (LR/Irr/CMV-neg); BCSH 2016 priority algorithm
- ✅ Near-Expiry Unit Management UI (/inventory/near-expiry/)
  - Filter by hours window (24/48/72/168h) and component class; paginated
- ✅ SOP Management Module (quality/models.py, migration 0005)
  - StandardOperatingProcedure + SOPVersion models; 12 categories; e-signature approval
  - Circular FK resolved in migration (3-step: SOP → SOPVersion → AddField active_version)
  - sop_list, sop_create, sop_detail views; ISO 15189:2022 clause 7.4
- ✅ Internal Quality Audit Programme (quality/models.py, migration 0005)
  - InternalAudit + AuditFinding models; add findings, resolve, raise NC from finding
  - internal_audit_list, create, detail views + templates; ISO 15189:2022 clause 8.7
- ✅ Staff Competency Assessment (quality/models.py, migration 0006)
  - StaffCompetency: 11 task categories, 6 methods, 4 outcomes; assessor ≠ assessee enforced
  - competency_list, competency_record views + templates; ISO 15189:2022 clause 6.2
- ✅ Quality Indicators Report (/core/reports/quality-indicators/)
  - 8 QI metrics: Wastage%, C:T ratio, Reaction rate/1000, TAT compliance, Near-expiry%, QC pass rate, NC backlog, SHOT events
  - ISO 15189:2022 clause 8.6 + AABB QI programme; period selector; colour-coded targets
- ✅ New alert checks: _check_sop_reviews, _check_competency_overdue, _check_nc_backlog
  - 3 new alert types added to Alert.TYPES

### COMPLETED SESSION 6 (2026-06-18)
- ✅ PatientPhenotype model (patients/models.py, migration 0007)
  - 17-antigen panel: Rh C/c/E/e, Kell K/k, Duffy Fya/Fyb, Kidd Jka/Jkb, MNS M/N/S/s, Lewis Lea/Leb, P1PK P1
  - OneToOne to Patient, mirrors DonorPhenotype structure
  - antigen_present_set(), antigen_absent_set(), required_negative_antigens() methods
  - record_patient_phenotype view + withdraw_consent view
  - Templates: record_phenotype.html, withdraw_consent.html
  - Patient detail: phenotype banner + "Record Phenotype" CTA; "Withdraw" link on active consent
  - BCSH 2016 extended phenotyping workflow before chronic transfusion
- ✅ NonConformance + CorrectiveAction models (quality/models.py, migration 0003)
  - 11 NC types, 5 severity levels, 5 status states
  - CAPA state machine: open → under_review → capa_open → capa_verify → closed
  - NC auto-numbering: NC-{year}-{count+1:04d}
  - nc_list, nc_create, nc_detail views + templates
  - Dashboard: open NC alert banner + nav link
  - ISO 15189:2022 clause 7.7 / AABB Standards 5.1.6 compliant
- ✅ Bedside PWA — /transfusion/bedside/
  - static/sw.js Service Worker (network-first API, cache-first static)
  - static/manifest.json Web App Manifest (start_url /bedside/)
  - BedsideVerifyView POST /api/v1/bedside/verify/ — patient UID + unit DID verification
  - ABO compatibility check embedded in response
  - Standalone bedside_pwa.html (no base.html) with ZXing-JS barcode scanner
  - bedside_pwa view injects user's API token; redirects /bedside/ → /transfusion/bedside/
  - PASS/STOP result display; offline badge; all 3 checks listed
  - Nav link: Bedside Verify (PWA) in Transfusion dropdown
- ✅ Donor Retention Campaigns (donors/models.py, migration 0003)
  - RetentionCampaign model: segment, channel, message_template, goals, status lifecycle
  - CampaignEnrollment model: status lifecycle (enrolled → contacted → responded → donated)
  - campaign_list, campaign_create, campaign_detail views
  - Auto-enroll matching lapsed donors by segment (lapsed 3/6/12m, new-never-returned, high-value)
  - Per-enrollment status update inline; KPI cards: response rate, conversion rate, goal progress bar
  - Templates: campaign_list.html, campaign_form.html, campaign_detail.html
  - Nav link: Retention Campaigns in Donors dropdown
  - Also fixed bug: lapsed_donors view used donation_date instead of donated_at
- ✅ New Lot Validation workflow (quality/models.py, migration 0004)
  - NewLotValidation model: pending → in_review → approved/rejected
  - LotValidationResult model: parallel testing with grade comparison (new ≥ reference = pass)
  - lot_validation_list, lot_validation_create, lot_validation_detail views
  - E-signature required for approval; releases lot to in_use
  - Auto-creates NonConformance on rejection
  - Templates: lot_validation_list.html, lot_validation_form.html, lot_validation_detail.html
  - Nav link: New Lot Validation in Quality dropdown
  - AABB/ISO 15189 new-lot parallel testing compliance

### COMPLETED SESSION 5 (2026-06-18)
- ✅ TAT (Turnaround Time) Report — core/reports.py turnaround_time_report(); AABB-compliant
  - Req→XM and total TAT broken down by urgency (routine/urgent/emergency)
  - Avg, median, P90 per urgency level; target thresholds (routine ≤60 min, urgent ≤30, emergency ≤10)
  - View + template at /core/reports/tat/; nav link added
- ✅ BloodGroupDiscrepancyInvestigation model (patients/models.py, migration 0006)
  - Root cause choices (clerical, technical, WBIT, post-HSCT, recent transfusion, genuine change)
  - Investigation status: open / resolved / escalated
  - SHOT reportable + WBIT event flags
  - Confirmed group FK once investigation complete
  - investigate_discrepancy view upgraded to create/update proper investigation records
  - discrepancy_investigation_list view + template + URL at /patients/discrepancies/
  - Open investigations shown as dashboard alert banner
  - Discrepancy Investigations link in nav
- ✅ irradiate_unit view (inventory/views.py) + template + URL
  - Dose validation: 25–50 Gy (BCSH minimum/maximum)
  - Dosimetry card confirmation checkbox
  - Creates ProcessingEvent(type='irradiation') + ElectronicSignature
  - RBC expiry reduced to 14 days post-irradiation (BCSH rule)
  - Irradiate button on unit_detail.html (only shown for non-irradiated available/quarantined/reserved units)
- ✅ Reagent low-stock alert (dashboard)
  - minimum_lots field added to Reagent model (migration 0002)
  - Dashboard checks all active reagents' in_use+quarantined lot count vs minimum_lots
  - Red alert banner when any reagent below threshold
- ✅ Bug fix: transfusion/issue.py — blood_request fetched before _check_neonatal_requirements() call

### COMPLETED SESSION 4 (2026-06-18)
- ✅ Migration conflict fixed: 0004_donation_blood_grouping superseded by 0005; no-op stub left
- ✅ NeonatalTransfusionOrder model + migration 0006 + create/detail views + templates
  - AABB/BSH neonatal requirements (irradiated, CMV-neg, leukoreduced)
  - Weight-based max volume: 15 mL/kg top-up, 160 mL/kg exchange
  - unit_eligible() checks all neonatal requirements with reasons
  - Neonatal button added to request_detail; is_neonatal flag on new_blood_request form
- ✅ MTPActivation model + migration 0007 + activate/detail/list views + templates
  - Massive Transfusion Protocol tracking (trigger, activated_at, stand_down, completion)
  - O-neg RBC pre-allocation check at activation
  - Retrospective crossmatch mandatory field
  - Haemovigilance reporting flag
  - MTP Log + Activate MTP in navbar
- ✅ Haemovigilance Dashboard at /transfusion/haemovigilance/
  - Reaction rate per 1000 transfusions KPI
  - By-type and by-severity bar charts
  - Unreported serious reaction alerts
  - Filterable by period (30/90/180/365d), type, severity
  - Paginated reaction log
- ✅ run_alerts: added _check_ungrouped_units() — alerts when quarantined units >24h without ABO typing
- ✅ Shortage prediction: check_shortages management command using Holt-Winters forecast
  - Raises forecast_shortage alerts when projected stock falls below 1.5 days safety level
- ✅ Donor engagement: donor_engagement management command
  - Lapsed donors detection (>6 months)
  - Auto-clears expired temporary deferrals
  - Reports pending milestone certificates
  - Daily eligible pool count per branch
- ✅ Donor Blood Group Card PDF (render_donor_blood_group_card_pdf, A6 wallet card)
  - Button added to donor detail page (only shown if ABO confirmed)
- ✅ core/templatetags/bloodbank_tags.py — getattr, mul, div, pct, abs filters
  - Fixes phenotype_form.html TemplateSyntaxError (missing getattr filter)
- ✅ Alert model: added ungrouped_units, forecast_shortage, sensor_offline, calibration_overdue, ongoing_excursion types
- ✅ seed_data: added reagent.manage, mtp.activate, neonatal.manage permissions + role assignments
- ✅ DEPLOYMENT.md: updated cron table with all 4 management commands
- ✅ Navbar: Haemovigilance, MTP Log, Activate MTP, Donor Milestones links added

### COMPLETED SESSION 3 (2026-06-17 continued)
- ✅ Cold chain app: StorageEquipment, TemperatureLog, SensorHealth, TemperatureExcursion, ExcursionUnitLink, EquipmentAlarm, UnitReturnCheck, ShipmentColdChain, ComponentStorageSpec
- ✅ Temperature ingest API: POST /api/v1/temperature/ (idempotent, auto-excursion detection, auto-quarantine)
- ✅ Cold chain alerts in run_alerts: sensor offline, calibration overdue, ongoing excursion
- ✅ BloodUnit.storage_equipment FK (migration 0004)
- ✅ Analytics app: DemandFactDaily, Forecast, KpiDaily models
- ✅ Holt-Winters additive forecasting engine (pure Python, no paid libraries)
- ✅ build_daily_facts management command (nightly; --all-history, --optimise flags)
- ✅ Analytics dashboard at /analytics/ with KPIs, wastage, forecasts, 30-day trend
- ✅ FHIR R4 facade: /fhir/metadata, /fhir/Patient/{id}, /fhir/BiologicallyDerivedProduct/{did}, /fhir/AuditEvent
- ✅ Dashboard complete overhaul: hero section, metrics row, blood group grid, quick actions, recent transfusions
- ✅ Navbar complete redesign: grouped dropdowns (Clinical, Blood Bank, Insights, Admin), Settings user menu
- ✅ Test suite: tests/test_compatibility.py, test_forecasting.py, test_coldchain.py

---

## PRIORITY IMPLEMENTATION QUEUE

### P1 — Patient Safety Critical (do first)

#### P1.1 — Two-ABO Determination Rule (REQ-X03)
**File:** `transfusion/issue.py`
**What:** Block group-specific issue if patient has < 2 concordant ABO determinations on file.
- Check `patient.blood_groups.filter(is_discrepant=False).count() < 2`
- Block in `issue_unit()` if patient does not have 2 independent ABO results
- Allow O-neg emergency override with physician e-sign

#### P1.2 — Sample Validity Enforcement in Crossmatch (REQ-X02)
**File:** `transfusion/views.py` `new_crossmatch`
**What:** Check `sample.is_valid()` before allowing crossmatch POST.
- Currently is_valid() exists but not checked in crossmatch view
- Add check: if not sample.is_valid() → error "Sample expired (3-day rule)"

#### P1.3 — Antibody-Driven Unit Blocking at Issue (REQ-P05 + Safety Guard)
**File:** `transfusion/issue.py`
**What:** At issue time, verify unit's antigen_negative_set satisfies ALL active patient antibodies.
- Currently only snapshot is checked; add real-time antibody check at issue

#### P1.4 — Electronic Crossmatch Eligibility Gates (REQ-X05)
**File:** `transfusion/views.py`
**What:** When method='electronic', auto-check all gates:
1. ≥2 concordant ABO/Rh results on file
2. Current antibody screen = negative
3. No clinical antibody history
4. Unit ABO confirmed
If any gate fails → error "Electronic XM not eligible, use AHG"

---

### P2 — Cold Chain Infrastructure (REQ-CC-01 to CC-07)

#### P2.1 — Storage Equipment Models
**New models in:** `core/models.py` or new `coldchain/` app
```python
StorageEquipment(name, type, sensor_id, branch, component_class_allowed, calibration_due, status)
TemperatureLog(equipment, recorded_at, temp_c, humidity_pct, agitation_ok, source, reading_uuid)
SensorHealth(sensor_id, equipment, last_seen_at, expected_interval_sec, status)
TemperatureExcursion(equipment, started_at, ended_at, max_temp_c, auto_quarantine, disposition, disposition_by, esign)
ExcursionUnitLink(excursion, blood_unit, auto_quarantined)
EquipmentAlarm(equipment, alarm_type, triggered_at, cleared_at, ack_by, escalation_level)
UnitReturnCheck(blood_unit, issue, issued_at, returned_at, minutes_out, measured_return_temp_c, rule_applied, decision)
ShipmentColdChain(transfer, logger_id, origin_branch, destination_branch, departed_at, arrived_at, logger_data_json, excursion_detected)
```

#### P2.2 — Temperature Ingestion API
**New endpoint:** `POST /api/v1/temperature/` (sensor sends readings)
- Validate reading_uuid (idempotency)
- Compare against component_storage_spec
- If out of range: create TemperatureExcursion, quarantine units in equipment

#### P2.3 — Background Worker (management command → daemon)
**File:** `core/management/commands/run_alerts.py` → enhance
- Extend to: check sensor heartbeats, escalate alarms, near-expiry flagging
- Run with: `python manage.py run_alerts` via Supervisord

---

### P3 — Analytics & Forecasting (REQ-ANL-01 to ANL-07)

#### P3.1 — Demand Fact Daily
**New model:** `analytics/models.py`
```python
DemandFactDaily(fact_date, branch, component_class, abo, rh, units_issued, units_requested, units_expired, units_wasted, stock_at_eod)
```
**Management command:** `python manage.py build_daily_facts`

#### P3.2 — Forecasting Engine (Holt-Winters Additive)
**New:** `analytics/forecasting.py`
- SimpleMovingAverage (7/14/28 day)
- SimpleExponentialSmoothing
- HoltWintersAdditive (weekly seasonality)
- Auto-select by MASE on rolling holdout
- Safety stock = forecast + Z × σ

#### P3.3 — KPI Dashboard
**Enhance:** `core/reports.py` and `templates/core/reports.html`
- Wastage %, C:T ratio, days of supply, near-expiry units, stock-out events, avg TAT
- Configurable per branch, date range selectable

#### P3.4 — Near-Expiry Alerts
**File:** background worker
- Query units with expiry within config_targets.near_expiry_alert_hours
- Create Alert records for each
- Dashboard shows "X units expiring in <72h"

---

### P4 — Transfusion Administration & Bedside (REQ-I05, REQ-I06)

#### P4.1 — Transfusion Administration Model
**New model:** `transfusion/models.py`
```python
TransfusionAdministration(blood_unit, patient, issue, bedside_verify_pass, patient_scan_id, unit_scan_did, admin_staff_1, admin_staff_2, start_at, completed_at, volume_given_ml, outcome, vitals_json, branch)
```

#### P4.2 — Bedside Verification View
**New view:** `transfusion/views_bedside.py`
- Scan patient wristband + unit DID
- Confirm match
- Two-person confirmation
- Create TransfusionAdministration

#### P4.3 — Bedside PWA
- Simple HTML page with ZXing-JS barcode scanner
- Works offline (Service Worker)
- Syncs back when connected

---

### P5 — Donor Eligibility Engine (REQ-D02)

#### P5.1 — Full Eligibility Evaluation at Donation
**File:** `donors/views.py` / `compliance/engine.py`
- Evaluate all compliance rules against donor at donation time
- Rules: age, weight, Hb, BP, pulse, donation interval, deferral status
- Show pass/fail with rule citation
- Block donation if any fail (unless medical director override)

#### P5.2 — Donor Adverse Events Model
**New model:** `donors/models.py`
```python
DonorAdverseEvent(donation, donor, event_type, severity, loss_of_consciousness, injury, treatment, outcome, reportable, report_ref, recorded_by)
```

---

### P6 — HL7 / FHIR Interoperability (REQ-IO-01 to IO-09)

#### P6.1 — FHIR R4 Facade (Basic)
**New:** `api/fhir.py`
- GET /fhir/Patient/{id}
- GET /fhir/BiologicallyDerivedProduct/{did}
- GET /fhir/AuditEvent (audit log export)
- GET /fhir/metadata (CapabilityStatement)

#### P6.2 — HL7 Integration Points
- Document the Mirth Connect channel mappings
- ADT^A01 → patient registration
- OML^O21 → blood request
- ORU^R01 → test results out

---

### P7 — UI/UX Improvements

#### P7.1 — Dashboard Enhancement
- Real-time inventory levels by ABO/Rh/component
- Near-expiry panel
- Pending crossmatches
- Active alarms

#### P7.2 — Patient Detail — Show Crossmatch History
- Link patient to all their crossmatches across requests

#### P7.3 — Inventory List — Better Filtering
- Filter by: ABO, Rh, component class, status, near-expiry
- Sortable columns

#### P7.4 — Request Detail — Show Compatible Units
- "New Crossmatch" button on request detail should prefill with compatible units

---

## WHAT TO IMPLEMENT NEXT (Session continuation order)

1. **P1.2** — Sample validity check in crossmatch POST (30 min)
2. **P1.4** — Electronic XM eligibility gates (1 hr)
3. **P2.1** — Cold chain models (StorageEquipment, TemperatureLog, etc.) (2 hrs)
4. **P3.4** — Near-expiry alerts (background worker enhancement) (1 hr)
5. **P4.1** — TransfusionAdministration model + view (1.5 hrs)
6. **P3.1+P3.2** — Analytics + forecasting (3 hrs)
7. **P5.1** — Donor eligibility evaluation (2 hrs)
8. **P6.1** — FHIR R4 basic facade (2 hrs)

---

## FILE MAP (key files to know)

| File | Purpose |
|------|---------|
| `patients/models.py` | Patient, PatientBloodGroup, PatientAntibody, PatientTransfusionRequirement |
| `patients/views.py` | Patient registration, blood group, antibody, requirement |
| `patients/migrations/0003_*.py` | Patient abo/rh_d migration (new) |
| `donors/models.py` | Donor, Donation |
| `inventory/models.py` | BloodUnit, ComponentType, ProcessingEvent, UnitLineage |
| `inventory/state_machine.py` | transition_unit(), can_transition(), seed_transitions() |
| `transfusion/models.py` | Sample, Crossmatch, BloodRequest, IssueTransaction, EmergencyRelease |
| `transfusion/views.py` | new_crossmatch, lock_unit_for_xm, unlock_unit_for_xm, issue_unit_view |
| `transfusion/issue.py` | issue_unit() — transactional issue logic |
| `transfusion/urls.py` | crossmatch/lock/, crossmatch/unlock/ (new) |
| `audit/models.py` + `audit/utils.py` | ElectronicSignature, write_audit, create_signature |
| `accounts/permissions.py` | has_permission() |
| `compliance/engine.py` | Rule evaluation |
| `core/management/commands/run_alerts.py` | Background worker |
| `templates/transfusion/crossmatch.html` | Redesigned crossmatch UI (new) |
| `templates/patients/register.html` | Patient registration with blood type (new) |
| `IMPROVEMENT_PLAN.md` | This file |
