# Revised Plan — Region-Agnostic Blood Bank Management System

*Synthesis of 8 deep-research lanes (clinical workflow, compliance, interoperability, data model & state machines, concurrency/sync, cold chain & hemovigilance, forecasting, security & privacy). Where lanes were uncertain or relied on standards-knowledge rather than live verification, this is flagged inline. Note: all 8 lanes reported that live web verification was blocked by a classifier outage; clause numbers and threshold figures (3-day sample validity, 28-day post-irradiation dating, 30y/10y retention, Part 11 sub-sections) are drawn from stable standards knowledge and MUST be re-verified against primary text before any contractual or regulatory claim.*

> **Project constraint (2026-06-15):** This is a portfolio/learning project with zero licensing budget. No ICCBBA registration, no licensed ISBT 128 code tables, no paid standards documents. The system follows all international clinical and technical standards as closely as possible using only free/open materials. Blood moves domestically only — no international scope. See §3.4 and §7.2 for the labeling approach that replaces ISBT 128.

---

## 1. Executive Verdict

**The original plan — a single-silo PHP/MySQL/AJAX app keyed on ABO/Rh static lookup, free-text patient names, generic QR codes, "reservation intent" locking, and offline multi-branch sync — is NOT sellable to an accredited hospital as-is.** It is a defensible *foundation* for the domain/inventory core, but four assumptions are disqualifying and three are unsafe. The gap between "works in a demo" and "a hospital will buy it" is not features — it is **patient-safety gating, validated identity, tamper-evident records, transactional concurrency, and standards-based interoperability**. None of these are optional at the sellable bar.

The 6 changes that must happen (in priority order):

1. **Replace ABO/Rh static lookup as the sole issue arbiter.** Issue must be gated by a real pretransfusion chain: Type & Screen with a sample-validity window, two independent ABO determinations (wrong-blood-in-tube defense), antibody screen, a typed crossmatch (immediate-spin / AHG / electronic), and special-attribute matching. A lookup table alone misses clinically significant alloantibodies and *will* cause a hemolytic reaction. (Lanes 1, 4)

2. **Make the recipient a first-class persistent entity with a lifelong antibody/special-requirements history.** Free-text `patient_name` must become a patient registry keyed on a stable master patient index, carrying append-only blood-group and alloantibody history that follows the patient across visits and branches. An evanesced anti-K that is invisible on today's screen must still force antigen-negative units for life. (Lanes 1, 4)

3. **Drop generic QR; adopt a proper machine-readable barcode scheme.** For this project: custom Donation ID (DID) encoded in Code 128 or Codabar (both free, open, and supported by all blood bank scanners). ISBT 128 would be the commercial-grade standard but requires ICCBBA licensing — deferred. Custom product catalog replaces ISBT 128 Product Description Codes. QR is still ruled out: no field grammar for blood data, not parseable by lab scanners, not interoperable with any LIS. (Lanes 2, 3, 4)

4. **Re-scope "offline multi-branch sync."** Single-issuance of one physical bag is a strong-consistency (CP) invariant; full offline writes to *shared* inventory is a CAP-theorem wall — you cannot un-transfuse blood. Re-scope to **single authoritative central DB + exclusive per-unit branch ownership**, where an offline branch may only act on units it already solely owns. Last-write-wins on unit lifecycle is banned. (Lane 5)

5. **Engineer tamper-evidence, e-signatures, transactional locking, and trusted time — these do not come free with LAMP.** Append-only hash-chained audit with externally anchored chain head; 21 CFR Part 11 signatures cryptographically bound to record content; `SELECT … FOR UPDATE` row locking inside transactions to prevent double-issue; server-authoritative UTC time. (Lanes 2, 4, 5, 8)

6. **Treat compliance as data, not code.** Eligibility/deferral/test-panel/retention/labeling rules must be versioned configuration rows evaluated by a generic rule engine, so selling into a new country = loading a ruleset, not editing PHP. Safety-critical invariants (reactive lockout, quarantine-until-tested, expiry, ABO compatibility) remain hardcoded guards the config can only *tighten*. (Lane 2)

And one meta-point the buyer's auditor will demand: **the product is the software PLUS a validation/documentation package** (IQ/OQ/PQ, traceability matrix, change control, DPIA, SOPs). No amount of code makes the product "Part 11 certified" in the abstract — that is the customer's facility-level obligation, and marketing it as pre-certified is a liability. (Lanes 2, 8)

---

## 2. Critical Safety Gaps to Close

Synthesized and deduplicated across lanes. Each line: the gap → *why a hospital rejects without it.*

- **Pretransfusion safety chain (T&S + antibody screen + crossmatch), not ABO/Rh lookup** — *issuing on lookup alone misses alloantibodies and causes acute/delayed hemolytic reactions; this is a fatal patient-safety and accreditation failure.* (L1, L4)
- **Two independent ABO determinations before group-specific issue** — *single-determination issue cannot catch wrong-blood-in-tube, the dominant cause of fatal ABO-incompatible transfusion.* (L1, L4)
- **Persistent lifelong patient antibody history driving antigen-negative selection** — *an evanesced-but-clinically-significant antibody invisible on the current screen will cause a delayed hemolytic reaction if units aren't antigen-negative.* (L1, L4)
- **Special attributes (irradiated / CMV-neg / washed / leukoreduced / antigen-neg) as clinically-gated unit properties enforced at issue** — *transfusing non-irradiated cellular product to an at-risk patient causes fatal TA-GVHD; the issue engine must hard-block non-conforming units.* (L1, L4)
- **Formal unit state machine with DB-enforced guards (quarantined/expired/recalled/reserved-to-other cannot be issued)** — *a PHP-only guard is bypassed by any bug; expired or quarantined units must be unissuable at the database layer.* (L4, L5)
- **Reactive-result lockout + quarantine-until-tested as universal invariants** — *releasing an untested or reactive unit transmits HIV/HBV/HCV/syphilis; this is the bright-line regulatory red line.* (L2, L6)
- **Single-issuance guarantee via transactional row locking** — *naive read-then-write or AJAX optimism double-issues one physical bag to two patients under load.* (L5)
- **Vein-to-vein bidirectional traceability + look-back/recall workflow** — *a donor who later seroconverts requires tracing every prior component to every recipient; without lineage + recipient identity this is impossible and the buyer fails EU/FDA traceability.* (L1, L2, L4)
- **Cold-chain excursion auto-quarantine + sensor-disconnect detection via background worker** — *a request-driven app cannot detect a sensor that stops reporting (the dangerous failure); units stored through an undetected excursion get transfused.* (L6)
- **Emergency uncrossmatched O-neg release with mandatory retrospective workflow** — *without a safe, audited emergency pathway staff bypass the system entirely in a trauma, or the system blocks life-saving release.* (L1)
- **Bedside two-person/barcode patient+unit verification** — *mis-transfusion at the bedside is a dominant fatal error; closed-loop scan is the single highest-value safety control and depends on ISBT 128, not QR.* (L1, L3)
- **Immutable, tamper-evident audit of every disposition + e-signature on release** — *a mutable audit table means a release decision can be silently rewritten; auditors reject this outright.* (L2, L4, L8)

---

## 3. Revised Data Model

Presented as **additions/alterations to the existing 6.x schema**, not a rewrite. Existing tables referenced: `blood_units`, `donations`, `donors`, `blood_requests`, `issue_transactions`, `audit_logs`, `users`, `branches`, `compatibility_rules`, `temperature_range` (static), `transfers`, `alerts`.

### 3.1 Patient registry & longitudinal history (replaces `blood_requests.patient_name`)
- **`patients`** — `patient_id PK, mpi_uid UNIQUE, given_name, family_name, sex, dob, national_id_hash, merged_into_patient_id (self-FK, never hard-delete), record_status(active/merged/blocked)`.
- **`patient_identifiers`** — `patient_id FK, system, value, is_primary, UNIQUE(system,value)` (cross-branch MRN/national-id reconciliation → one patient).
- **`patient_blood_groups`** (append-only) — `patient_id FK, abo, rh_d, method, sample_id FK, determined_by/verified_by FK users, source(current/historical/external), is_discrepant, supersedes_id`. Expose latest-confirmed via a VIEW, never a stored column. Trigger blocks electronic crossmatch on ABO discrepancy.
- **`patient_antibodies`** (lifelong) — `patient_id FK, specificity (anti-K, anti-Jka…), antigen_system, clinical_significance, status(identified/historical_only/ruled_out), evanescent, first_identified_at/branch, sample_id FK`. Drives antigen-negative filtering regardless of current screen.
- **`patient_special_requirements` / `patient_transfusion_requirements`** — `patient_id FK, requirement(irradiated/cmv_neg/washed/antigen_neg/phenotype_matched), antigen_spec, active, reason, set_by FK`. (Lanes 1 and 4 propose near-identical tables — **merge into one**.)
- `ALTER blood_requests`: drop `patient_name`; add `patient_id FK`, `urgency(routine/urgent/emergency_MTP)`, `requested_ts, crossmatch_started_ts, crossmatch_completed_ts, issued_ts`, `units_requested/crossmatched/transfused`, `outcome(fulfilled/partial/unmet/cancelled)`, `requesting_ward_id, requesting_physician_id` (the latter for TAT and C:T ratio).

### 3.2 Pretransfusion testing & crossmatch
- **`samples` / `patient_pretransfusion_sample`** — `id, patient_id NULL, donor_id NULL, collected_at, collected_by FK, sample_type, accession_number UNIQUE, validity_expiry` (3-day rule when transfused/pregnant in prior 3 months), `abo_confirmation_status`.
- **`antibody_screen`** — `sample_id FK, method(IAT/PEG/LISS/gel), screen_cell_lot, per-cell results, overall_result, tech_id, datetime`.
- **`antibody_identification`** — `sample_id FK, panel_lot, identified_specificities[]`. Positive results write into `patient_antibodies`.
- **`crossmatches`** — `id, sample_id FK, blood_unit_id FK, request_id FK, method(immediate_spin/AHG/electronic), result(compatible/incompatible/electronic_release), reagent_lot, tech_id, datetime, electronic_eligibility_snapshot`. Electronic-XM gates (two concordant ABO/Rh, current screen neg + no antibody history, validated alerting, donor ABO confirmed) enforced server-side; failure downgrades to AHG.
- **`emergency_release`** — `request_id, patient_id, units[], physician_id, justification, release_datetime, retrospective_xm_status, signoff_status, signoff_physician_id`.
- **`msbos`** — `procedure_code, branch_id NULL, order_type(none/T&S/XM), units_count` (drives request defaults + C:T ratio).

### 3.3 Component lineage & processing (DAG)
- **`processing_events`** — `id, event_type(separation/split/irradiation/leukoreduction/pooling/wash/aliquot/thaw/pathogen_reduction), performed_at, performed_by FK, branch_id, sop_version, esign_id FK`.
- **`unit_lineage`** — `processing_event_id FK, parent_unit_id NULL FK, parent_donation_id NULL FK, child_unit_id FK, relationship(derived_from/split_from/pooled_into/aliquot_of)`. Recursive CTE → ancestor/descendant set for look-back and recall.
- `ALTER blood_units`: add `parent_donation_id FK`, `production_event_id FK`, `component_class(RBC/FFP/PLT/CRYO/WB/GRAN)`; special-attribute columns `leukoreduced, irradiated, irradiation_datetime, cmv_negative, washed, deglycerolized, antigen_negative_set`; **recompute expiry event-driven** on irradiation (28d) and deglycerolization (24h), not a fixed field.

### 3.4 Custom labeling & unit identity (replaces ISBT 128 — no licensing)

> **Decision (2026-06-15):** ISBT 128 requires ICCBBA registration + licensed code tables (recurring cost). Since this project is domestic-only with no licensing budget, we use a custom Donation ID (DID) scheme encoded in Code 128 barcode (ISO/IEC 15417, free/open). All clinical safety logic, state machines, and traceability are unchanged — only the identifier format and label encoding differ. If this later becomes a commercial product for an accredited site, the DID column can be aliased and ISBT 128 layered on top.

**Custom DID format:**
```
[FACILITY 3 chars][YEAR 2 digits][SERIAL 6 digits][CHECK 1 char]
= 12 chars total
```
Check character computed by ISO 7064 MOD 11-2 (free algorithm, same family used by ISBN-10/IBAN).

- `ALTER blood_units`: add `did CHAR(12) UNIQUE NOT NULL` (immutable, replaces any QR/generic ID), `did_check_char CHAR(1)`, `division_suffix CHAR(2)` (for split/aliquot), `collection_datetime`, `expiry_datetime` (time-precise for platelets/short-dated components).
- **`component_types`** (internal catalog, owned by us): `code CHAR(6), name, component_class (RBC/FFP/PLT/CRYO/WB/GRAN), attributes_json (leukoreduced, irradiated, washed, cmv_negative, antigen_negative_set, additive_solution)`. No external license — we define the codes.
- **`ref_facilities`** (internal): `facility_code CHAR(3), name, branch_id FK` — ensures DID uniqueness within deployment.
- **`label_templates` + `label_print_log`** — template version, DID, barcode symbology (Code 128 / optionally Codabar), image checksums, printed_by/at.
- Barcode symbology: **Code 128** (free, ISO/IEC 15417) as primary; **Codabar/NW-7** as fallback option (free, historically used in blood banking, all blood bank scanners support it). **No QR** — QR is not parseable by blood bank scanners and has no standard field grammar for blood data.
- Labeling profile config (`labeling_profile.standard`): `CUSTOM_CODE128` | `CODABAR` (both free). Field `iccbba_fin` left nullable for future ISBT 128 upgrade path.

### 3.5 Unit state machine
- `ALTER blood_units.status` → formal ENUM: `quarantined(default), in_testing, available, failed_qc, reserved, crossmatched, issued, transfused, returned_to_stock, wasted, expired, recalled, quarantined_holdback, transferred_out, in_transit, destroyed`. Plus concurrency fields: `version INT, owner_branch_id, reserved_by_user_id, reserved_for_request_id, reserved_until, crossmatch_hold_until, current_equipment_id`.
- **`unit_state_transitions`** — `from_status, to_status, requires_role, guard_rule` (consulted by app AND BEFORE-UPDATE trigger using `SIGNAL SQLSTATE '45000'`).
- **`unit_status_events`** (append-only, authoritative) — `unit_id FK, from_status, to_status, reason, actor FK, esign_id FK, occurred_at`. Current status denormalized for query speed but event log is source of truth.

### 3.6 Cold chain & hemovigilance
- **`component_storage_spec`** (replaces static `temperature_range`) — per `component_class`: target/transport min-max °C, `requires_agitation`, `agitation_max_interruption_min`, `frozen_threshold_c`, `shelf_life_hours`, `max_temp_excursion_min`, `source_standard`. All values configurable.
- **`storage_equipment`** — fridge/platelet-agitator/freezer/ULT/transport-cooler/validated-shipper; `sensor_id, calibration_due, component_class_allowed, status`.
- **`temperature_log`** (high-volume time-series; partition/archive monthly) — `equipment_id, recorded_at UTC, temp_c, humidity, agitation_ok, source(sensor/manual), reading_uuid, ingest_received_at`.
- **`sensor_health`** — `last_seen_at` heartbeat for disconnect detection by background worker.
- **`temperature_excursion`** + **`excursion_unit_link`** — auto-create on breach, auto-set affected units `quarantined`; disposition (return/quarantine/discard) restricted to medical-director role with justification.
- **`equipment_alarm`** — `alarm_type(high/low_temp/agitation_failure/power_loss/door_open/sensor_disconnect/calibration_overdue/battery_low), triggered/cleared, ack, escalation_level`.
- **`unit_return_check`** — `issued_at, returned_at, minutes_out, measured_return_temp_c, rule_applied(30min/validated-temp), decision`.
- **`transfusion_reaction`** + **`reaction_unit_link`** — recipient events: category (AHTR/DHTR/FNHTR/allergic/anaphylactic/TACO/TRALI/TAD/TA-GVHD/PTP/sepsis/TTI/hypotensive), `time_class, severity_grade, imputability, signs_symptoms JSON, lab_results(DAT…), reportable_to_authority, report_ref`.
- **`donor_adverse_event`** — VVR/syncope/hematoma/nerve-injury/citrate-reaction; severity, LOC/injury flags, outcome, reportable.
- **Shared vocabularies:** `hv_severity_grade (0–4/death)`, `hv_imputability (definite/probable/possible/unlikely/excluded/not_assessable)`.
- **`discard_reason`** (coded taxonomy) + **`unit_disposal`** + **`biohazard_disposal_batch`** (chain-of-custody, manifest, witness).
- **`shipment_cold_chain`** — transport-leg temps, embedded logger data, excursion flag.

### 3.7 Recall / look-back
- **`recalls`** — `trigger(donor_seroconversion/positive_repeat_test/recipient_reaction/equipment_failure/recall_notice), trigger_donor_id, marker, status`.
- **`recall_items`** — `recall_id FK, blood_unit_id FK, role(implicated/co_component/recipient_traced), disposition, recipient_patient_id FK`.

### 3.8 Compliance configuration (data-driven rule engine)
- **`compliance_jurisdiction`**, **`compliance_ruleset`** (versioned, effective_from/to, immutable-once-active), **`compliance_rule`** (rule_kind AGE/WEIGHT/HB/BP/DONATION_INTERVAL/DEFERRAL/REQUIRED_TEST…, operator, thresholds, applies_to predicate, citation).
- **`test_definition`** (configurable mandatory TTI panel: HIV/HBsAg/anti-HCV/syphilis minimum + jurisdiction add-ons), **`donation_test_result`** (gates `blood_units` releasability).
- **`retention_policy`** (record_class, retention_years, indefinite_flag; default strictest 30y traceability), **`labeling_profile`** (ISBT128/Codabar/custom).
- **`disposition_decision`** (records which `ruleset_version_id` governed each action). Bind each **branch** to its own jurisdiction+ruleset (one install may span jurisdictions).
- **`validation_artifact`** (IQ/OQ/PQ/VMP/trace_matrix/change_record per deployment).

### 3.9 Immutable audit, e-signatures, security
- **`audit_logs` REDESIGN** — add `seq, occurred_at_utc DATETIME(6), actor_user_id, action, action_meaning, entity_table, entity_id, before_json, after_json, branch_id, ruleset_version_id, prev_hash CHAR(64), row_hash CHAR(64), esign_id FK, source(online/offline_replay)`. INSERT-only (revoke UPDATE/DELETE at DB-grant level); separate INSERT-only audit-writer DB account; trigger rejects UPDATE/DELETE.
- **`audit_chain_anchors`** — `chain_head_hash, anchored_at, tsa_token, server_signature` (periodic external/WORM/RFC-3161 notarization — the part MySQL alone cannot guarantee).
- **`electronic_signatures`** — `signer_user_id, signed_at_utc, meaning(reviewed/approved/released/verified/quarantine_release/recalled), auth_method, reauth_at, signed_payload_hash (binds signature to record content), audit_log_id FK`.
- **RBAC:** `permissions`, `roles`, `user_roles(…,branch_id)`, `role_permissions`, `sod_conflicts(permission_a,permission_b)`. `ALTER blood_units` release pipeline: add `collected_by, tested_by, interpreted_by, released_by` + timestamps; enforce `released_by NOT IN (collected_by,tested_by,interpreted_by)`.
- **`break_glass_sessions`**, **`sessions`** (server-side, idle+absolute timeout), `ALTER users`: `password_hash (Argon2id), mfa_secret_enc, mfa_enabled, mfa_recovery_codes_hashed, failed_attempts, locked_until`.
- **Privacy:** `consent_records` (distinguish donor consent vs recipient vital-interest/healthcare basis), `dsr_requests`, `subject_identity` (split direct identifiers, field-encrypted with blind indexes for exact-match), `key_refs` (envelope-encryption metadata; master key in external KMS).

### 3.10 Concurrency & sync
- **`unit_ownership_log`** (append-only, who owned each DIN when), **`sync_events`** (event_uuid idempotency key, branch_id, entity_din, action, prior_version, device_ts, server_received_ts, apply_result), **`sync_conflicts`** (mandatory human reconciliation workflow — never auto-merge unit lifecycle), **`inventory_change_feed`** (seq per branch for cheap 304/SSE polling).

### 3.11 Analytics event spine
- **`unit_event_log`** (append-only) — `unit_id, event_type(collected/tested/available/reserved/crossmatched/issued/transfused/returned/discarded/expired/transferred), event_ts UTC, actor, branch_id, related_request_id, reason_code_id`. *Note: this overlaps `unit_status_events` (L4) and the `sync_events`/audit spine — **consolidate to one append-only event stream** feeding state machine, audit, and analytics rather than three parallel logs.*
- **`reason_codes`**, **`demand_fact_daily`** (materialized nightly), **`forecast`**, **`forecast_accuracy`**, **`kpi_daily`**, **`config_targets`** (per-tenant ABO/Rh distribution, days-of-supply, near-expiry windows, C:T target, safety quantile).

> **Cross-lane consolidation note:** Lanes 1, 4, 5, 6, 7, 8 each independently propose an append-only event/audit log. Build **one** canonical append-only, hash-chained event stream with typed event kinds, not six tables. Likewise the patient special-requirements table appears in both L1 and L4 — merge.

---

## 4. The Stack Reckoning

**Honest verdict: vanilla PHP/MySQL/AJAX is an adequate core for the domain/inventory logic and good-enough for KPI computation and lightweight forecasting — but it does NOT meet the sellable bar unaugmented. An unaugmented LAMP build will fail a 21 CFR Part 11 / EU GMP Annex 11 audit, a GDPR Art 35 DPIA, and hospital LIS/HIS integration onboarding.** This is the consensus across every lane. The relational schema, deterministic safety gates, rule engine, RBAC/SoD, state-machine triggers, password/MFA/session security, and KPI aggregation are all genuinely feasible on the stack. What breaks:

- **Concurrency (single-issuance):** Solvable in-stack *only* with InnoDB `SELECT … FOR UPDATE` inside an explicit transaction (autocommit off), a deadlock-retry wrapper (ER 1213/1205 *will* occur), `READ COMMITTED` isolation, `SKIP LOCKED` for "grab any compatible unit" / `NOWAIT` for targeted actions. A SELECT-then-UPDATE without `FOR UPDATE` is the classic double-allocation bug. **This is non-negotiable and must be designed in, not assumed.**

- **Offline multi-branch sync (shared inventory):** **Not safely feasible as multi-master on any stack** — it is a CAP-theorem wall, not a PHP limitation. You cannot un-transfuse blood, and last-write-wins silently hides a two-patients-one-bag event. CRDTs do **not** rescue this (single-issuance is distributed mutual exclusion, not a mergeable type). Minimum viable: **central authoritative DB + exclusive per-unit branch ownership**; offline branch acts only on units it solely owns; idempotent append-only sync; conflicts quarantine + raise critical alert, never auto-merge. Sell "offline-resilient issuance of locally-owned stock," not "full offline multi-branch operation."

- **Real-time visibility:** Vanilla PHP cannot push. 30s AJAX polling is acceptable for *awareness only* — correctness is enforced at commit by `FOR UPDATE`, never by what the UI showed. Genuine real-time requires an **always-on non-PHP component** (Mercure SSE hub, or Swoole/Workerman/Ratchet, or Centrifugo/Soketi). This breaks the "drop on any LAMP host" pitch and must be disclosed.

- **Cold-chain monitoring:** A request-driven app **cannot detect a sensor that stops reporting** (the dangerous failure) or deliver an alarm when no browser is open. Requires a **background worker/daemon** (real OS cron or a long-running service, not request-triggered pseudo-cron) plus an **out-of-band notification path** (SMS/voice/email gateway with escalation). Validated hardware dataloggers with independent alarms should remain the *primary* safety layer; the software is the QA/record system.

- **Interoperability (HL7/FHIR):** HL7 v2 over MLLP needs a **persistent TCP daemon** (framing, ACK/NAK, queue, retry) — outside request/response PHP; realistically a dedicated interface engine (Mirth/NextGen Connect) or long-running worker. FHIR needs a conformant REST facade (CapabilityStatement, LOINC/SNOMED/ISBT-128 terminology binding) — implementable in PHP only as a deliberately built, version-pinned subsystem, never ad-hoc JSON. **A single-silo app with no HL7/FHIR is unsellable beyond one silo.**

- **ISBT 128 labeling:** PHP can render labels *only* with a validated Code 128 + Data Matrix ECC200 library producing correct data identifiers, quiet zones, and ISO 7064 MOD 37-2 check characters. Generic QR libraries are unacceptable. Code tables are externally licensed/versioned — needs an import pipeline, not an enum.

- **E-signatures & immutable audit:** MySQL rows are mutable; hash-chaining gives tamper-**evidence**, not tamper-**prevention** (a root/DBA can recompute the whole chain). True immutability needs **external anchoring** (WORM store, RFC 3161 TSA, or signed off-host nightly digest) — DBA/root is explicitly outside the trust boundary. Signatures must bind to a **content hash** (11.70) and re-authenticate at signing (11.200). Trusted **server-side UTC time** (NTP/TSA) is mandatory — never accept a client timestamp.

- **Encryption/keys:** Field-level AES-256-GCM on direct identifiers (defeats indexing — use blind indexes for exact match only); keys in an **external KMS/HSM**, never in PHP config or the DB. MySQL TDE protects files at rest only and requires Enterprise/MariaDB with a proper keyring plugin (a licensing cost).

**Minimum viable architecture:** PHP/MySQL core domain app **+** (1) a push/real-time hub, (2) a background worker/scheduler service, (3) an out-of-band alerting path, (4) an HL7 interface engine + FHIR facade, (5) an ISBT 128 label/identity module, (6) a KMS, (7) external audit anchoring, (8) validated hardware dataloggers. The PHP web app becomes *one component*, not the whole system. Say this to the buyer plainly rather than designing to a happy path.

---

## 5. Standards Checklist

| Standard | What it obligates |
|---|---|
| **ISBT 128 (ICCBBA ST-001/ST-002)** | ~~Requires per-facility ICCBBA registration + licensed code tables.~~ **Deferred — no budget.** *Principles adopted:* custom DID (same structural idea: facility + year + serial + check char), Code 128 barcode symbology (free, ISO/IEC 15417), Codabar fallback, internal component catalog replaces Product Description Codes. ISBT 128 upgrade path left open (DID column aliasable). No QR. |
| **HL7 v2 / FHIR R4/R5** | v2 over MLLP: ADT (identity), OML/ORM (orders), ORU/OUL (results), BPO/BTX/TCD/SPM blood-bank segments. FHIR: Patient, ServiceRequest, Specimen, Observation, DiagnosticReport, BiologicallyDerivedProduct(+Dispense), MedicationAdministration/Procedure, Provenance. The interoperability boundary — not a custom API. |
| **FDA 21 CFR Part 11** | Validated system (IQ/OQ/PQ); secure, computer-generated, time-stamped, non-obscuring audit trail (11.10e); human-readable + electronic record export (11.10b); authority checks (11.10g); e-signatures with name+date+meaning (11.50), bound to record (11.70), two components / re-auth (11.200), ID/password controls (11.300). Validation is the *customer's* facility obligation; vendor ships the package. |
| **FDA 21 CFR 606 / 610 / 640** | cGMP for blood; records & traceability (606.160, ≥10y retention); HIV/HCV look-back (610.46/610.47); component-specific storage/additive requirements; product-deviation & fatality reporting (606.171 / 600.14). |
| **EU Blood Directive 2002/98/EC + 2004/33/EC + 2005/61/EC + 2005/62/EC** | Designated responsible person (Art 9); full vein-to-vein traceability with ≥30-year retention (Art 14 / 2005/61/EC); donor eligibility/testing technical requirements (2004/33/EC); SAE/SAR haemovigilance notification with severity + imputability grading; GMP-equivalent quality system. |
| **WHO Blood Safety** | Universal minimum TTI panel (HIV, HBsAg, anti-HCV, syphilis); donor suitability assessment; cold-chain & wastage guidance (<5% RBC target); vein-to-vein traceability & haemovigilance. |
| **AABB Standards (current ed.) + Technical Manual** | Pretransfusion testing, two ABO determinations, historical antibody records & antigen-negative selection, electronic-crossmatch eligibility, sample validity (3-day rule), irradiation dating (28d), MSBOS/C:T ratio, qualified second review before release, 30-minute / validated return rule. |
| **ISBT/IHN haemovigilance definitions** | Standardized reaction definitions (TACO 2018 / TRALI 2019 consensus, AHTR/DHTR/FNHTR/etc.) and donor surveillance definitions; severity (0–4/death) + imputability scales. |
| **GDPR / HIPAA / ISO 27001 / ISO 15189 / Annex 11** | Special-category health-data lawful basis (donor consent withdrawable; recipient = healthcare/vital-interest, not consent); DSR workflows; DPIA (Art 35); breach notification 72h; encryption & access control (Art 32); lab quality/competence; computerized-system validation & data integrity. |

*Caveat: all clause numbers above are from standards knowledge under a verification outage and must be re-checked against primary text before any regulatory claim.*

---

## 6. Revised Roadmap

**Phase 0 — Foundations (rebuild, not bolt-on):** Patient registry + MPI/identifiers; append-only hash-chained event/audit stream (one canonical log); permission-based RBAC + SoD; Argon2id + server-side sessions; data-driven compliance rule engine skeleton with versioned rulesets bound per-branch. *These are prerequisites for everything else; retrofitting them later means a rewrite.*

**Phase 1 — MVP Core (safely buildable, single-site, online):**
- Pretransfusion chain: T&S sample + validity window, two-ABO rule, antibody screen/ID, persistent antibody + special-requirements history.
- Typed crossmatch records (IS/AHG/electronic with enforced eligibility gates) + emergency uncrossmatched release with retrospective tasks.
- Unit state machine with DB-trigger guards; special attributes enforced at issue; FEFO allocation.
- Single-issuance via `FOR UPDATE` + deadlock retry + timed reservations (lazy reclaim).
- Component lineage DAG + look-back/recall query; configurable mandatory TTI panel + reactive-lockout/quarantine-until-tested.
- Custom DID + internal component catalog + Code 128/Codabar labels (no ICCBBA registration required; free symbologies only).
- E-signatures bound to content hash on release; server-authoritative UTC time; external audit anchoring.
- KPI event spine + nightly materialized KPIs (wastage, stock-out, C:T, days-of-supply, TAT, near-expiry); cold-start forecasting (moving avg → SES → Holt-Winters additive) via a **real scheduler**.

**Phase 2 — Sellable-product increments:**
- Cold-chain: background worker for sensor-disconnect, excursion auto-quarantine, out-of-band escalation; integration with validated dataloggers; transport cold-chain.
- Hemovigilance: recipient reaction + donor adverse-event capture with severity/imputability, TACO/TRALI differentiation, regulatory reporting timelines.
- Bedside barcode positive patient+unit verification (PWA/scanner layer).
- Real-time visibility hub (SSE/Mercure) with polling fallback.
- KMS integration + field-level PII encryption + blind indexes; DPIA/SOP/validation-package deliverables.

**Phase 3 — Multi-branch & interoperability:**
- Central authoritative DB + exclusive per-unit ownership; idempotent append-only sync; conflict-quarantine reconciliation; offline-resilient locally-owned issuance.
- HL7 v2 interface engine (MLLP) + FHIR R4 facade; per-hospital onboarding/conformance toolkit; haemovigilance HL7/FHIR export.

**Phase 4 — Analytics maturity (only if justified):** Multi-tenant pooled forecasting as a *separate* Python microservice with exogenous regressors — explicitly deferred; ML is cost without payback at single-hospital volume.

---

## 7. Open Decisions for the Human

1. **Offline scope.** Full offline multi-branch (unsafe/undeliverable) vs central-authority + exclusive per-unit ownership. **Recommend:** the latter; refuse full offline shared-inventory writes as a feature. (Strong cross-lane consensus, L5.)

2. **ISBT 128 vs alternate identifier.** ~~ISBT 128 requires per-customer ICCBBA registration + recurring licensing.~~ **DECIDED (2026-06-15):** Use custom DID scheme on Code 128 (free). Codabar acceptable as secondary option. No QR. ISBT 128 upgrade path kept open via nullable `iccbba_fin` and aliasable DID column. (L2, L3, L4.)

3. **Real-time component.** Accept the always-on non-PHP hub (breaks "pure LAMP") vs ship 30s-polling-only and market honestly as "up to 30s stale." **Recommend:** polling for MVP, SSE/Mercure hub for the sellable product; disclose either way. (L5.)

4. **HL7/FHIR build vs buy.** Embed a dedicated interface engine (Mirth) vs build a PHP worker/facade. **Recommend:** buy/integrate Mirth for HL7 v2 MLLP; build a thin FHIR facade in PHP. (L3.)

5. **MySQL edition for TDE.** Community (file-keyring, weak) vs Enterprise/MariaDB (proper keyring, licensing cost). **Recommend:** MariaDB or MySQL Enterprise + external KMS + app-level field encryption; do not rely on community file-keyring at the sellable bar. (L8.)

6. **Audit immutability anchor.** Self-contained hash chain (tamper-evident only) vs external WORM/RFC-3161 anchoring (tamper-resistant against DBA/root). **Recommend:** external anchoring of the chain head; treat DBA/root as outside the trust boundary. Do not market MySQL-only as tamper-proof. (L2, L4, L8.)

7. **Validation/compliance ownership.** Vendor cannot certify "Part 11 compliant" in the abstract. **Recommend:** ship a validation package (IQ/OQ/PQ, traceability matrix, VMP, change control, DPIA, SOPs) as a priced deliverable; never market pre-certification. (L2, L8.)

8. **Forecasting depth.** Holt-Winters + safety quantile (in-stack) vs ML. **Recommend:** Holt-Winters additive with MASE-driven auto-fallback for MVP; defer ML to a future pooled multi-tenant service only. Region-specific ABO/Rh distributions and all KPI thresholds must be config, never hardcoded. (L7.)

9. **Region/jurisdiction binding granularity.** One global config vs per-branch jurisdiction binding. **Recommend:** bind each branch to its own jurisdiction+ruleset — a single install may legitimately span conflicting jurisdictions. (L2.)

10. **Consolidate the event/audit/state/sync logs.** Six lanes each proposed an append-only log. **Recommend (architect's call, low-risk):** one canonical append-only hash-chained event stream with typed event kinds feeding state machine, audit, analytics, and sync — not parallel tables that can drift.