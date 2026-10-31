# Blood Bank Management System — Master Requirements Specification
## Version 1.0 | 2026-06-15

> **Licensing constraint (hard):** Zero budget for paid licensing. No ICCBBA registration, no licensed ISBT 128 code tables, no paid standards documents, no commercial library fees. All international clinical and safety standards are followed using only free/open materials. Domestic deployment scope. ISBT 128 upgrade path preserved via aliasable columns and nullable foreign key.
>
> **Standing rule:** Any requirement referencing a paid standard or licensed code table is automatically replaced by its free-equivalent implementation described herein. No exceptions without explicit sign-off.

---

## Table of Contents
1. [System Overview](#1-system-overview)
2. [Architectural Principles](#2-architectural-principles)
3. [Functional Requirements](#3-functional-requirements)
4. [Complete Database Schema](#4-complete-database-schema)
5. [State Machines](#5-state-machines)
6. [Safety Guards (Non-Negotiable)](#6-safety-guards-non-negotiable)
7. [Security Requirements](#7-security-requirements)
8. [Cold Chain Requirements](#8-cold-chain-requirements)
9. [Compliance Engine Requirements](#9-compliance-engine-requirements)
10. [Interoperability Requirements](#10-interoperability-requirements)
11. [Audit and Traceability Requirements](#11-audit-and-traceability-requirements)
12. [Analytics and Forecasting Requirements](#12-analytics-and-forecasting-requirements)
13. [Multi-Branch Architecture](#13-multi-branch-architecture)
14. [Non-Functional Requirements](#14-non-functional-requirements)
15. [Tech Stack Decisions](#15-tech-stack-decisions)
16. [Standards Compliance Map](#16-standards-compliance-map)
17. [Phase Roadmap](#17-phase-roadmap)

---

## 1. System Overview

### 1.1 Purpose
A multi-branch blood bank management system covering the complete lifecycle of a blood donation: donor eligibility screening → collection → component processing → infectious disease testing → labeling → storage and cold-chain monitoring → pretransfusion compatibility testing → clinical issue → bedside administration → hemovigilance. The system enforces all clinical safety invariants at the database layer — not solely in application code — so that no application-layer bug can issue blood that is expired, quarantined, recalled, or incompatible.

### 1.2 Scope
- Domestic blood movement only (no international transfer of units)
- Multi-branch single-deployment (one authoritative central database)
- Replaces the following in a conventional blood bank: paper compatibility records, manual temperature logs, spreadsheet forecasting, paper audit trail

### 1.3 Core Safety Invariants (Hardcoded — Cannot Be Configured Away)
These invariants are enforced by database triggers in addition to application logic. No configuration, permission, or override can disable them:

1. A unit in status `quarantined`, `in_testing`, `failed_qc`, `expired`, `recalled`, `quarantined_holdback`, or `destroyed` cannot be issued.
2. A unit cannot be issued to a patient whose blood request requires special attributes (irradiated, CMV-negative, antigen-negative, washed) that the unit does not satisfy.
3. A unit with any reactive infectious disease test result cannot be released.
4. A unit cannot be issued without a completed crossmatch record (except emergency uncrossmatched release, which has its own audited pathway).
5. A patient with a clinically significant historical antibody (even if currently undetectable) must only receive antigen-negative units for that specificity.
6. A blood unit cannot be issued to two patients simultaneously (transactional row locking enforced).
7. No blood unit status can revert to a less-restrictive state (e.g. `transfused` → `available` is forbidden).
8. Every safety-critical action requires a human actor with explicit permission — no anonymous or automated direct issue.
9. The person who released a unit must not be the same person who collected, tested, or interpreted results for that unit (Separation of Duties).
10. All timestamps used for clinical decisions are server-side UTC. Client-supplied timestamps are rejected for all safety-critical records.

---

## 2. Architectural Principles

### 2.1 Database as the Authority
All business rules that are patient-safety critical are implemented twice: once in application logic and once as database-level constraints (triggers, CHECK constraints, foreign keys). The database layer is the last line of defense.

### 2.2 Append-Only for Safety Records
The following tables are INSERT-only. The application database account has no UPDATE or DELETE privilege on them:
- `audit_logs`, `unit_status_events`, `patient_blood_groups`, `patient_antibodies`, `electronic_signatures`, `unit_lineage`, `recall_items`, `consent_records`, `donation_test_result`, `unit_event_log`

### 2.3 Single Authoritative Database
One central MariaDB/MySQL instance is the authoritative source. Branches do not run independent databases that merge. Offline resilience is limited to: actions on units that the branch exclusively owns. Shared-inventory writes while offline are forbidden.

### 2.4 Configuration Over Code for Compliance Rules
Eligibility rules, deferral criteria, mandatory test panels, retention periods, and labeling profiles are stored as versioned database records evaluated by a generic rule engine. Selling into a new jurisdiction = loading a ruleset. Editing PHP is not required.

### 2.5 Separation of Concerns
The system is one cohesive PHP application plus mandatory satellite components:
- Background worker/daemon (cold chain, forecasting, alerts — cannot be done in request/response)
- Out-of-band alerting path (SMS/email — not just in-browser)
- HL7 interface engine for hospital integration (Mirth Connect, free/open source)
- External Key Management System (HashiCorp Vault, free/open source)
- External audit anchoring (RFC 3161 TSA or append-only remote log)

---

## 3. Functional Requirements

### 3.1 Donor Management
- REQ-D01: Register donors with demographic details. Store all PII encrypted; use blind indexes for lookup.
- REQ-D02: Evaluate donor eligibility at each donation against the active compliance ruleset (age, weight, hemoglobin, blood pressure, donation interval, deferral history, travel/exposure history).
- REQ-D03: Apply temporary and permanent deferrals. Permanent deferrals cannot be overridden without medical director e-signature.
- REQ-D04: Capture donor adverse events (vasovagal, hematoma, nerve injury, citrate reaction) with severity and outcome.
- REQ-D05: Record full informed consent per donation, including privacy notice version shown.

### 3.2 Donation and Component Production
- REQ-C01: One donation record per collection event. One donation yields one or more blood unit records through processing events.
- REQ-C02: Model the full component DAG (Directed Acyclic Graph): whole blood → separation → RBC + plasma + platelets + cryoprecipitate.
- REQ-C03: Track splits, pools, irradiation, leukoreduction, washing, deglycerolization, and aliquoting as first-class processing events.
- REQ-C04: Irradiation automatically recalculates unit expiry to 28 days from irradiation datetime (not original expiry). Enforced via trigger.
- REQ-C05: Deglycerolization automatically recalculates unit expiry to 24 hours. Enforced via trigger.
- REQ-C06: Every processing step requires an electronic signature from the performing staff member.
- REQ-C07: Assign a DID (Donation ID) to every unit at creation. Format: `[3-char facility][2-digit year][6-digit serial][1 check char]` = 12 chars. Check char computed by ISO 7064 MOD 11-2. DID is immutable once assigned.
- REQ-C08: Print Code 128 barcode label for every unit using the current approved label template. Log every print.

### 3.3 Infectious Disease Testing
- REQ-T01: Every donation must be tested for the mandatory panel defined in the active compliance ruleset (minimum: HIV Ag/Ab combo, HBsAg, anti-HCV, syphilis). Additional tests per jurisdiction.
- REQ-T02: A unit cannot transition to `available` until all mandatory tests have a non-reactive result AND an e-signature of the interpreter.
- REQ-T03: Any reactive result immediately sets the unit to `quarantined` (or `failed_qc` if non-releasable) and triggers a lockout. This cannot be overridden by application logic — it is enforced by a DB trigger.
- REQ-T04: Repeat-reactive results require second-line confirmatory testing before permanent deferral of donor.
- REQ-T05: Test results are linked to: the specific donation, the specific sample, the instrument used, the performing tech, and the reviewing tech (two-person verification).

### 3.4 Patient Registry
- REQ-P01: Every recipient is a persistent patient record, not a text name on a request form.
- REQ-P02: A patient may have multiple IDs across branches (different MRNs). All resolve to one `patient_id` via the `patient_identifiers` table.
- REQ-P03: Patient merges (deduplication) are audited and signed. Merged records are never hard-deleted. All history from both records carries forward.
- REQ-P04: Patient blood group history is append-only. The current blood group is a database view over the history, not a stored column.
- REQ-P05: Patient antibody history is lifelong, append-only, and cross-branch. An antibody identified at any branch is visible at all branches.
- REQ-P06: Patient special requirements (irradiated-for-life, CMV-negative, antigen-negative, washed) are stored per patient and enforced at every issue event.

### 3.5 Pretransfusion Testing Chain
- REQ-X01: Every non-emergency issue requires a current pre-transfusion sample with confirmed validity.
- REQ-X02: Sample validity for patients transfused or pregnant within the prior 3 months is 72 hours (3-day rule, day 0 = collection day). System enforces this.
- REQ-X03: Non-O blood group units require two independent ABO/Rh determinations before issue: current sample + one prior historical record OR two independently-collected samples. System blocks group-specific issue on a single determination.
- REQ-X04: Antibody screen must be performed and resulted on the current sample before crossmatch.
- REQ-X05: Crossmatch method:
  - Serologic (immediate spin): ABO incompatibility only — not sufficient when patient has antibody history or positive screen.
  - AHG (antiglobulin): Required when current screen positive OR any historical antibody of clinical significance exists.
  - Electronic (computer): Permitted only when ALL of: (a) two concordant ABO/Rh results on file, (b) current screen negative, (c) no clinical antibody history, (d) donor unit ABO confirmed, (e) system has been validated for this. Failure of any condition auto-downgrades to AHG.
- REQ-X06: Electronic crossmatch eligibility gates are server-side evaluated and not overridable without medical director e-signature.
- REQ-X07: Emergency uncrossmatched release follows the `emergency_release` pathway: physician ID + justification required at release; retrospective crossmatch and physician sign-off tasks created automatically.

### 3.6 Blood Issue and Administration
- REQ-I01: Issue is a transactional operation using `SELECT ... FOR UPDATE` on the specific unit row. Double-issue is structurally impossible (not just handled by application logic).
- REQ-I02: Before issuing any unit, the system verifies: unit status = `crossmatched`, ABO compatibility, all patient special requirements met, unit not expired, crossmatch not expired.
- REQ-I03: Issue requires an electronic signature from the authorized issuer.
- REQ-I04: Issuer must not be the same person as collector, tester, or result interpreter for that unit (enforced at issue time).
- REQ-I05: Bedside verification: patient wristband barcode and unit DID barcode are both scanned at the bedside. Mismatch blocks administration. Two-person confirmation recorded.
- REQ-I06: Transfusion outcome (completion, adverse event, time, vital signs, staff) is recorded in `transfusion_administration`.
- REQ-I07: Unit return: units returned from ward within 30 minutes (or within validated temperature parameters) may be returned to stock following the `unit_return_check` workflow.

### 3.7 Hemovigilance
- REQ-H01: Transfusion reactions are recorded with ISBT/IHN standard categories, severity grade 0–4, and imputability scale (definite/probable/possible/unlikely/excluded/not_assessable).
- REQ-H02: TACO and TRALI differentiation using current consensus definitions (2018/2019).
- REQ-H03: Reportable reactions are flagged; the system generates a structured report. The staff member submits to the relevant authority.
- REQ-H04: Donor adverse events are captured with severity, outcome, and reportability flag.
- REQ-H05: Hemovigilance data is exportable in HL7 FHIR format for national/regional surveillance reporting.

### 3.8 Recall and Look-Back
- REQ-R01: Recall is triggered by: donor seroconversion, positive confirmatory test, recipient reaction, equipment failure, or external recall notice.
- REQ-R02: On trigger, system uses a recursive CTE over `unit_lineage` to find ALL components derived from affected donations, including splits, pools, and co-components.
- REQ-R03: In-stock units are bulk-transitioned to `quarantined_holdback` or `recalled` status automatically.
- REQ-R04: Already-issued units trace to recipients via `issue_transactions`. Recipient patient_ids are surfaced for clinical notification. System does not automatically contact patients — it surfaces the data for clinicians.
- REQ-R05: Full recall status tracking through to disposition and regulatory reporting. Recall cannot be closed without e-signature from medical director.

---

## 4. Complete Database Schema

### Conventions
- `PK` = Primary Key (BIGINT AUTO_INCREMENT unless noted)
- `FK → table` = Foreign key reference
- `UNIQUE` = Unique constraint
- All timestamps are `DATETIME(6)` in UTC unless noted as `DATE`
- `JSON` columns validated by app layer
- `ENUM` types defined exhaustively
- Append-only tables: denoted with `[append-only]`
- All `TEXT` columns storing PII must use application-level AES-256-GCM encryption

---

### 4.1 Branches and Facilities

```sql
CREATE TABLE branches (
  branch_id       BIGINT PRIMARY KEY AUTO_INCREMENT,
  name            VARCHAR(200) NOT NULL,
  address         TEXT,
  facility_code   CHAR(3) NOT NULL UNIQUE,  -- used in DID generation
  jurisdiction_id BIGINT NOT NULL,           -- FK compliance_jurisdiction
  ruleset_id      BIGINT,                    -- FK compliance_ruleset (active ruleset)
  timezone        VARCHAR(50) NOT NULL DEFAULT 'UTC',
  active          TINYINT(1) NOT NULL DEFAULT 1,
  created_at      DATETIME(6) NOT NULL
);

CREATE TABLE ref_facilities (
  facility_code   CHAR(3) PRIMARY KEY,
  name            VARCHAR(200) NOT NULL,
  branch_id       BIGINT NOT NULL  -- FK branches
);
```

---

### 4.2 Users, Roles, Permissions, SoD

```sql
CREATE TABLE users (
  user_id               BIGINT PRIMARY KEY AUTO_INCREMENT,
  username              VARCHAR(100) NOT NULL UNIQUE,
  password_hash         VARCHAR(255) NOT NULL,    -- Argon2id via PHP password_hash()
  mfa_secret_enc        TEXT,                     -- encrypted TOTP secret
  mfa_enabled           TINYINT(1) NOT NULL DEFAULT 0,
  mfa_recovery_codes_hashed  JSON,               -- array of hashed backup codes
  failed_attempts       SMALLINT NOT NULL DEFAULT 0,
  locked_until          DATETIME(6),
  branch_id             BIGINT,                  -- FK branches (home branch)
  display_name          VARCHAR(200) NOT NULL,
  active                TINYINT(1) NOT NULL DEFAULT 1,
  created_at            DATETIME(6) NOT NULL,
  created_by            BIGINT                   -- FK users
);

CREATE TABLE permissions (
  permission_id   BIGINT PRIMARY KEY AUTO_INCREMENT,
  code            VARCHAR(100) NOT NULL UNIQUE,  -- e.g. 'unit.release', 'test.perform'
  description     VARCHAR(500)
);

CREATE TABLE roles (
  role_id         BIGINT PRIMARY KEY AUTO_INCREMENT,
  name            VARCHAR(100) NOT NULL,
  branch_scoped   TINYINT(1) NOT NULL DEFAULT 1,
  description     VARCHAR(500)
);

CREATE TABLE user_roles (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id         BIGINT NOT NULL,               -- FK users
  role_id         BIGINT NOT NULL,               -- FK roles
  branch_id       BIGINT,                        -- FK branches (null = all branches)
  granted_by      BIGINT NOT NULL,               -- FK users
  granted_at      DATETIME(6) NOT NULL,
  revoked_at      DATETIME(6),
  UNIQUE (user_id, role_id, branch_id)
);

CREATE TABLE role_permissions (
  role_id         BIGINT NOT NULL,               -- FK roles
  permission_id   BIGINT NOT NULL,               -- FK permissions
  PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE sod_conflicts (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  permission_a    BIGINT NOT NULL,               -- FK permissions
  permission_b    BIGINT NOT NULL,               -- FK permissions
  reason          VARCHAR(500)
  -- Enforced: no user can hold both permission_a and permission_b simultaneously
);

CREATE TABLE sessions (
  session_id            VARCHAR(128) PRIMARY KEY,
  user_id               BIGINT NOT NULL,          -- FK users
  created_at            DATETIME(6) NOT NULL,
  last_activity_at      DATETIME(6) NOT NULL,
  absolute_expires_at   DATETIME(6) NOT NULL,
  ip                    VARCHAR(45),
  user_agent            VARCHAR(500),
  reauth_at             DATETIME(6)               -- last password re-entry (for e-signing)
);

CREATE TABLE break_glass_sessions (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id         BIGINT NOT NULL,               -- FK users
  reason_code     VARCHAR(50) NOT NULL,
  justification   TEXT NOT NULL,
  granted_at      DATETIME(6) NOT NULL,
  expires_at      DATETIME(6) NOT NULL,
  alert_sent_to   BIGINT,                        -- FK users (supervisor notified)
  reviewed_by     BIGINT,                        -- FK users
  reviewed_at     DATETIME(6)
);
```

---

### 4.3 Donors

```sql
CREATE TABLE donors (
  donor_id                BIGINT PRIMARY KEY AUTO_INCREMENT,
  subject_id              BIGINT NOT NULL UNIQUE, -- FK subject_identity (PII stored there)
  sex                     ENUM('M','F','Unknown') NOT NULL,
  dob                     DATE NOT NULL,
  blood_group_abo         ENUM('A','B','AB','O'),
  blood_group_rh          ENUM('pos','neg','weak_d','unknown'),
  deferral_status         ENUM('active','temporary_defer','permanent_defer') NOT NULL DEFAULT 'active',
  deferral_reason         VARCHAR(500),
  deferral_until          DATE,
  deferral_set_by         BIGINT,                -- FK users
  total_donations         INT NOT NULL DEFAULT 0,
  last_donation_date      DATE,
  registration_branch_id  BIGINT NOT NULL,       -- FK branches
  created_at              DATETIME(6) NOT NULL,
  created_by              BIGINT NOT NULL        -- FK users
);

CREATE TABLE donations (
  donation_id             BIGINT PRIMARY KEY AUTO_INCREMENT,
  donor_id                BIGINT NOT NULL,        -- FK donors
  branch_id               BIGINT NOT NULL,        -- FK branches
  donated_at              DATETIME(6) NOT NULL,
  donation_type           ENUM('whole_blood','apheresis_rbc','apheresis_plt','apheresis_plasma','apheresis_multicomponent') NOT NULL,
  volume_ml               SMALLINT,
  bag_lot_number          VARCHAR(50),
  collection_set_lot      VARCHAR(50),
  collected_by            BIGINT NOT NULL,        -- FK users
  phlebotomy_site         VARCHAR(100),
  adverse_event_id        BIGINT,                -- FK donor_adverse_event
  consent_id              BIGINT NOT NULL,        -- FK consent_records
  created_at              DATETIME(6) NOT NULL
);

CREATE TABLE donor_adverse_event (
  event_id        BIGINT PRIMARY KEY AUTO_INCREMENT,
  donation_id     BIGINT NOT NULL,               -- FK donations
  donor_id        BIGINT NOT NULL,               -- FK donors
  event_type      ENUM('vasovagal','syncope','hematoma','nerve_injury','citrate_reaction','arterial_puncture','other') NOT NULL,
  severity        ENUM('mild','moderate','severe') NOT NULL,
  loss_of_consciousness  TINYINT(1) NOT NULL DEFAULT 0,
  injury          TINYINT(1) NOT NULL DEFAULT 0,
  treatment       TEXT,
  outcome         ENUM('full_recovery','ongoing','medical_referral','hospitalized') NOT NULL,
  reportable      TINYINT(1) NOT NULL DEFAULT 0,
  report_ref      VARCHAR(100),
  recorded_by     BIGINT NOT NULL,               -- FK users
  recorded_at     DATETIME(6) NOT NULL
);
```

---

### 4.4 Patients

```sql
CREATE TABLE patients (
  patient_id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  mpi_uid                 CHAR(36) NOT NULL UNIQUE,  -- master patient index UUID
  subject_id              BIGINT NOT NULL UNIQUE,     -- FK subject_identity
  sex                     ENUM('M','F','Unknown') NOT NULL,
  dob                     DATE,
  merged_into_patient_id  BIGINT,                    -- FK patients (for dedup merges)
  record_status           ENUM('active','merged','blocked') NOT NULL DEFAULT 'active',
  created_at              DATETIME(6) NOT NULL,
  created_by              BIGINT NOT NULL             -- FK users
);

CREATE TABLE patient_identifiers (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  patient_id      BIGINT NOT NULL,               -- FK patients
  system          VARCHAR(100) NOT NULL,          -- e.g. 'MRN:BranchA', 'national-id'
  value           VARCHAR(200) NOT NULL,
  is_primary      TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE (system, value)
);

-- Append-only: never UPDATE, never DELETE
CREATE TABLE patient_blood_groups (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  patient_id      BIGINT NOT NULL,               -- FK patients
  abo             ENUM('A','B','AB','O') NOT NULL,
  rh_d            ENUM('pos','neg','weak_d','unknown') NOT NULL,
  method          VARCHAR(50) NOT NULL,           -- gel / tube / analyzer
  sample_id       BIGINT NOT NULL,               -- FK samples
  determined_by   BIGINT NOT NULL,               -- FK users
  verified_by     BIGINT,                        -- FK users (second person, required for first determination)
  branch_id       BIGINT NOT NULL,               -- FK branches
  source          ENUM('current_testing','historical','external') NOT NULL,
  is_discrepant   TINYINT(1) NOT NULL DEFAULT 0, -- triggers investigation if 1
  supersedes_id   BIGINT,                        -- FK self (which older record this replaces)
  determined_at   DATETIME(6) NOT NULL,
  esign_id        BIGINT                         -- FK electronic_signatures
);

-- Append-only: lifelong alloantibody history
CREATE TABLE patient_antibodies (
  id                      BIGINT PRIMARY KEY AUTO_INCREMENT,
  patient_id              BIGINT NOT NULL,        -- FK patients
  specificity             VARCHAR(50) NOT NULL,   -- anti-K, anti-Jka, anti-E, anti-D, etc.
  antigen_system          VARCHAR(50) NOT NULL,   -- Kell, Kidd, Duffy, Rh, MNS, etc.
  clinical_significance   ENUM('significant','insignificant','unknown') NOT NULL,
  status                  ENUM('identified','suspected','historical_only','ruled_out') NOT NULL,
  evanescent              TINYINT(1) NOT NULL DEFAULT 1,
  autocontrol_positive    TINYINT(1) NOT NULL DEFAULT 0,
  first_identified_at     DATETIME(6) NOT NULL,
  first_identified_branch BIGINT NOT NULL,        -- FK branches
  identified_by           BIGINT NOT NULL,        -- FK users
  last_demonstrated_at    DATETIME(6),
  sample_id               BIGINT                 -- FK samples
);

CREATE TABLE patient_transfusion_requirements (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  patient_id      BIGINT NOT NULL,               -- FK patients
  requirement     ENUM('irradiated','cmv_negative','washed','antigen_negative','phenotype_matched','hbs_negative','leukoreduced_only') NOT NULL,
  antigen_spec    VARCHAR(100),                  -- for antigen_negative: which antigen (e.g. K-neg)
  active          TINYINT(1) NOT NULL DEFAULT 1,
  reason          VARCHAR(500) NOT NULL,
  set_by          BIGINT NOT NULL,               -- FK users
  set_at          DATETIME(6) NOT NULL,
  revoked_by      BIGINT,                        -- FK users
  revoked_at      DATETIME(6)
);
```

---

### 4.5 Blood Units

```sql
CREATE TABLE blood_units (
  unit_id                 BIGINT PRIMARY KEY AUTO_INCREMENT,
  did                     CHAR(12) NOT NULL UNIQUE,   -- Donation ID barcode (immutable)
  did_check_char          CHAR(1) NOT NULL,
  division_suffix         CHAR(2),                    -- A0, B0 for splits/aliquots
  donation_id             BIGINT NOT NULL,             -- FK donations
  component_type_code     CHAR(6) NOT NULL,            -- FK component_types
  component_class         ENUM('RBC','FFP','PLT','CRYO','WB','GRAN') NOT NULL,
  collection_datetime     DATETIME(6) NOT NULL,
  expiry_datetime         DATETIME(6) NOT NULL,        -- recomputed on irradiation/deglyc
  volume_ml               SMALLINT,
  additive_solution       VARCHAR(50),                 -- SAGM, AS-1, CPD, etc.
  status                  ENUM(
    'quarantined',
    'in_testing',
    'available',
    'failed_qc',
    'reserved',
    'crossmatched',
    'issued',
    'transfused',
    'returned_to_stock',
    'wasted',
    'expired',
    'recalled',
    'quarantined_holdback',
    'transferred_out',
    'in_transit',
    'destroyed'
  ) NOT NULL DEFAULT 'quarantined',
  version                 INT NOT NULL DEFAULT 1,      -- optimistic locking
  owner_branch_id         BIGINT NOT NULL,             -- FK branches
  reserved_for_request_id BIGINT,                     -- FK blood_requests
  reserved_by_user_id     BIGINT,                     -- FK users
  reserved_until          DATETIME(6),
  crossmatch_hold_until   DATETIME(6),
  current_equipment_id    BIGINT,                     -- FK storage_equipment
  -- Processing attributes
  leukoreduced            TINYINT(1) NOT NULL DEFAULT 0,
  irradiated              TINYINT(1) NOT NULL DEFAULT 0,
  irradiation_datetime    DATETIME(6),                -- triggers expiry recalculation
  cmv_negative            TINYINT(1) NOT NULL DEFAULT 0,
  washed                  TINYINT(1) NOT NULL DEFAULT 0,
  deglycerolized          TINYINT(1) NOT NULL DEFAULT 0,
  deglycerolization_datetime DATETIME(6),
  antigen_negative_set    JSON,                       -- {"K": true, "E": true, ...}
  pathogen_reduced        TINYINT(1) NOT NULL DEFAULT 0,
  -- Traceability of production chain
  parent_donation_id      BIGINT NOT NULL,             -- FK donations
  production_event_id     BIGINT,                     -- FK processing_events
  -- SoD traceability (for Separation of Duties enforcement at release)
  collected_by            BIGINT,                     -- FK users
  collected_at            DATETIME(6),
  tested_by               BIGINT,                     -- FK users
  tested_at               DATETIME(6),
  interpreted_by          BIGINT,                     -- FK users
  interpreted_at          DATETIME(6),
  released_by             BIGINT,                     -- FK users (must differ from above 3)
  released_at             DATETIME(6),
  -- ISBT 128 upgrade path (nullable until ICCBBA registration obtained)
  iccbba_fin              CHAR(13),                   -- future: ISBT 128 DIN
  iccbba_product_code     CHAR(8),                    -- future: ISBT 128 product code
  created_at              DATETIME(6) NOT NULL
);

CREATE TABLE component_types (
  code                    CHAR(6) PRIMARY KEY,
  name                    VARCHAR(200) NOT NULL,
  component_class         ENUM('RBC','FFP','PLT','CRYO','WB','GRAN') NOT NULL,
  attributes_json         JSON,                       -- default attributes
  shelf_life_hours        SMALLINT NOT NULL,
  storage_temp_min_c      DECIMAL(4,1) NOT NULL,
  storage_temp_max_c      DECIMAL(4,1) NOT NULL
);
```

---

### 4.6 Component Processing (the Production DAG)

```sql
CREATE TABLE processing_events (
  event_id        BIGINT PRIMARY KEY AUTO_INCREMENT,
  event_type      ENUM(
    'whole_blood_separation',
    'apheresis_collection',
    'split',
    'irradiation',
    'leukoreduction',
    'pooling',
    'wash',
    'aliquot',
    'thaw',
    'pathogen_reduction',
    'deglycerolization',
    'freeze'
  ) NOT NULL,
  performed_at    DATETIME(6) NOT NULL,
  performed_by    BIGINT NOT NULL,               -- FK users
  branch_id       BIGINT NOT NULL,               -- FK branches
  sop_version     VARCHAR(50) NOT NULL,
  equipment_id    BIGINT,                        -- FK storage_equipment (e.g. irradiator)
  esign_id        BIGINT NOT NULL,               -- FK electronic_signatures
  notes           TEXT,
  created_at      DATETIME(6) NOT NULL
);

-- Append-only: the family tree of every unit
CREATE TABLE unit_lineage (
  id                      BIGINT PRIMARY KEY AUTO_INCREMENT,
  processing_event_id     BIGINT NOT NULL,        -- FK processing_events
  parent_unit_id          BIGINT,                -- FK blood_units (null if parent is a donation)
  parent_donation_id      BIGINT,                -- FK donations (null if parent is a unit)
  child_unit_id           BIGINT NOT NULL,        -- FK blood_units
  relationship            ENUM('derived_from','split_from','pooled_into','aliquot_of') NOT NULL
  -- Both parent_unit_id and parent_donation_id can exist (for first-generation components)
  -- Recursive CTE over this table gives full ancestor/descendant set for recall
);
```

---

### 4.7 Samples and Testing

```sql
CREATE TABLE samples (
  sample_id               BIGINT PRIMARY KEY AUTO_INCREMENT,
  patient_id              BIGINT,                -- FK patients (null if donor sample)
  donor_id                BIGINT,                -- FK donors (null if patient sample)
  accession_number        VARCHAR(100) NOT NULL UNIQUE,
  collected_at            DATETIME(6) NOT NULL,
  collected_by            BIGINT NOT NULL,        -- FK users
  sample_type             ENUM('pre_transfusion','donor_screening','quality_control','external') NOT NULL,
  validity_expiry         DATETIME(6),            -- for pre-transfusion: 3-day rule
  abo_confirmation_status ENUM('confirmed','single_determination','discrepant','not_applicable') NOT NULL DEFAULT 'not_applicable',
  branch_id               BIGINT NOT NULL,        -- FK branches
  created_at              DATETIME(6) NOT NULL
);

CREATE TABLE antibody_screen (
  screen_id       BIGINT PRIMARY KEY AUTO_INCREMENT,
  sample_id       BIGINT NOT NULL,               -- FK samples
  method          ENUM('IAT','PEG','LISS','gel','solid_phase') NOT NULL,
  screen_cell_lot VARCHAR(100) NOT NULL,
  result_per_cell JSON NOT NULL,                 -- {"cell_1": "neg", "cell_2": "pos", ...}
  overall_result  ENUM('positive','negative','invalid') NOT NULL,
  tech_id         BIGINT NOT NULL,               -- FK users
  performed_at    DATETIME(6) NOT NULL,
  instrument      VARCHAR(100),
  esign_id        BIGINT                         -- FK electronic_signatures
);

CREATE TABLE antibody_identification (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  sample_id       BIGINT NOT NULL,               -- FK samples
  screen_id       BIGINT NOT NULL,               -- FK antibody_screen
  panel_lot       VARCHAR(100) NOT NULL,
  identified_specificities  JSON NOT NULL,       -- ["anti-K","anti-E"]
  excluded_specificities    JSON,
  tech_id         BIGINT NOT NULL,               -- FK users
  reviewed_by     BIGINT,                        -- FK users
  performed_at    DATETIME(6) NOT NULL,
  esign_id        BIGINT                         -- FK electronic_signatures
  -- On save: application creates/updates patient_antibodies rows
);

CREATE TABLE test_definition (
  test_code       VARCHAR(50) PRIMARY KEY,
  name            VARCHAR(200) NOT NULL,
  pathogen        VARCHAR(100),                  -- HIV, HBV, HCV, Syphilis, HTLV, etc.
  method          VARCHAR(100),                  -- ELISA, NAT, RPR, TPHA
  mandatory       TINYINT(1) NOT NULL DEFAULT 1,
  applies_to      ENUM('donors','patients','both') NOT NULL DEFAULT 'donors',
  is_confirmatory TINYINT(1) NOT NULL DEFAULT 0
);

-- Append-only
CREATE TABLE donation_test_result (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  donation_id     BIGINT NOT NULL,               -- FK donations
  test_code       VARCHAR(50) NOT NULL,          -- FK test_definition
  sample_id       BIGINT NOT NULL,               -- FK samples
  result          ENUM('reactive','non_reactive','indeterminate','invalid') NOT NULL,
  instrument      VARCHAR(100),
  instrument_lot  VARCHAR(100),
  s_co_ratio      DECIMAL(8,4),                  -- signal/cutoff ratio
  performed_by    BIGINT NOT NULL,               -- FK users
  reviewed_by     BIGINT NOT NULL,               -- FK users (second person)
  esign_id        BIGINT NOT NULL,               -- FK electronic_signatures
  performed_at    DATETIME(6) NOT NULL,
  -- Reactive result: DB trigger sets blood_units.status = 'quarantined' for all units from this donation
  UNIQUE (donation_id, test_code)
);
```

---

### 4.8 Crossmatch and Blood Requests

```sql
CREATE TABLE blood_requests (
  request_id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  patient_id              BIGINT NOT NULL,        -- FK patients
  branch_id               BIGINT NOT NULL,        -- FK branches
  requesting_ward_id      BIGINT,                -- FK wards
  requesting_physician_id BIGINT,                -- FK users
  component_class         ENUM('RBC','FFP','PLT','CRYO','WB','GRAN') NOT NULL,
  units_requested         SMALLINT NOT NULL,
  units_crossmatched      SMALLINT NOT NULL DEFAULT 0,
  units_transfused        SMALLINT NOT NULL DEFAULT 0,
  urgency                 ENUM('routine','urgent','emergency_mtp') NOT NULL DEFAULT 'routine',
  special_requirements_json JSON,               -- snapshot of patient requirements at request time
  requested_ts            DATETIME(6) NOT NULL,
  crossmatch_started_ts   DATETIME(6),
  crossmatch_completed_ts DATETIME(6),
  issued_ts               DATETIME(6),
  outcome                 ENUM('fulfilled','partial','unmet','cancelled') NOT NULL DEFAULT 'unmet',
  msbos_order_type        ENUM('none','type_and_screen','crossmatch'),
  ruleset_version_id      BIGINT NOT NULL        -- FK compliance_ruleset (what was active)
);

CREATE TABLE crossmatches (
  crossmatch_id           BIGINT PRIMARY KEY AUTO_INCREMENT,
  sample_id               BIGINT NOT NULL,        -- FK samples (patient's current sample)
  blood_unit_id           BIGINT NOT NULL,        -- FK blood_units
  request_id              BIGINT NOT NULL,        -- FK blood_requests
  method                  ENUM('immediate_spin','AHG','electronic') NOT NULL,
  result                  ENUM('compatible','incompatible','electronic_release','invalid') NOT NULL,
  antibody_screen_result  ENUM('negative','positive'),
  reagent_lot             VARCHAR(100),
  tech_id                 BIGINT NOT NULL,        -- FK users
  verified_by             BIGINT,                -- FK users
  performed_at            DATETIME(6) NOT NULL,
  electronic_eligibility_snapshot JSON,          -- rules evaluated for e-XM
  esign_id                BIGINT NOT NULL        -- FK electronic_signatures
);

CREATE TABLE emergency_release (
  id                      BIGINT PRIMARY KEY AUTO_INCREMENT,
  request_id              BIGINT NOT NULL,        -- FK blood_requests
  patient_id              BIGINT NOT NULL,        -- FK patients
  units_json              JSON NOT NULL,          -- list of unit_ids released
  physician_id            BIGINT NOT NULL,        -- FK users
  justification           TEXT NOT NULL,
  release_datetime        DATETIME(6) NOT NULL,
  release_esign_id        BIGINT NOT NULL,        -- FK electronic_signatures
  retrospective_xm_status ENUM('pending','completed','incompatible_found') NOT NULL DEFAULT 'pending',
  signoff_status          ENUM('pending','signed_off') NOT NULL DEFAULT 'pending',
  signoff_physician_id    BIGINT,                -- FK users
  signoff_at              DATETIME(6),
  signoff_esign_id        BIGINT                 -- FK electronic_signatures
);

CREATE TABLE msbos (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  procedure_code  VARCHAR(100) NOT NULL,
  branch_id       BIGINT,                        -- FK branches (null = system-wide)
  order_type      ENUM('none','type_and_screen','crossmatch') NOT NULL,
  units_count     SMALLINT NOT NULL DEFAULT 0,
  UNIQUE (procedure_code, branch_id)
);

CREATE TABLE issue_transactions (
  issue_id        BIGINT PRIMARY KEY AUTO_INCREMENT,
  blood_unit_id   BIGINT NOT NULL,               -- FK blood_units
  patient_id      BIGINT NOT NULL,               -- FK patients
  request_id      BIGINT NOT NULL,               -- FK blood_requests
  crossmatch_id   BIGINT,                        -- FK crossmatches (null for emergency release)
  emergency_release_id BIGINT,                  -- FK emergency_release (null for standard)
  issued_by       BIGINT NOT NULL,               -- FK users
  issue_esign_id  BIGINT NOT NULL,               -- FK electronic_signatures
  issued_at       DATETIME(6) NOT NULL,
  intended_branch BIGINT NOT NULL,               -- FK branches
  abo_check_passed TINYINT(1) NOT NULL
);
```

---

### 4.9 Unit State Machine

```sql
CREATE TABLE unit_state_transitions (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  from_status     VARCHAR(30) NOT NULL,
  to_status       VARCHAR(30) NOT NULL,
  requires_permission VARCHAR(100),              -- permission code required
  guard_rule      VARCHAR(500),                  -- description of additional guard
  UNIQUE (from_status, to_status)
);

-- Append-only: every status change ever
CREATE TABLE unit_status_events (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  unit_id         BIGINT NOT NULL,               -- FK blood_units
  from_status     VARCHAR(30) NOT NULL,
  to_status       VARCHAR(30) NOT NULL,
  reason          VARCHAR(500),
  actor           BIGINT NOT NULL,               -- FK users
  esign_id        BIGINT,                        -- FK electronic_signatures (if required)
  occurred_at     DATETIME(6) NOT NULL           -- server-side UTC only
);
```

---

### 4.10 Cold Chain

```sql
CREATE TABLE component_storage_spec (
  component_class             ENUM('RBC','FFP','PLT','CRYO','WB','GRAN') PRIMARY KEY,
  storage_temp_min_c          DECIMAL(4,1) NOT NULL,
  storage_temp_max_c          DECIMAL(4,1) NOT NULL,
  transport_temp_min_c        DECIMAL(4,1),
  transport_temp_max_c        DECIMAL(4,1),
  requires_agitation          TINYINT(1) NOT NULL DEFAULT 0,
  agitation_max_interruption_min SMALLINT,
  frozen_threshold_c          DECIMAL(4,1),
  shelf_life_hours            SMALLINT NOT NULL,
  max_temp_excursion_min      SMALLINT NOT NULL DEFAULT 30,
  source_standard             VARCHAR(200)
);

CREATE TABLE storage_equipment (
  equipment_id    BIGINT PRIMARY KEY AUTO_INCREMENT,
  name            VARCHAR(200) NOT NULL,
  type            ENUM('fridge','platelet_agitator','freezer','ult_freezer','transport_cooler','validated_shipper') NOT NULL,
  sensor_id       VARCHAR(100) UNIQUE,
  branch_id       BIGINT NOT NULL,               -- FK branches
  component_class_allowed ENUM('RBC','FFP','PLT','CRYO','WB','GRAN','MIXED'),
  calibration_due DATE,
  status          ENUM('active','maintenance','decommissioned') NOT NULL DEFAULT 'active',
  location        VARCHAR(200)
);

CREATE TABLE temperature_log (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  equipment_id    BIGINT NOT NULL,               -- FK storage_equipment
  recorded_at     DATETIME(6) NOT NULL,
  temp_c          DECIMAL(5,2) NOT NULL,
  humidity_pct    DECIMAL(5,2),
  agitation_ok    TINYINT(1),
  source          ENUM('sensor','manual') NOT NULL,
  reading_uuid    CHAR(36) NOT NULL UNIQUE       -- idempotency key
  -- Partition by recorded_at monthly. Archive after 2 years (keep summary).
);

CREATE TABLE sensor_health (
  sensor_id               VARCHAR(100) PRIMARY KEY,
  equipment_id            BIGINT NOT NULL,        -- FK storage_equipment
  last_seen_at            DATETIME(6),
  expected_interval_sec   SMALLINT NOT NULL DEFAULT 300,
  status                  ENUM('ok','late','offline') NOT NULL DEFAULT 'ok'
);

CREATE TABLE temperature_excursion (
  excursion_id    BIGINT PRIMARY KEY AUTO_INCREMENT,
  equipment_id    BIGINT NOT NULL,               -- FK storage_equipment
  started_at      DATETIME(6) NOT NULL,
  ended_at        DATETIME(6),
  max_temp_c      DECIMAL(5,2),
  min_temp_c      DECIMAL(5,2),
  auto_quarantine TINYINT(1) NOT NULL DEFAULT 1,
  disposition     ENUM('return_to_stock','quarantine','discard'),
  disposition_by  BIGINT,                        -- FK users (must be medical_director role)
  disposition_at  DATETIME(6),
  justification   TEXT,
  esign_id        BIGINT                         -- FK electronic_signatures
);

CREATE TABLE excursion_unit_link (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  excursion_id    BIGINT NOT NULL,               -- FK temperature_excursion
  blood_unit_id   BIGINT NOT NULL,               -- FK blood_units
  auto_quarantined TINYINT(1) NOT NULL DEFAULT 1
);

CREATE TABLE equipment_alarm (
  alarm_id        BIGINT PRIMARY KEY AUTO_INCREMENT,
  equipment_id    BIGINT NOT NULL,               -- FK storage_equipment
  alarm_type      ENUM('high_temp','low_temp','agitation_failure','power_loss','door_open','sensor_disconnect','calibration_overdue','battery_low') NOT NULL,
  triggered_at    DATETIME(6) NOT NULL,
  cleared_at      DATETIME(6),
  ack_by          BIGINT,                        -- FK users
  ack_at          DATETIME(6),
  escalation_level TINYINT NOT NULL DEFAULT 1   -- 1=staff, 2=supervisor, 3=on-call
);

CREATE TABLE unit_return_check (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  blood_unit_id   BIGINT NOT NULL,               -- FK blood_units
  issue_id        BIGINT NOT NULL,               -- FK issue_transactions
  issued_at       DATETIME(6) NOT NULL,
  returned_at     DATETIME(6) NOT NULL,
  minutes_out     SMALLINT NOT NULL,
  measured_return_temp_c DECIMAL(5,2),
  rule_applied    ENUM('30_minute_rule','validated_temp') NOT NULL,
  decision        ENUM('return_to_stock','discard') NOT NULL,
  decided_by      BIGINT NOT NULL,               -- FK users
  esign_id        BIGINT NOT NULL                -- FK electronic_signatures
);

CREATE TABLE shipment_cold_chain (
  shipment_id     BIGINT PRIMARY KEY AUTO_INCREMENT,
  transfer_id     BIGINT NOT NULL,               -- FK transfers
  logger_id       VARCHAR(100),
  origin_branch_id      BIGINT NOT NULL,         -- FK branches
  destination_branch_id BIGINT NOT NULL,         -- FK branches
  departed_at     DATETIME(6) NOT NULL,
  arrived_at      DATETIME(6),
  logger_data_json JSON,
  excursion_detected TINYINT(1) NOT NULL DEFAULT 0
);
```

---

### 4.11 Hemovigilance

```sql
CREATE TABLE transfusion_administration (
  admin_id        BIGINT PRIMARY KEY AUTO_INCREMENT,
  blood_unit_id   BIGINT NOT NULL,               -- FK blood_units
  patient_id      BIGINT NOT NULL,               -- FK patients
  issue_id        BIGINT NOT NULL,               -- FK issue_transactions
  bedside_verify_pass TINYINT(1) NOT NULL,
  patient_scan_id VARCHAR(100),                 -- scanned wristband
  unit_scan_did   CHAR(12),                     -- scanned unit DID
  admin_staff_1   BIGINT NOT NULL,               -- FK users
  admin_staff_2   BIGINT,                        -- FK users (second checker)
  start_at        DATETIME(6),
  completed_at    DATETIME(6),
  volume_given_ml SMALLINT,
  outcome         ENUM('completed','stopped_adverse_event','returned','partial') NOT NULL,
  vitals_json     JSON,                          -- pre/during/post vital signs
  branch_id       BIGINT NOT NULL                -- FK branches
);

CREATE TABLE transfusion_reaction (
  reaction_id     BIGINT PRIMARY KEY AUTO_INCREMENT,
  admin_id        BIGINT NOT NULL,               -- FK transfusion_administration
  patient_id      BIGINT NOT NULL,               -- FK patients
  reaction_category ENUM(
    'AHTR','DHTR','FNHTR','allergic','anaphylactic',
    'TACO','TRALI','TAD','TA_GVHD','PTP','sepsis','TTI','hypotensive','other'
  ) NOT NULL,
  onset_timing    ENUM('during','within_1h','within_24h','delayed') NOT NULL,
  severity_grade  TINYINT NOT NULL CHECK (severity_grade BETWEEN 0 AND 4),
  imputability    ENUM('definite','probable','possible','unlikely','excluded','not_assessable') NOT NULL,
  signs_symptoms_json JSON,
  lab_results_json    JSON,
  dat_result      ENUM('positive','negative','not_done'),
  reportable_to_authority TINYINT(1) NOT NULL DEFAULT 0,
  report_ref      VARCHAR(100),
  reported_at     DATETIME(6),
  reported_by     BIGINT,                        -- FK users
  recorded_by     BIGINT NOT NULL,               -- FK users
  recorded_at     DATETIME(6) NOT NULL
);

CREATE TABLE reaction_unit_link (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  reaction_id     BIGINT NOT NULL,               -- FK transfusion_reaction
  blood_unit_id   BIGINT NOT NULL,               -- FK blood_units
  role            ENUM('implicated','co_administered') NOT NULL
);
```

---

### 4.12 Recall and Look-Back

```sql
CREATE TABLE recalls (
  recall_id       BIGINT PRIMARY KEY AUTO_INCREMENT,
  trigger         ENUM('donor_seroconversion','positive_repeat_test','recipient_reaction','equipment_failure','recall_notice') NOT NULL,
  trigger_donor_id     BIGINT,                  -- FK donors
  trigger_donation_id  BIGINT,                  -- FK donations
  marker          VARCHAR(100),                 -- HIV, HBV, HCV, HTLV, syphilis, bacterial
  opened_at       DATETIME(6) NOT NULL,
  opened_by       BIGINT NOT NULL,              -- FK users
  esign_id        BIGINT NOT NULL,              -- FK electronic_signatures
  status          ENUM('open','tracing','quarantined','dispositioned','closed','reported_to_authority') NOT NULL DEFAULT 'open',
  closed_at       DATETIME(6),
  close_esign_id  BIGINT                        -- FK electronic_signatures (medical director)
);

CREATE TABLE recall_items (
  id                      BIGINT PRIMARY KEY AUTO_INCREMENT,
  recall_id               BIGINT NOT NULL,       -- FK recalls
  blood_unit_id           BIGINT NOT NULL,       -- FK blood_units
  role                    ENUM('implicated_component','co_component','recipient_traced') NOT NULL,
  disposition             ENUM('quarantined','destroyed','already_transfused_recipient_notified','not_found'),
  recipient_patient_id    BIGINT,                -- FK patients (if already transfused)
  clinical_notified_at    DATETIME(6),
  notified_by             BIGINT                 -- FK users
);
```

---

### 4.13 Labeling

```sql
CREATE TABLE label_templates (
  template_id     BIGINT PRIMARY KEY AUTO_INCREMENT,
  version         VARCHAR(20) NOT NULL,
  component_class ENUM('RBC','FFP','PLT','CRYO','WB','GRAN'),
  barcode_symbology ENUM('Code128','Codabar') NOT NULL DEFAULT 'Code128',
  fields_json     JSON NOT NULL,
  content_checksum CHAR(64) NOT NULL,            -- SHA-256 of the template
  approved_by     BIGINT NOT NULL,               -- FK users
  approved_at     DATETIME(6) NOT NULL,
  active          TINYINT(1) NOT NULL DEFAULT 1
);

CREATE TABLE label_print_log (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  blood_unit_id   BIGINT NOT NULL,               -- FK blood_units
  template_id     BIGINT NOT NULL,               -- FK label_templates
  did             CHAR(12) NOT NULL,
  printed_by      BIGINT NOT NULL,               -- FK users
  printed_at      DATETIME(6) NOT NULL,
  printer_id      VARCHAR(100),
  print_success   TINYINT(1) NOT NULL DEFAULT 1
);

CREATE TABLE labeling_profile (
  profile_id      BIGINT PRIMARY KEY AUTO_INCREMENT,
  standard        ENUM('CUSTOM_CODE128','CODABAR') NOT NULL DEFAULT 'CUSTOM_CODE128',
  iccbba_fin      CHAR(13)                       -- null until ISBT 128 adopted
);
```

---

### 4.14 Compliance Rule Engine

```sql
CREATE TABLE compliance_jurisdiction (
  jurisdiction_id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name            VARCHAR(200) NOT NULL,
  country_code    CHAR(2) NOT NULL UNIQUE
);

CREATE TABLE compliance_ruleset (
  ruleset_id      BIGINT PRIMARY KEY AUTO_INCREMENT,
  jurisdiction_id BIGINT NOT NULL,               -- FK compliance_jurisdiction
  version         VARCHAR(20) NOT NULL,
  effective_from  DATE NOT NULL,
  effective_to    DATE,
  status          ENUM('draft','active','superseded') NOT NULL DEFAULT 'draft',
  locked          TINYINT(1) NOT NULL DEFAULT 0, -- once active: lock prevents edits
  created_by      BIGINT NOT NULL,               -- FK users
  UNIQUE (jurisdiction_id, version)
);

CREATE TABLE compliance_rule (
  rule_id         BIGINT PRIMARY KEY AUTO_INCREMENT,
  ruleset_id      BIGINT NOT NULL,               -- FK compliance_ruleset
  rule_kind       ENUM('AGE','WEIGHT','HB','BP_SYSTOLIC','BP_DIASTOLIC','PULSE','DONATION_INTERVAL','DEFERRAL','REQUIRED_TEST','RETENTION','LABEL_FORMAT','MAX_VOLUME') NOT NULL,
  applies_to      ENUM('donor_eligibility','unit_release','record_retention','labeling') NOT NULL,
  operator        ENUM('gt','lt','gte','lte','eq','between','required','forbidden') NOT NULL,
  threshold_value DECIMAL(10,4),
  threshold_value_2 DECIMAL(10,4),              -- for 'between'
  threshold_unit  VARCHAR(50),                   -- years, kg, g_dL, mmHg, days
  applies_predicate JSON,                        -- extra conditions (e.g. sex='F')
  citation        VARCHAR(500) NOT NULL          -- law/standard reference
);

CREATE TABLE retention_policy (
  record_class    VARCHAR(100) PRIMARY KEY,
  min_retention_years SMALLINT NOT NULL,
  indefinite      TINYINT(1) NOT NULL DEFAULT 0,
  legal_authority VARCHAR(500)
);

CREATE TABLE disposition_decision (
  decision_id         BIGINT PRIMARY KEY AUTO_INCREMENT,
  entity_type         VARCHAR(50) NOT NULL,
  entity_id           BIGINT NOT NULL,
  ruleset_version_id  BIGINT NOT NULL,           -- FK compliance_ruleset
  decided_at          DATETIME(6) NOT NULL,
  decided_by          BIGINT NOT NULL            -- FK users
);

CREATE TABLE validation_artifact (
  artifact_id     BIGINT PRIMARY KEY AUTO_INCREMENT,
  artifact_type   ENUM('IQ','OQ','PQ','VMP','traceability_matrix','change_record','DPIA','SOP') NOT NULL,
  version         VARCHAR(20) NOT NULL,
  description     TEXT,
  file_ref        VARCHAR(500),
  approved_by     BIGINT,                        -- FK users
  approved_at     DATETIME(6),
  branch_id       BIGINT                         -- FK branches
);
```

---

### 4.15 Audit, Signatures, and Chain of Custody

```sql
-- INSERT-only. App DB account has no UPDATE or DELETE on this table.
-- DB trigger rejects UPDATE/DELETE attempts via SIGNAL SQLSTATE '45000'.
CREATE TABLE audit_logs (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  seq             BIGINT NOT NULL UNIQUE,         -- monotonic, no gaps
  occurred_at_utc DATETIME(6) NOT NULL,
  actor_user_id   BIGINT NOT NULL,               -- FK users
  action          VARCHAR(100) NOT NULL,          -- e.g. 'unit.status_changed'
  action_meaning  VARCHAR(500),
  entity_table    VARCHAR(100) NOT NULL,
  entity_id       BIGINT NOT NULL,
  before_json     JSON,
  after_json      JSON,
  branch_id       BIGINT,                        -- FK branches
  ruleset_version_id BIGINT,                     -- FK compliance_ruleset
  prev_hash       CHAR(64) NOT NULL,             -- SHA-256 of previous row
  row_hash        CHAR(64) NOT NULL,             -- SHA-256(seq||occurred_at||actor||action||entity_table||entity_id||before_json||after_json||prev_hash)
  esign_id        BIGINT,                        -- FK electronic_signatures (if action was signed)
  source          ENUM('online','offline_replay') NOT NULL DEFAULT 'online'
  -- row_hash computed server-side ONLY; never accept caller-supplied hash
);

CREATE TABLE audit_chain_anchors (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  chain_head_hash CHAR(64) NOT NULL,
  chain_head_seq  BIGINT NOT NULL,
  anchored_at     DATETIME(6) NOT NULL,
  tsa_token       TEXT,                          -- RFC 3161 timestamp token (base64)
  server_signature TEXT                          -- app-level signature of the hash
);

CREATE TABLE electronic_signatures (
  esign_id        BIGINT PRIMARY KEY AUTO_INCREMENT,
  signer_user_id  BIGINT NOT NULL,               -- FK users
  signed_at_utc   DATETIME(6) NOT NULL,          -- server time only
  meaning         ENUM('reviewed','approved','released','verified','quarantine_release','recalled','rejected','witnessed') NOT NULL,
  auth_method     ENUM('password_reauth','mfa_reauth') NOT NULL,
  reauth_at       DATETIME(6) NOT NULL,
  signed_payload_hash CHAR(64) NOT NULL,         -- SHA-256 of the record being signed
  audit_log_id    BIGINT,                        -- FK audit_logs
  manifested_name VARCHAR(200) NOT NULL          -- printed name at time of signing
);
```

---

### 4.16 Privacy and Consent

```sql
CREATE TABLE subject_identity (
  subject_id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  subject_type            ENUM('donor','patient') NOT NULL,
  name_enc                TEXT,                  -- AES-256-GCM encrypted
  national_id_enc         TEXT,                  -- AES-256-GCM encrypted
  contact_enc             TEXT,                  -- AES-256-GCM encrypted
  name_blind_index        CHAR(64),              -- HMAC-SHA256 of normalized name
  national_id_blind_index CHAR(64),              -- HMAC-SHA256 of normalized ID
  data_key_ref            BIGINT                 -- FK key_refs
);

CREATE TABLE key_refs (
  key_ref_id      BIGINT PRIMARY KEY AUTO_INCREMENT,
  subject_id      BIGINT NOT NULL,               -- FK subject_identity
  wrapped_key     TEXT NOT NULL,                 -- data key, wrapped by KMS master key
  key_version     VARCHAR(50) NOT NULL,
  kms_key_id      VARCHAR(200) NOT NULL,         -- reference to key in KMS (Vault)
  created_at      DATETIME(6) NOT NULL,
  rotated_at      DATETIME(6)
);

-- Append-only
CREATE TABLE consent_records (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  subject_id      BIGINT NOT NULL,               -- FK subject_identity
  subject_type    ENUM('donor','patient') NOT NULL,
  purpose         VARCHAR(200) NOT NULL,
  lawful_basis    ENUM('consent','vital_interest','healthcare_provision','legal_obligation') NOT NULL,
  notice_version  VARCHAR(20) NOT NULL,
  captured_at     DATETIME(6) NOT NULL,
  captured_by     BIGINT NOT NULL,               -- FK users
  withdrawn_at    DATETIME(6),
  withdrawal_note TEXT
);

CREATE TABLE dsr_requests (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  subject_id      BIGINT NOT NULL,               -- FK subject_identity
  request_type    ENUM('access','rectify','erase','restrict','portability') NOT NULL,
  status          ENUM('received','processing','completed','refused') NOT NULL DEFAULT 'received',
  requested_at    DATETIME(6) NOT NULL,
  handled_by      BIGINT,                        -- FK users
  completed_at    DATETIME(6),
  outcome         TEXT,
  refusal_reason  TEXT
);
```

---

### 4.17 Analytics and Forecasting

```sql
-- Canonical append-only event stream (feeds state machine, audit, analytics, sync)
CREATE TABLE unit_event_log (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  unit_id         BIGINT NOT NULL,               -- FK blood_units
  event_type      ENUM('collected','tested','available','reserved','crossmatched','issued','transfused','returned','discarded','expired','transferred','recalled','wasted') NOT NULL,
  event_ts        DATETIME(6) NOT NULL,
  actor           BIGINT NOT NULL,               -- FK users
  branch_id       BIGINT NOT NULL,               -- FK branches
  related_request_id BIGINT,                    -- FK blood_requests
  reason_code_id  BIGINT                         -- FK reason_codes
);

CREATE TABLE reason_codes (
  code            VARCHAR(50) PRIMARY KEY,
  category        ENUM('wastage','deferral','return','discard','transfer','recall') NOT NULL,
  description     VARCHAR(500) NOT NULL
);

CREATE TABLE demand_fact_daily (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  fact_date       DATE NOT NULL,
  branch_id       BIGINT NOT NULL,               -- FK branches
  component_class ENUM('RBC','FFP','PLT','CRYO','WB','GRAN') NOT NULL,
  abo             ENUM('A','B','AB','O'),
  rh              ENUM('pos','neg'),
  units_issued    SMALLINT NOT NULL DEFAULT 0,
  units_requested SMALLINT NOT NULL DEFAULT 0,
  units_expired   SMALLINT NOT NULL DEFAULT 0,
  units_wasted    SMALLINT NOT NULL DEFAULT 0,
  stock_at_eod    SMALLINT NOT NULL DEFAULT 0,
  generated_at    DATETIME(6) NOT NULL,
  UNIQUE (fact_date, branch_id, component_class, abo, rh)
);

CREATE TABLE forecast (
  forecast_id     BIGINT PRIMARY KEY AUTO_INCREMENT,
  branch_id       BIGINT NOT NULL,               -- FK branches
  component_class ENUM('RBC','FFP','PLT','CRYO','WB','GRAN') NOT NULL,
  abo             ENUM('A','B','AB','O'),
  rh              ENUM('pos','neg'),
  forecast_date   DATE NOT NULL,
  predicted_units DECIMAL(6,2) NOT NULL,
  safety_stock_units DECIMAL(6,2) NOT NULL,
  model_used      ENUM('moving_avg','ses','holt_winters_additive') NOT NULL,
  generated_at    DATETIME(6) NOT NULL
);

CREATE TABLE forecast_accuracy (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  forecast_id     BIGINT NOT NULL,               -- FK forecast
  actual_units    SMALLINT NOT NULL,
  mase            DECIMAL(6,4),                  -- Mean Absolute Scaled Error
  evaluated_at    DATETIME(6) NOT NULL
);

CREATE TABLE kpi_daily (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  kpi_date        DATE NOT NULL,
  branch_id       BIGINT NOT NULL,               -- FK branches
  component_class ENUM('RBC','FFP','PLT','CRYO','WB','GRAN') NOT NULL,
  ct_ratio        DECIMAL(6,3),                  -- crossmatch:transfuse ratio (target ≤ 2.0)
  wastage_pct     DECIMAL(5,2),
  stock_out_events SMALLINT NOT NULL DEFAULT 0,
  days_of_supply  DECIMAL(5,2),
  near_expiry_units SMALLINT NOT NULL DEFAULT 0,
  tat_request_to_issue_min DECIMAL(8,2),
  generated_at    DATETIME(6) NOT NULL,
  UNIQUE (kpi_date, branch_id, component_class)
);

CREATE TABLE config_targets (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  branch_id       BIGINT,                        -- FK branches (null = system-wide)
  component_class ENUM('RBC','FFP','PLT','CRYO','WB','GRAN') NOT NULL,
  target_days_of_supply DECIMAL(5,2) NOT NULL DEFAULT 3.0,
  max_wastage_pct DECIMAL(5,2) NOT NULL DEFAULT 5.0,
  near_expiry_alert_hours SMALLINT NOT NULL DEFAULT 72,
  abo_distribution_json JSON,                    -- expected ABO distribution for region
  safety_quantile DECIMAL(4,3) NOT NULL DEFAULT 0.950
);
```

---

### 4.18 Multi-Branch and Sync

```sql
CREATE TABLE transfers (
  transfer_id     BIGINT PRIMARY KEY AUTO_INCREMENT,
  blood_unit_id   BIGINT NOT NULL,               -- FK blood_units
  from_branch_id  BIGINT NOT NULL,               -- FK branches
  to_branch_id    BIGINT NOT NULL,               -- FK branches
  initiated_by    BIGINT NOT NULL,               -- FK users
  initiated_at    DATETIME(6) NOT NULL,
  approved_by     BIGINT,                        -- FK users
  approved_at     DATETIME(6),
  dispatched_at   DATETIME(6),
  received_at     DATETIME(6),
  received_by     BIGINT,                        -- FK users
  status          ENUM('requested','approved','in_transit','received','rejected','cancelled') NOT NULL DEFAULT 'requested',
  reason          VARCHAR(500),
  cold_chain_ok   TINYINT(1)
);

CREATE TABLE unit_ownership_log (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  unit_id         BIGINT NOT NULL,               -- FK blood_units
  from_branch_id  BIGINT,                        -- FK branches
  to_branch_id    BIGINT NOT NULL,               -- FK branches
  transferred_at  DATETIME(6) NOT NULL,
  transfer_id     BIGINT                         -- FK transfers
);

CREATE TABLE sync_events (
  event_uuid      CHAR(36) PRIMARY KEY,
  branch_id       BIGINT NOT NULL,               -- FK branches
  entity_din      CHAR(12),                      -- blood unit DID
  action          VARCHAR(100) NOT NULL,
  prior_version   INT NOT NULL,
  payload_json    JSON NOT NULL,
  device_ts       DATETIME(6) NOT NULL,
  server_received_ts DATETIME(6) NOT NULL,
  apply_result    ENUM('applied','rejected','conflict') NOT NULL
);

CREATE TABLE sync_conflicts (
  conflict_id     BIGINT PRIMARY KEY AUTO_INCREMENT,
  event_uuid_a    CHAR(36) NOT NULL,             -- FK sync_events
  event_uuid_b    CHAR(36),                      -- FK sync_events
  blood_unit_id   BIGINT NOT NULL,               -- FK blood_units
  conflict_type   VARCHAR(200) NOT NULL,
  status          ENUM('pending','resolved') NOT NULL DEFAULT 'pending',
  resolved_by     BIGINT,                        -- FK users
  resolved_at     DATETIME(6),
  resolution      TEXT
  -- Never auto-merge unit lifecycle conflicts. Always human resolution.
);

CREATE TABLE inventory_change_feed (
  seq             BIGINT PRIMARY KEY AUTO_INCREMENT,
  branch_id       BIGINT NOT NULL,               -- FK branches
  event_type      VARCHAR(100) NOT NULL,
  entity_id       BIGINT NOT NULL,
  occurred_at     DATETIME(6) NOT NULL
);
```

---

## 5. State Machines

### 5.1 Blood Unit Status Machine

All transitions enforced by a `BEFORE UPDATE` trigger on `blood_units`. Illegal transitions fire `SIGNAL SQLSTATE '45000'`.

```
INITIAL: quarantined
            ↓ [all tests started]
        in_testing
            ↓ [all TTI tests non-reactive + e-signed]
        available   ← also: returned_to_stock
            ↓ [reservation placed]
        reserved    ← can return to available (reservation expired/released)
            ↓ [crossmatch completed]
        crossmatched ← can return to reserved/available (crossmatch cancelled)
            ↓ [issued with e-signature]
        issued
            ↓ [transfusion completed]         ↓ [returned within rule]   ↓ [not returned]
        transfused                      returned_to_stock            wasted

EXCEPTION STATES (reachable from most non-terminal states):
        expired        (expiry_datetime ≤ NOW() — DB trigger auto-sets)
        failed_qc      (quality failure)
        recalled       (recall_id created)
        quarantined_holdback (hold pending investigation)
        transferred_out → in_transit → [received at destination]
        destroyed      (terminal, after recall/failed_qc/wasted/expired)
```

### 5.2 Blood Request State
`pending` → `in_progress` (T&S started) → `crossmatched` (units XM'd) → `issued` → `closed` | `partial` | `cancelled`

### 5.3 Recall State
`open` → `tracing` → `quarantined` → `dispositioned` → `closed` | `reported_to_authority`

---

## 6. Safety Guards (Non-Negotiable)

These are enforced both in application code AND as database-level triggers. The database layer rejects the action even if the application is compromised or buggy.

| Guard | Enforcement |
|-------|-------------|
| Reactive TTI result → unit cannot be released | DB trigger on `donation_test_result`: if result = 'reactive' → UPDATE blood_units SET status='quarantined' WHERE donation_id = this donation_id |
| Expired unit cannot be issued | DB trigger on `issue_transactions` INSERT: check blood_units.expiry_datetime > NOW() |
| Quarantined/recalled/failed_qc cannot be issued | Transition lookup in `unit_state_transitions` consulted by BEFORE UPDATE trigger |
| Double-issue prevention | `SELECT ... FOR UPDATE` on blood_units row inside explicit transaction; status must be 'crossmatched' at commit time |
| ABO discrepancy blocks e-XM | Trigger on `patient_blood_groups`: if is_discrepant = 1 → prevent any crossmatch.method = 'electronic' for that patient |
| Patient antibody history drives issue | Application checks patient_antibodies before unit selection; trigger on issue_transactions verifies unit.antigen_negative_set satisfies active antibody constraints |
| SoD at release | Application checks: issued_by NOT IN (SELECT collected_by, tested_by, interpreted_by FROM blood_units WHERE unit_id = this_unit) |
| Sample validity | Application and trigger: crossmatch blocked if sample.validity_expiry < NOW() |
| Two ABO determinations required | Application blocks group-specific issue if patient_blood_groups count for patient < 2 or first determination has no verified_by |

---

## 7. Security Requirements

### 7.1 Authentication
- **REQ-SEC-01:** Password hashing: `password_hash($password, PASSWORD_ARGON2ID, ['memory_cost' => 65536, 'time_cost' => 4, 'threads' => 1])`. Fallback: bcrypt cost ≥ 12.
- **REQ-SEC-02:** MFA mandatory for: unit.release, user.manage, config.edit, break_glass, medical_director roles. Algorithm: TOTP RFC 6238 (30-second window, HMAC-SHA1 minimum, SHA-256 preferred). Library: PHP `OTPHP` (MIT license, free).
- **REQ-SEC-03:** No forced password rotation. Rotate only on suspected compromise (NIST 800-63B). Minimum length 12 characters. Check against known-breached password list.
- **REQ-SEC-04:** Account lockout: 5 failed attempts → 15-minute lockout. Exponential backoff per subsequent failure. Per-account + per-IP rate limiting. Lockout is time-based, not permanent (to avoid DoS).

### 7.2 Sessions
- **REQ-SEC-05:** Server-side sessions stored in database. Idle timeout: 15 minutes for release/admin roles, 30 minutes for standard roles. Absolute lifetime: 8 hours.
- **REQ-SEC-06:** Session ID regenerated on login and on privilege change.
- **REQ-SEC-07:** Cookies: `HttpOnly; Secure; SameSite=Strict`. Short expiry. No session data in cookie beyond session token.
- **REQ-SEC-08:** Re-authentication required before every electronic signature event (regardless of session age).

### 7.3 Transport Security
- **REQ-SEC-09:** TLS 1.2 minimum on all connections. TLS 1.3 preferred. HSTS header. Disable TLS 1.0, TLS 1.1, all RC4/DES/3DES ciphers.
- **REQ-SEC-10:** MySQL connection: `REQUIRE SSL` on all application DB accounts. TLS for app-to-DB connection.
- **REQ-SEC-11:** Inter-branch sync channels: mTLS (mutual TLS) — both client and server present certificates.

### 7.4 Encryption at Rest
- **REQ-SEC-12:** Application-level AES-256-GCM (via PHP `libsodium` — built in since PHP 7.2) on all direct identifiers in `subject_identity`: name, national_id, contact.
- **REQ-SEC-13:** Blind indexes (HMAC-SHA256 of normalized value) for name and national_id to support exact-match lookup without decrypting.
- **REQ-SEC-14:** Per-record data encryption keys. Each key is wrapped (encrypted) by a master key held in HashiCorp Vault (free, open source). The wrapped key is stored in `key_refs`. Plaintext keys are never written to the database.
- **REQ-SEC-15:** Key rotation: when master key is rotated, re-wrap all data keys. No re-encryption of data required.

### 7.5 Application Security
- **REQ-SEC-16:** All database queries use prepared statements (PDO or MySQLi with bound parameters). No string-interpolated SQL.
- **REQ-SEC-17:** All output HTML-encoded via `htmlspecialchars()`. Content Security Policy header.
- **REQ-SEC-18:** CSRF tokens on all state-mutating forms and AJAX requests.
- **REQ-SEC-19:** File uploads: MIME type validation server-side; store outside webroot; no execution permissions.

---

## 8. Cold Chain Requirements

- **REQ-CC-01:** A dedicated background worker process (not web request) checks sensor heartbeats every 60 seconds. If any sensor has not reported within `expected_interval_sec`, the worker sets `sensor_health.status = 'offline'` and creates an `equipment_alarm` with type `sensor_disconnect`. Silence ≠ normal. Silence = alarm.
- **REQ-CC-02:** Background worker evaluates every temperature reading against `component_storage_spec`. Excursion detected → create `temperature_excursion` record → bulk-quarantine all units in that equipment → create `equipment_alarm` → escalate alert.
- **REQ-CC-03:** Temperature excursion disposition (return to stock / quarantine / discard) requires medical director role + electronic signature. No automatic return-to-stock without human decision.
- **REQ-CC-04:** Platelet agitation failure: if `agitation_ok = 0` for longer than `agitation_max_interruption_min` → same excursion workflow.
- **REQ-CC-05:** Alert escalation: if alarm not acknowledged within 15 minutes → escalate to level 2 (supervisor). 30 minutes unacknowledged → level 3 (on-call). Out-of-band (SMS or voice call) for level 2+.
- **REQ-CC-06:** `temperature_log` partitioned by month. Automated archival after 24 months (summarized to daily min/max/avg). Original per-reading data retained for 7 years minimum.
- **REQ-CC-07:** Transport (shipment): data logger embedded in transport box. Logger data uploaded on arrival. If excursion detected in transit → units enter return-check workflow, not direct stock.

---

## 9. Compliance Engine Requirements

- **REQ-COMP-01:** Each branch is bound to exactly one active `compliance_ruleset`. One installation may span multiple jurisdictions (branches in different countries).
- **REQ-COMP-02:** Rulesets are versioned and immutable once `status = 'active'`. Editing an active ruleset is forbidden. Changes require creating a new version.
- **REQ-COMP-03:** Donor eligibility evaluation at each donation: the engine evaluates all `compliance_rule` rows for the branch's active ruleset against the donor's data. Pass all = eligible. Fail any = ineligible with coded reason.
- **REQ-COMP-04:** Every disposition decision records which `ruleset_version_id` was active, creating a permanent audit link.
- **REQ-COMP-05:** Safety invariants are hardcoded (see §6) and cannot be overridden by compliance rules. Rules can only tighten safety constraints — never loosen them below the hardcoded floor.
- **REQ-COMP-06:** Retention: the system enforces `retention_policy` rows. The nightly purge job refuses to delete any record class before `min_retention_years` has elapsed from the latest relevant event date. Default strictest (30 years for traceability).

---

## 10. Interoperability Requirements

### 10.1 HL7 v2
- **REQ-IO-01:** HL7 v2 messages over MLLP (Minimal Lower Layer Protocol) via Mirth Connect (free, open source). The PHP app does not handle raw MLLP sockets.
- **REQ-IO-02:** Inbound: ADT^A01/A08/A28/A31 (patient demographics), OML^O21 (order), SPM (specimen).
- **REQ-IO-03:** Outbound: ORU^R01 (results), OUL^R22, BPO/BTX (blood product order/transfusion), TCD (test code details), ACK.
- **REQ-IO-04:** Blood bank segments: BPO (blood product order), BTX (blood product transfusion), BPX (blood product dispense status).
- **REQ-IO-05:** Mirth Connect channel maps HL7 segments to/from system tables. Each channel is versioned.

### 10.2 FHIR R4
- **REQ-IO-06:** FHIR R4 REST facade implemented in PHP as a versioned subsystem. Serves: `Patient`, `ServiceRequest`, `Specimen`, `Observation`, `DiagnosticReport`, `BiologicallyDerivedProduct`, `BiologicallyDerivedProductDispense`, `MedicationAdministration`, `Provenance`, `AuditEvent`.
- **REQ-IO-07:** `CapabilityStatement` served at `/fhir/metadata`. Versioned.
- **REQ-IO-08:** Hemovigilance data exportable as FHIR `AdverseEvent` resources.
- **REQ-IO-09:** Terminology: LOINC codes for test results (free), SNOMED CT (free for use, no registration needed for implementation), internal codes for blood components (since ISBT 128 is deferred).

### 10.3 Bedside PWA
- **REQ-IO-10:** A Progressive Web App accessible on any smartphone or tablet.
- **REQ-IO-11:** Scans patient wristband barcode and unit DID barcode (Code 128). Confirms match. Requires two staff member confirmations.
- **REQ-IO-12:** Creates `transfusion_administration` record on confirmation.
- **REQ-IO-13:** Offline mode: if network unavailable, PWA stores locally and syncs when reconnected. Critical mismatch rejection is local (no network required).

---

## 11. Audit and Traceability Requirements

- **REQ-AUD-01:** Every INSERT, UPDATE, and DELETE on any table that affects patient safety data is captured in `audit_logs` via application-layer audit writer (not DB triggers alone — triggers cannot capture the authenticated user context reliably).
- **REQ-AUD-02:** `audit_logs` is INSERT-only. The application DB account is granted `INSERT` only — no `UPDATE`, no `DELETE`. A DB trigger on `audit_logs` rejects UPDATE/DELETE via `SIGNAL SQLSTATE '45000'`.
- **REQ-AUD-03:** Hash chain: `row_hash = SHA256(CONCAT(seq, '|', occurred_at_utc, '|', actor_user_id, '|', action, '|', entity_table, '|', entity_id, '|', COALESCE(before_json,''), '|', COALESCE(after_json,''), '|', prev_hash))`. Computed exclusively server-side.
- **REQ-AUD-04:** Nightly: compute chain head hash, sign it, optionally obtain RFC 3161 timestamp token from a free TSA (e.g. DigiCert, FreeTSA.org), store in `audit_chain_anchors`. The DBA cannot silently falsify records because the nightly anchor is saved off-host.
- **REQ-AUD-05:** A chain-verification cron job recomputes the hash chain from genesis and compares to the latest anchor. Alert on any divergence.
- **REQ-AUD-06:** Audit records are permanently retained (minimum 30 years per EU directive). Archive strategy: move to partitioned cold table but keep in same hash chain; never delete.
- **REQ-AUD-07:** Electronic signatures: every release, QC pass/fail, quarantine release, recall open/close, and patient blood-group first determination requires an `electronic_signature` record. The `signed_payload_hash` ties the signature to the exact record content.
- **REQ-AUD-08:** Vein-to-vein traceability: given any `blood_unit_id`, the system can produce: the donor's identity, every test result, all processing events, all child units derived from the same donation, the recipient patient, and the transfusion outcome. This query must be available as a one-click report.

---

## 12. Analytics and Forecasting Requirements

- **REQ-ANL-01:** Background worker materializes `demand_fact_daily` and `kpi_daily` nightly from the event log.
- **REQ-ANL-02:** Three forecasting models implemented in PHP:
  1. Simple Moving Average (7-day, 14-day, 28-day windows) — baseline
  2. Simple Exponential Smoothing (SES) — handles trend
  3. Holt-Winters Additive — handles trend + weekly seasonality (best for blood demand)
- **REQ-ANL-03:** Model auto-selection: run all three on a rolling holdout window, pick the model with lowest MASE. Record which model was used in `forecast.model_used`.
- **REQ-ANL-04:** Safety stock = forecast + Z × σ(demand), where Z = inverse normal at `config_targets.safety_quantile` (default 95th percentile).
- **REQ-ANL-05:** ABO/Rh distribution target is configurable per branch per component class in `config_targets.abo_distribution_json`. Never hardcoded.
- **REQ-ANL-06:** KPI dashboard shows at minimum: wastage %, C:T ratio, days of supply, near-expiry units, stock-out events, average TAT (request to issue). All per-branch, per-component-class, date-selectable.
- **REQ-ANL-07:** Near-expiry alert: units within `config_targets.near_expiry_alert_hours` of expiry are flagged. System suggests FEFO (First Expired, First Out) allocation.

---

## 13. Multi-Branch Architecture

- **REQ-MB-01:** One authoritative central database. Branches connect to it. No peer-to-peer sync.
- **REQ-MB-02:** Unit ownership is per-branch. A branch may only act on units it exclusively owns (except cross-branch requests which follow a transfer workflow).
- **REQ-MB-03:** An offline branch (network interrupted) may issue, reserve, and crossmatch units it solely owns. It may not access or modify units owned by another branch.
- **REQ-MB-04:** Offline events are queued with idempotency UUIDs. On reconnection, replayed in order. Each replayed event is verified against current server state before applying.
- **REQ-MB-05:** Conflicts (two branches acted on the same unit during an outage) are written to `sync_conflicts` and require human resolution. Never auto-merge. The unit is quarantined until resolved.
- **REQ-MB-06:** Per-unit ownership history is maintained in `unit_ownership_log`.
- **REQ-MB-07:** Each branch may be bound to its own compliance jurisdiction and ruleset.

---

## 14. Non-Functional Requirements

| NFR | Requirement |
|-----|-------------|
| Response time | Unit availability search: < 500ms at 100 concurrent users |
| Issue transaction | < 2 seconds end-to-end including lock, crossmatch verify, audit write |
| Uptime | 99.5% minimum (single-site, no HA initially) |
| Audit write | Must not block the primary transaction. Audit is written in the same transaction; if audit fails, the primary operation fails (not silently swallowed). |
| Temperature log | Background worker must ingest and evaluate sensor data within 60 seconds of receipt |
| Data retention | 30 years minimum for traceability data (EU). 10 years minimum for blood records (FDA/WHO) |
| Backup | Daily full backup + continuous binary log. Restore drill documented quarterly |
| Scalability | Designed for single-hospital or multi-branch regional deployment. ML forecasting explicitly deferred (not needed at this scale) |
| Accessibility | Web UI: WCAG 2.1 AA minimum |
| Browser support | All modern browsers (Chrome, Firefox, Edge, Safari). IE not supported |

---

## 15. Tech Stack Decisions

| Layer | Choice | License | Reason |
|-------|--------|---------|--------|
| Backend | PHP 8.2+ | MIT/Zend | Available, familiar, adequate |
| Database | MariaDB 11+ | GPL | Better open-source TDE than MySQL Community; full MySQL compatibility |
| ORM/Query | PDO with prepared statements | Built-in | No ORM overhead; prepared statements are security baseline |
| Frontend | HTML + CSS + vanilla JS or Alpine.js | MIT | No framework overhead needed |
| Real-time (minimal) | Server-Sent Events (SSE) | Built-in HTTP | One-way push from server; no extra infra for awareness-level updates |
| Background worker | PHP CLI daemon (process supervisor: Supervisord, free) | MIT | Runs continuously; handles cold chain monitoring and nightly KPIs |
| Barcode generation | PHP-Barcode-Generator (picqer) | MIT | Code 128 and Codabar, well-tested |
| Barcode scanning | ZXing-JS (browser) | Apache 2.0 | Free, runs in browser for bedside PWA |
| MFA / TOTP | PHP OTPHP library | MIT | RFC 6238 compliant |
| Crypto/encryption | PHP libsodium (built-in since 7.2) | ISC | AES-256-GCM, HMAC-SHA256, no external dependency |
| Key management | HashiCorp Vault | MPL 2.0 (free) | Industry standard, self-hosted, HTTP API |
| HL7 v2 interface | Mirth Connect (NextGen Connect) | MPL 2.0 (free) | Best free HL7 v2 MLLP engine |
| FHIR facade | Custom PHP implementation | — | Thin REST wrapper, versioned |
| Audit anchoring | FreeTSA.org (RFC 3161 TSA) | Free | External timestamping; no cost |
| Alerting | PHPMailer (email) + Africa's Talking or Twilio (SMS, free tier) | LGPL | Out-of-band notification path |
| Process monitoring | Supervisord | MIT | Keeps background worker alive |
| Forecasting | PHP implementation of HW-Additive | — | No Python/ML service needed at single-hospital scale |

---

## 16. Standards Compliance Map

| Standard | Compliance approach | Cost |
|----------|--------------------|----|
| WHO Blood Safety guidelines | Minimum TTI panel enforced via configurable `test_definition`; cold-chain rules in `component_storage_spec`; traceability via `unit_lineage` + `issue_transactions` | Free |
| AABB principles | Pretransfusion chain enforced (T&S + XM); two-ABO rule; electronic-XM eligibility gates; antibody history; MSBOS/C:T ratio; FEFO; 30-min return rule | Free |
| HL7 v2 | ADT, OML, ORU, BPO/BTX messages via Mirth Connect | Free |
| FHIR R4 | REST facade with CapabilityStatement | Free |
| ISO/IEC 15417 (Code 128) | Barcode library produces correct Code 128 | Free |
| ISO 7064 MOD 11-2 | Implemented for DID check character computation | Free |
| GDPR principles | Consent records, lawful basis distinction, DSR workflows, encryption, retention enforcement, DPIA template | Free |
| 21 CFR Part 11 principles | Append-only audit, hash chain, e-signatures with re-auth and payload binding, server-side UTC, access controls | Free |
| EU Directives 2002/98/EC, 2005/61/EC, 2005/62/EC | 30-year traceability; vein-to-vein; hemovigilance categories and imputability; responsible person role | Free |
| FDA 21 CFR 606/610 | Codebase follows principles: TTI testing, look-back, product deviation capture, traceability records | Free |
| ISBT 128 / ICCBBA | **Deferred** — not licensed. Custom DID on Code 128 replaces DIN. Internal `component_types` catalog replaces ISBT PDCs. `iccbba_fin` and `iccbba_product_code` columns preserved for future upgrade. | $0 now |
| MySQL Enterprise TDE | **Not used** — replaced by app-level AES-256-GCM + HashiCorp Vault (achieves stronger protection: covers query-time access, not just file-level) | $0 |

---

## 17. Phase Roadmap

### Phase 0 — Foundations (prerequisites for everything else)
All of these must exist before any feature is built on top. Retrofitting later = full rewrite.

- [ ] Database schema: patients, patient_identifiers, users, roles, permissions, user_roles, sod_conflicts, sessions
- [ ] Argon2id password hashing + TOTP MFA skeleton
- [ ] Server-side session management with idle/absolute timeout
- [ ] Append-only `audit_logs` with hash-chain + INSERT-only DB account
- [ ] `electronic_signatures` table and signing workflow
- [ ] `compliance_jurisdiction` + `compliance_ruleset` + `compliance_rule` skeleton with evaluator
- [ ] `subject_identity` + `key_refs` + HashiCorp Vault integration skeleton
- [ ] Background worker process wired with Supervisord
- [ ] `ref_facilities` + DID generation with ISO 7064 MOD 11-2 check character

### Phase 1 — MVP Core (single branch, online, safe)

- [ ] Full donor workflow: registration → eligibility screen → donation → component separation
- [ ] `blood_units` state machine with DB trigger guards
- [ ] TTI test panel + reactive-result lockout (DB trigger)
- [ ] Patient registry with `patient_blood_groups` + `patient_antibodies` + `patient_transfusion_requirements`
- [ ] Pre-transfusion chain: sample validity, two-ABO rule, antibody screen, crossmatch (IS/AHG/electronic with gates)
- [ ] Blood issue: `SELECT ... FOR UPDATE` + SoD check + e-signature + `issue_transactions`
- [ ] Emergency uncrossmatched release pathway
- [ ] `unit_lineage` DAG + recall workflow (basic)
- [ ] Code 128 label printing + `label_print_log`
- [ ] Cold chain monitoring: `temperature_log`, `sensor_health`, excursion detection (background worker)
- [ ] Equipment alarm escalation + email alerting
- [ ] Basic KPI dashboard: wastage, C:T ratio, days of supply
- [ ] Nightly audit chain anchoring (FreeTSA.org RFC 3161)

### Phase 2 — Sellable Product Increments

- [ ] Full hemovigilance: `transfusion_reaction` + `donor_adverse_event` + reporting flags
- [ ] Complete recall workflow with look-back CTE + recipient notification
- [ ] Bedside PWA: DID + wristband scan + two-person confirmation
- [ ] `transfusion_administration` records
- [ ] SSE real-time inventory dashboard (30-second polling fallback)
- [ ] SMS alerting (Africa's Talking free tier or Twilio)
- [ ] DPIA template + IQ/OQ/PQ template documents
- [ ] Holt-Winters forecasting + `forecast` + `kpi_daily`
- [ ] FHIR R4 facade (Patient, BiologicallyDerivedProduct, AuditEvent minimum)

### Phase 3 — Multi-Branch and Interoperability

- [ ] Multi-branch unit ownership + `transfers` + `unit_ownership_log`
- [ ] Offline resilience: `sync_events` + `sync_conflicts` + idempotent replay
- [ ] HL7 v2 via Mirth Connect: ADT + OML + ORU + BPO/BTX
- [ ] `compliance_ruleset` per-branch jurisdiction binding + multi-jurisdiction support
- [ ] Shipment cold chain: `shipment_cold_chain` + transport logger integration

### Phase 4 — Advanced (if justified)

- [ ] ISBT 128 upgrade: ICCBBA registration → populate `iccbba_fin` + `iccbba_product_code` → update label templates
- [ ] WebAuthn/FIDO2 phishing-resistant MFA (replaces TOTP)
- [ ] Multi-tenant pooled forecasting microservice (only if multi-hospital aggregate data is available)
- [ ] National haemovigilance authority automated report submission

---

*End of REQUIREMENTS-BEST.md*
*Authored: 2026-06-15 | No licensing cost incurred | All referenced standards are free to implement*
