# Blood Bank Management System — Easy Requirements Guide

> **Who this is for:** Anyone building or reviewing this system. Written in plain English.
> **Project rule:** Zero licensing budget. No ISBT 128 / ICCBBA. No paid code tables. All standards followed using only free/open materials.
> **Date:** 2026-06-15

---

## PART 1 — INTERNATIONAL-LEVEL REQUIREMENTS (Must Have First)

These are the things that make a blood bank system safe and acceptable at hospital level anywhere in the world. Do not skip any of these.

---

### 1. Patient Is a Real Person, Not Just a Name

**The problem with the old way:** Storing a patient as just a text name like "John Smith" means you can never reliably find that same person again. If a patient was transfused last year and developed an antibody against a blood type, the system has no way to know that on their next visit. That is dangerous.

**What to do instead:** Every patient gets a permanent record in the database with a unique ID. All their blood history — their blood type, any antibodies found in their blood, any special requirements — follows them across every visit and every branch forever.

**Why this matters:** Some blood antibodies (like anti-K or anti-Jka) can disappear from a blood test over time but they are still dangerous. If a patient has had one, they must always get blood that is negative for that antigen for the rest of their life. Without a permanent patient record, this is impossible.

---

### 2. The Full Safety Check Before Giving Blood (Pretransfusion Chain)

**The old way was wrong:** Just checking if ABO blood types match (A, B, AB, O) is not enough. It only catches a small number of dangerous mismatches. There are dozens of other blood antigens that can cause serious or fatal reactions.

**The correct process is:**
1. Draw a blood sample from the patient → record when it was drawn
2. Test the sample for ABO and Rh type (must be confirmed twice total across visits)
3. Screen the sample for unexpected antibodies
4. If antibodies are found → identify exactly which ones → record permanently on patient
5. Select a blood unit that is compatible with the patient
6. Do a crossmatch (compatibility test) of the patient's blood against the selected unit
7. Only then issue the blood

**Sample time limit:** If the patient has had a transfusion or been pregnant in the last 3 months, their blood sample is only valid for 3 days. After that, a fresh sample is needed.

---

### 3. Every Blood Unit Has a Unique ID and a Barcode

**No QR codes.** QR codes cannot be scanned by hospital blood bank equipment. They have no standard format for blood data.

**What to use:** Code 128 barcode (free, open, ISO standard). All blood bank scanners support it.

**Our custom ID format (called DID — Donation ID):**
```
[3-letter facility code] + [2-digit year] + [6-digit serial] + [1 check character]
= 12 characters total, e.g. KNH260000012
```

The check character is calculated using the ISO 7064 MOD 11-2 formula (same method used for ISBN book numbers and IBAN bank accounts — completely free).

**Why not ISBT 128?** ISBT 128 is the international standard barcode format for blood. It is excellent. But it requires paying for ICCBBA facility registration and licensed code tables. Since this is a portfolio/learning project, we skip the paid part and use Code 128 with our own ID scheme instead. The upgrade path is kept open for later.

---

### 4. Blood Units Must Go Through a State Machine

Every blood unit must be in exactly one state at any time. The database enforces this — not just the app code.

**The states a unit can be in:**

```
quarantined (new unit, before testing)
    ↓
in_testing (samples being tested)
    ↓
available (all tests passed, ready to use)
    ↓ (splits here by what happens next)
reserved (held for a patient)
    ↓
crossmatched (compatibility test done)
    ↓
issued (handed over to clinical staff)
    ↓
transfused (given to patient)
    OR
returned_to_stock (unit came back within 30 min, still good)
    OR
wasted (returned too late / temperature problem)

Special states reachable at any time:
- expired (past expiry date — cannot be issued)
- recalled (donor later tested positive — must not be used)
- failed_qc (failed quality check — cannot be issued)
- quarantined_holdback (under investigation)
- destroyed (final state for disposal)
- transferred_out / in_transit (moving between branches)
```

**Database rule:** A trigger in the database will reject any illegal move. For example, going from `quarantined` to `issued` directly is blocked at database level — even if a bug in the app tries to do it.

---

### 5. You Cannot Give the Same Unit to Two Patients

This is called a double-issue bug. Under heavy load, if two nurses at two computers both try to issue the same unit at the same time, a simple app can give it to both. You cannot un-transfuse blood.

**Fix:** Use `SELECT ... FOR UPDATE` in MySQL/MariaDB. This locks the specific row in the database when you are checking it, so the second request must wait until the first one finishes. This is a specific SQL technique and must be deliberately coded in.

---

### 6. Immutable Audit Trail (Every Action Is Recorded Forever)

Every action in the system — issuing blood, changing a patient record, running a test — must be recorded and must never be changed or deleted. The record must also include who did it, what time, and what the values were before and after.

**Why this is hard with plain MySQL:** A database admin can edit or delete records in a regular MySQL table. So "just storing in a table" is not enough.

**The solution:** Hash-chaining. Each audit record stores a hash (fingerprint) of itself plus the hash of the previous record. If anyone changes or deletes a record, all the hashes after it become wrong, and the tampering is detectable. The most recent hash is saved outside the system (e.g. sent to an external server or a timestamping service) so even the database admin cannot quietly recompute everything.

---

### 7. Electronic Signatures on Critical Actions

Certain actions must be signed by a user — not just clicked. For example:
- Releasing a blood unit (approving it is safe to give)
- A quarantine release
- Confirming a test result

A signature means: the user re-enters their password at that moment, the system records their name, the time, and what the signature means (e.g. "approved for release"). The signature is mathematically linked to the record it signs, so it cannot be copied to a different record.

---

### 8. Nobody Can Do Everything Alone (Separation of Duties)

The person who collected a blood donation must not be the same person who tests it and also must not be the same person who approves its release. These are separate roles. The database enforces this.

- The system tracks: who collected, who tested, who interpreted results, who released
- Before allowing a release, the system checks that the releaser is none of the above
- Roles and permissions are stored in the database, not hardcoded

---

### 9. Cold Chain — Blood Must Stay at the Right Temperature

Different blood products need different temperatures:
- Red blood cells: 1–6 °C, no agitation
- Platelets: 20–24 °C, must be continuously agitated
- Frozen plasma: −18 °C or colder
- Cryoprecipitate: −18 °C or colder

**What the system must do:**
- Connect to temperature sensors in fridges/freezers
- Log every temperature reading continuously
- If temperature goes out of range → immediately quarantine all affected units → alert staff
- If a sensor stops sending data → treat it as an alarm (not silence it)
- A background worker process must do this checking continuously. A regular web app cannot do it because no browser needs to be open.

---

### 10. Vein-to-Vein Traceability

For every unit of blood ever in the system, you must be able to answer:
- **Forward:** Who received this unit? When? At which branch?
- **Backward:** Which donor did this come from? What were their test results?

This must go back 30 years (EU requirement) or 10 years minimum (US/WHO).

**Why:** If a donor tests positive for HIV 6 months after donating, you must find every unit from that donor, trace every patient who received them, and notify those patients. Without traceability this is impossible.

---

### 11. Recall and Look-Back Workflow

If a donor later tests positive for HIV, HBV, HCV, or syphilis:
1. Find all past donations by that donor
2. Find all blood units from those donations (including units split into multiple components)
3. Quarantine any that are still in stock
4. For units already transfused → find the recipients → notify clinical staff
5. Track the status of every step (who was notified, what was done)

---

### 12. Hemovigilance (Reporting Bad Reactions)

When a patient has a bad reaction to a transfusion, the system must:
- Record the type of reaction (there are many: AHTR, DHTR, FNHTR, TACO, TRALI, anaphylaxis, sepsis, etc.)
- Record severity (0 = no harm to 4 = death)
- Record how certain we are the transfusion caused it (definite / probable / possible / unlikely)
- Flag if it must be reported to health authorities
- Link back to the specific unit and donor

Similarly for donor adverse events (fainting, bruising, nerve injury during donation).

---

### 13. Compliance Rules Must Be Data, Not Code

Every country has different rules: minimum age for donation, hemoglobin level required, which diseases to test for, how long records must be kept, etc.

**The right way:** Store these rules in the database. The system evaluates them from the database. To add a new country or change a rule → update the database, not the code.

**Never do this:** `if ($country == "Kenya") { $minAge = 18; }` in PHP. That is hardcoded and requires a developer to change it every time.

---

### 14. Privacy — Patient and Donor Data Is Protected

- Patient data (name, national ID, blood results) is health data — the most sensitive category under GDPR and similar laws
- Direct identifiers (name, ID number, contact info) must be stored encrypted, not in plain text
- Encryption keys must NOT be stored in the same database or in the PHP code. They go in a separate key management system (e.g. HashiCorp Vault, free and open source)
- Each person must be able to request their data, correct it, or ask to restrict it
- But their blood safety records cannot be deleted even if they ask — the law requires keeping them for 10–30 years

---

### 15. Multi-Factor Authentication for Key Roles

Staff who can release blood units, manage users, or change system settings must log in with two factors:
1. Password
2. A one-time code from an authenticator app (TOTP — like Google Authenticator)

---

---

## PART 2 — DATABASE TABLES

This section lists every table in the system. Each table has: what it stores, why it exists, and what the important columns are.

---

### GROUP A — People

#### `patients` — The patient registry
Stores every patient (blood recipient) as a permanent record.

| Column | What it is |
|--------|-----------|
| patient_id | Unique ID for this patient (never changes) |
| mpi_uid | Master patient index — a global unique ID across all branches |
| given_name | First name |
| family_name | Last name |
| sex | M / F / Unknown |
| dob | Date of birth |
| national_id_hash | National ID number hashed for matching without storing it plain |
| merged_into_patient_id | If this record was merged with another, points to the survivor |
| record_status | active / merged / blocked |

---

#### `patient_identifiers` — All IDs for a patient
A patient may have different record numbers at different hospital branches. This table links them all to one patient.

| Column | What it is |
|--------|-----------|
| patient_id | Links to patients table |
| system | Which system gave this ID (e.g. "MRN:BranchA", "national-id") |
| value | The actual ID number |
| is_primary | Yes/No — is this the main ID |

---

#### `patient_blood_groups` — Patient blood type history (append-only)
Records every time a patient's blood type is tested. Never updates — only adds new rows.

| Column | What it is |
|--------|-----------|
| patient_id | Which patient |
| abo | A / B / AB / O |
| rh_d | pos / neg / weak_d / unknown |
| method | How it was tested (gel, tube, analyzer) |
| sample_id | Which blood sample was used |
| determined_by | Which lab tech did it |
| verified_by | Second person who confirmed it (required for first-ever determination) |
| is_discrepant | YES if this result disagrees with a previous one — triggers investigation |
| supersedes_id | Which older record this replaces |

*Note: A database view shows the latest confirmed blood group. The table itself always keeps all history.*

---

#### `patient_antibodies` — Patient antibody history (lifelong, append-only)
Stores every blood antibody ever found in a patient. Even if the antibody becomes undetectable on a current test, this record stays and forces antigen-negative blood forever.

| Column | What it is |
|--------|-----------|
| patient_id | Which patient |
| specificity | Which antibody (e.g. anti-K, anti-Jka, anti-E) |
| antigen_system | Which blood group system (Kell, Kidd, Duffy, Rh...) |
| clinical_significance | significant / insignificant / unknown |
| status | identified / historical_only / ruled_out |
| evanescent | YES = antibody can disappear from test but is still dangerous |
| first_identified_at | Date first found |
| first_identified_branch | Where first found |

---

#### `patient_transfusion_requirements` — Standing requirements for a patient
Some patients need special blood for life (e.g. irradiated blood after a bone marrow transplant). This table stores those standing requirements.

| Column | What it is |
|--------|-----------|
| patient_id | Which patient |
| requirement | irradiated / cmv_negative / washed / antigen_negative / phenotype_matched |
| antigen_spec | Specific antigen if antigen_negative (e.g. K-negative) |
| active | YES/NO — is this still in force |
| reason | Why this requirement exists |
| set_by | Which doctor set it |

---

#### `donors` — Blood donor registry
Each person who donates blood.

| Column | What it is |
|--------|-----------|
| donor_id | Unique ID |
| given_name, family_name | Name (stored encrypted) |
| sex, dob | Demographics |
| blood_group | ABO + Rh |
| deferral_status | active / temporary_defer / permanent_defer |
| deferral_reason, deferral_until | Details if deferred |
| total_donations | Count |
| last_donation_date | For interval checking |
| national_id_hash | For de-duplication |

---

#### `donations` — Individual donation events
Each time a donor donates blood.

| Column | What it is |
|--------|-----------|
| donation_id | Unique ID |
| donor_id | Who donated |
| branch_id | Where it happened |
| donated_at | Date and time |
| donation_type | whole_blood / apheresis_rbc / apheresis_plt / apheresis_plasma |
| volume_ml | How much collected |
| bag_lot_number | Bag used |
| collected_by | Staff member |
| consent_id | Links to consent record |
| phlebotomy_adverse_event | If donor had a reaction |

---

### GROUP B — Blood Units

#### `blood_units` — Every individual blood bag/component
The central table. One row = one physical bag of blood.

| Column | What it is |
|--------|-----------|
| unit_id | Unique internal ID |
| did | Donation ID barcode (12 chars, e.g. KNH260000012) — immutable |
| did_check_char | Check digit |
| division_suffix | For split/aliquot units (e.g. "A1") |
| donation_id | Which donation it came from |
| component_type_code | What type of component (links to component_types) |
| component_class | RBC / FFP / PLT / CRYO / WB / GRAN |
| collection_datetime | When collected |
| expiry_datetime | When it expires (time-precise for platelets) |
| status | Current state (quarantined/available/reserved/etc.) |
| version | Concurrency version number (increments on each change) |
| owner_branch_id | Which branch owns this unit |
| reserved_for_request_id | Which patient request is holding it |
| reserved_until | When the reservation expires |
| leukoreduced | YES/NO |
| irradiated | YES/NO |
| irradiation_datetime | When irradiated (resets expiry to 28 days from this date) |
| cmv_negative | YES/NO |
| washed | YES/NO |
| antigen_negative_set | JSON: which antigens this unit is negative for |
| collected_by | Staff |
| tested_by | Lab tech |
| interpreted_by | Person who read results |
| released_by | Person who approved for use (must differ from the above) |
| parent_donation_id | Original donation |
| production_event_id | Which processing event created this component |

---

#### `component_types` — Internal catalog of blood product types
Our own product list (replaces the licensed ISBT 128 Product Description Codes).

| Column | What it is |
|--------|-----------|
| code | Our internal 6-char code (e.g. RBC001) |
| name | Human-readable name (e.g. "Leukoreduced Red Blood Cells in SAGM") |
| component_class | RBC / FFP / PLT / CRYO / WB / GRAN |
| attributes_json | Default attributes (leukoreduced: true, additive_solution: "SAGM", etc.) |
| shelf_life_hours | Default shelf life |
| storage_temp_min/max | Required storage temperatures |

---

#### `ref_facilities` — Facility codes for DID generation
Maps the 3-letter facility code in the DID to a real branch.

| Column | What it is |
|--------|-----------|
| facility_code | 3-letter code (e.g. KNH) |
| name | Full facility name |
| branch_id | Links to branches table |

---

### GROUP C — Pretransfusion Testing

#### `samples` — Blood samples taken from patients (or donors)
Each time blood is drawn for testing, it gets a sample record.

| Column | What it is |
|--------|-----------|
| sample_id | Unique ID |
| patient_id | Which patient (null if donor sample) |
| donor_id | Which donor (null if patient sample) |
| accession_number | Lab number (unique) |
| collected_at | Date/time drawn |
| collected_by | Who drew it |
| sample_type | pre_transfusion / donor_screening / etc. |
| validity_expiry | For pre-transfusion samples: when the 3-day window ends |
| abo_confirmation_status | confirmed / single_determination / discrepant |

---

#### `antibody_screen` — Screening test for unexpected antibodies
Run on every patient sample. Checks against a panel of reagent cells.

| Column | What it is |
|--------|-----------|
| screen_id | Unique ID |
| sample_id | Which sample tested |
| method | IAT / PEG / LISS / gel |
| screen_cell_lot | Batch number of reagent cells used |
| result_per_cell | Results for each reagent cell (JSON) |
| overall_result | positive / negative |
| tech_id | Who ran the test |
| performed_at | When |

---

#### `antibody_identification` — Detailed identification of found antibodies
Run when the antibody screen is positive. Identifies exactly which antibody.

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| sample_id | Which sample |
| panel_lot | Reagent panel batch number |
| identified_specificities | JSON list of antibodies found (e.g. ["anti-K", "anti-E"]) |
| performed_at | When |
| tech_id | Who |

*When this finds an antibody, it creates/updates a row in patient_antibodies.*

---

#### `crossmatches` — Compatibility test between a patient and a specific unit
The final check before giving blood to a patient.

| Column | What it is |
|--------|-----------|
| crossmatch_id | Unique ID |
| sample_id | Patient's sample |
| blood_unit_id | The blood unit being tested |
| request_id | Which blood request this is for |
| method | immediate_spin / AHG / electronic |
| result | compatible / incompatible / electronic_release |
| reagent_lot | Reagent batch used |
| tech_id | Who did it |
| performed_at | When |
| verified_by | Second checker |
| electronic_eligibility_snapshot | JSON: what eligibility rules were checked for electronic crossmatch |

---

#### `emergency_release` — Issuing blood before crossmatch is complete
For life-threatening emergencies. Blood (usually O-negative) is given before all checks are done.

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| request_id | Which request |
| patient_id | Which patient |
| units_json | Which units were given |
| physician_id | Doctor who authorized |
| justification | Why emergency release was needed |
| release_datetime | When |
| retrospective_xm_status | pending / completed / incompatible_found |
| signoff_status | pending / signed_off |
| signoff_physician_id | Doctor who signed off retrospectively |

---

#### `msbos` — Maximum Surgical Blood Order Schedule
Tells the system how many units to crossmatch for each surgery type. Reduces unnecessary blood reservations.

| Column | What it is |
|--------|-----------|
| procedure_code | Surgery/procedure type |
| branch_id | Which branch (can be null for system-wide default) |
| order_type | none / type_and_screen / crossmatch |
| units_count | How many units to prepare |

---

### GROUP D — Blood Request and Issue

#### `blood_requests` — A clinical team's request for blood
One row per request from a ward or doctor.

| Column | What it is |
|--------|-----------|
| request_id | Unique ID |
| patient_id | Which patient needs blood |
| branch_id | Which branch is requesting |
| requesting_ward_id | Ward |
| requesting_physician_id | Doctor |
| component_class | What type of blood product needed |
| units_requested | How many |
| units_crossmatched | How many have been crossmatched |
| units_transfused | How many actually given |
| urgency | routine / urgent / emergency_MTP |
| requested_ts | When request was made |
| crossmatch_started_ts | When crossmatching began |
| crossmatch_completed_ts | When crossmatching finished |
| issued_ts | When blood was issued |
| outcome | fulfilled / partial / unmet / cancelled |
| ruleset_version_id | Which compliance rules governed this |

---

#### `issue_transactions` — The actual act of handing over blood
One row per unit issued.

| Column | What it is |
|--------|-----------|
| issue_id | Unique ID |
| blood_unit_id | Which unit |
| patient_id | Which patient |
| request_id | Which request |
| crossmatch_id | Which crossmatch approved this |
| issued_by | Who handed it over |
| issue_esign_id | Electronic signature on this action |
| issued_at | When |
| abo_check_passed | YES/NO |
| intended_branch | Which branch it's going to |

---

### GROUP E — Component Processing (How Components Are Made)

#### `processing_events` — Events where blood is processed/modified
One row for each time a blood unit is processed (separated, irradiated, washed, etc.)

| Column | What it is |
|--------|-----------|
| event_id | Unique ID |
| event_type | separation / split / irradiation / leukoreduction / pooling / wash / aliquot / thaw / pathogen_reduction |
| performed_at | When |
| performed_by | Staff member |
| branch_id | Where |
| sop_version | Which standard operating procedure version was used |
| esign_id | Electronic signature on this step |

---

#### `unit_lineage` — The family tree of blood units
Tracks which units came from which, including splits and pools.

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| processing_event_id | Which processing event created this relationship |
| parent_unit_id | The unit this came from (null if came from a raw donation) |
| parent_donation_id | The original donation (null if parent is a unit) |
| child_unit_id | The resulting unit |
| relationship | derived_from / split_from / pooled_into / aliquot_of |

*With this table you can trace: one unit → its donor → all co-products from that donation → all recipients. This is how look-back and recall work.*

---

### GROUP F — Unit Lifecycle Tracking

#### `unit_state_transitions` — The rule book for unit status changes
Defines which status changes are allowed.

| Column | What it is |
|--------|-----------|
| from_status | Current status |
| to_status | Status it can move to |
| requires_role | Which user role can trigger this transition |
| guard_rule | Additional condition that must be true |

---

#### `unit_status_events` — Every status change a unit ever had (append-only)
The complete history of where a unit has been.

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| unit_id | Which unit |
| from_status | What status it was in |
| to_status | What status it moved to |
| reason | Why |
| actor | Who did it |
| esign_id | Signature if required |
| occurred_at | When (server time, UTC) |

---

### GROUP G — Testing and Test Results

#### `test_definition` — What tests are mandatory
Configurable list of required infectious disease tests.

| Column | What it is |
|--------|-----------|
| test_code | Internal code (e.g. HIV_AgAb, HBsAg, anti_HCV) |
| name | Full test name |
| pathogen | HIV / HBV / HCV / Syphilis / HTLV / etc. |
| mandatory | YES/NO |
| applies_to | donors / patients / both |
| jurisdiction_id | Which country's rules require it |

---

#### `donation_test_result` — Test results for a donation
Records whether a donated unit passed all required tests.

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| donation_id | Which donation |
| test_code | Which test |
| sample_id | Which sample |
| result | reactive / non_reactive / indeterminate |
| instrument | Testing equipment used |
| performed_by | Tech |
| reviewed_by | Second checker |
| esign_id | Signature |
| performed_at | When |

*A blood unit cannot move to "available" status until ALL mandatory tests are non-reactive.*

---

### GROUP H — Cold Chain and Storage

#### `component_storage_spec` — Rules for storing each blood type
Defines temperature requirements for each blood component class.

| Column | What it is |
|--------|-----------|
| component_class | RBC / FFP / PLT / CRYO / WB / GRAN |
| storage_temp_min_c | Minimum temperature (°C) |
| storage_temp_max_c | Maximum temperature (°C) |
| transport_temp_min_c | During transport |
| transport_temp_max_c | During transport |
| requires_agitation | YES for platelets |
| agitation_max_interruption_min | How long agitation can stop (e.g. 60 min for platelets) |
| shelf_life_hours | How long it lasts |
| max_temp_excursion_min | How many minutes outside range before quarantine |

---

#### `storage_equipment` — Fridges, freezers, agitators
Every piece of cold storage equipment.

| Column | What it is |
|--------|-----------|
| equipment_id | Unique ID |
| name | Description (e.g. "RBC Fridge A") |
| type | fridge / platelet_agitator / freezer / ult_freezer / transport_cooler |
| sensor_id | ID of the temperature sensor |
| branch_id | Where it is |
| component_class_allowed | What can be stored here |
| calibration_due | Next calibration date |
| status | active / maintenance / decommissioned |

---

#### `temperature_log` — Continuous temperature readings (high volume)
A row is added every few minutes from every sensor.

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| equipment_id | Which equipment |
| recorded_at | Timestamp (UTC) |
| temp_c | Temperature in Celsius |
| agitation_ok | YES/NO (for platelet agitators) |
| source | sensor / manual |
| reading_uuid | Unique ID of this reading (for deduplication) |

*This table grows fast. Partition by month and archive old data.*

---

#### `sensor_health` — Heartbeat monitoring for sensors
Tracks when each sensor last sent data.

| Column | What it is |
|--------|-----------|
| sensor_id | Unique sensor ID |
| equipment_id | Which equipment |
| last_seen_at | Last time a reading was received |
| expected_interval_sec | How often it should report |
| status | ok / late / offline |

*A background worker checks this table every minute. If a sensor has not reported in longer than expected → raise alarm. A sensor going silent is more dangerous than a sensor reporting high temperature.*

---

#### `temperature_excursion` — When temperature went out of range
One row per excursion event.

| Column | What it is |
|--------|-----------|
| excursion_id | Unique ID |
| equipment_id | Which equipment |
| started_at | When it began |
| ended_at | When it ended (null if still ongoing) |
| max_temp_c | Worst temperature reached |
| auto_quarantine | YES — system automatically quarantined affected units |
| disposition | return_to_stock / quarantine / discard |
| disposition_by | Medical director (required to decide fate) |
| justification | Reason for decision |

---

#### `excursion_unit_link` — Which units were in a fridge during an excursion
Links an excursion event to the specific units affected.

| Column | What it is |
|--------|-----------|
| excursion_id | Which excursion |
| blood_unit_id | Which unit |
| was_in_equipment_at_start | YES/NO |
| auto_quarantined | YES if system quarantined it |

---

#### `equipment_alarm` — Alarms from storage equipment
Tracks all equipment alerts.

| Column | What it is |
|--------|-----------|
| alarm_id | Unique ID |
| equipment_id | Which equipment |
| alarm_type | high_temp / low_temp / agitation_failure / power_loss / door_open / sensor_disconnect / calibration_overdue / battery_low |
| triggered_at | When |
| cleared_at | When resolved (null if still active) |
| ack_by | Who acknowledged |
| escalation_level | 1=staff / 2=supervisor / 3=on-call |

---

#### `unit_return_check` — When blood comes back from the ward
If blood is returned before being given, can it go back into stock?

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| blood_unit_id | Which unit |
| issued_at | When it was issued |
| returned_at | When it came back |
| minutes_out | How long it was out |
| measured_return_temp_c | Temperature when returned |
| rule_applied | 30_minute_rule / validated_temp |
| decision | return_to_stock / discard |
| decided_by | Staff member |

---

#### `shipment_cold_chain` — Temperature data during inter-branch transport
When blood moves between branches, track the temperature throughout the journey.

| Column | What it is |
|--------|-----------|
| shipment_id | Unique ID |
| transfer_id | Which transfer this belongs to |
| logger_id | Data logger device ID |
| origin_branch_id | Sent from |
| destination_branch_id | Going to |
| departed_at | When it left |
| arrived_at | When it arrived |
| logger_data_json | All temperature readings from logger |
| excursion_detected | YES/NO |

---

### GROUP I — Hemovigilance (Reporting Reactions)

#### `transfusion_reaction` — Bad reactions in patients
One row per adverse event in a patient being transfused.

| Column | What it is |
|--------|-----------|
| reaction_id | Unique ID |
| blood_unit_id | Which unit caused it |
| patient_id | Which patient |
| request_id | Which request |
| reaction_category | AHTR / DHTR / FNHTR / allergic / anaphylactic / TACO / TRALI / TAD / TA_GVHD / PTP / sepsis / TTI / hypotensive |
| onset_timing | during / within_24h / delayed |
| severity_grade | 0 (no harm) to 4 (death) |
| imputability | definite / probable / possible / unlikely / excluded |
| signs_symptoms_json | Vital signs and symptoms |
| lab_results_json | DAT, bilirubin, etc. |
| reportable_to_authority | YES/NO |
| report_ref | Regulatory report reference number |
| reported_at | When sent to authorities |

---

#### `reaction_unit_link` — For reactions involving multiple units
If a patient received multiple units and a reaction occurs.

| Column | What it is |
|--------|-----------|
| reaction_id | Which reaction |
| blood_unit_id | Which unit |
| role | implicated / co_administered |

---

#### `donor_adverse_event` — Bad events in donors during donation
When a donor has a problem during or after donation.

| Column | What it is |
|--------|-----------|
| event_id | Unique ID |
| donation_id | Which donation session |
| donor_id | Which donor |
| event_type | vasovagal / syncope / hematoma / nerve_injury / citrate_reaction / arterial_puncture |
| severity | mild / moderate / severe |
| loss_of_consciousness | YES/NO |
| injury | YES/NO |
| outcome | full_recovery / ongoing / medical_referral |
| reportable | YES/NO |

---

### GROUP J — Recall and Look-Back

#### `recalls` — A recall or look-back investigation
One row per recall event (e.g. a donor tests positive 6 months after donating).

| Column | What it is |
|--------|-----------|
| recall_id | Unique ID |
| trigger | donor_seroconversion / positive_repeat_test / recipient_reaction / equipment_failure / recall_notice |
| trigger_donor_id | Which donor (if donor-triggered) |
| marker | Which disease marker (HIV / HBV / HCV / syphilis) |
| opened_at | When recall was started |
| opened_by | Staff |
| status | open / tracing / quarantined / dispositioned / closed / reported_to_authority |
| esign_id | Signature of person who opened it |

---

#### `recall_items` — Each unit affected by a recall
One row per blood unit involved in a recall.

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| recall_id | Which recall |
| blood_unit_id | Which unit |
| role | implicated_component / co_component / recipient_traced |
| disposition | quarantined / destroyed / already_transfused_recipient_notified / not_found |
| recipient_patient_id | Which patient received it (if already given) |

---

### GROUP K — Compliance Rule Engine

#### `compliance_jurisdiction` — Countries/regions
Each country or regulatory zone the system is deployed in.

| Column | What it is |
|--------|-----------|
| jurisdiction_id | Unique ID |
| name | e.g. "Kenya", "Nigeria", "EU", "US-FDA" |
| country_code | ISO 2-letter code |

---

#### `compliance_ruleset` — A set of rules for a jurisdiction
A versioned, dated package of rules. Once active, it is locked (immutable).

| Column | What it is |
|--------|-----------|
| ruleset_id | Unique ID |
| jurisdiction_id | Which country |
| version | Version number |
| effective_from | Date active from |
| effective_to | Date active until (null = current) |
| status | draft / active / superseded |

---

#### `compliance_rule` — Individual rules
One row per rule (e.g. "minimum donor age is 18").

| Column | What it is |
|--------|-----------|
| rule_id | Unique ID |
| ruleset_id | Which ruleset |
| rule_kind | AGE / WEIGHT / HB / BP / DONATION_INTERVAL / DEFERRAL / REQUIRED_TEST / RETENTION / LABEL_FORMAT |
| operator | greater_than / less_than / equals / between |
| threshold_value | e.g. 18 |
| threshold_unit | years / kg / g_dL / mmHg / days |
| applies_to | donor_eligibility / unit_release / record_retention |
| citation | The law or standard this comes from |

---

#### `test_definition` — see GROUP G above

#### `donation_test_result` — see GROUP G above

#### `retention_policy` — How long to keep each type of record

| Column | What it is |
|--------|-----------|
| record_class | donor_record / unit_record / traceability / audit_log / etc. |
| min_retention_years | Minimum years to keep |
| indefinite | YES if must be kept forever |
| legal_authority | The law that requires this |

---

#### `disposition_decision` — Records which rules were in force when a decision was made
This is for audit trail purposes — proving what rules were active when a unit was released.

| Column | What it is |
|--------|-----------|
| decision_id | Unique ID |
| entity_type | blood_unit / donation / request |
| entity_id | Which record |
| ruleset_version_id | Which ruleset was active |
| decided_at | When |
| decided_by | Who |

---

### GROUP L — Labeling

#### `label_templates` — Templates for blood bag labels
Defines how a label looks.

| Column | What it is |
|--------|-----------|
| template_id | Unique ID |
| version | Version number |
| component_class | Which blood type this template is for |
| barcode_symbology | Code128 / Codabar |
| fields_json | Which fields to print and where |
| checksum | Hash of the template (for validation) |
| approved_by | Who approved this template |

---

#### `label_print_log` — Record of every label printed
Every label printed gets a log entry.

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| blood_unit_id | Which unit |
| template_id | Which template |
| did | The DID barcode on the label |
| printed_by | Who printed |
| printed_at | When |
| printer_id | Which printer was used |

---

#### `labeling_profile` — System-wide labeling settings

| Column | What it is |
|--------|-----------|
| profile_id | Unique ID (usually just one row) |
| standard | CUSTOM_CODE128 / CODABAR |
| iccbba_fin | Null for now — reserved if ISBT 128 is ever adopted |

---

### GROUP M — Security and Access Control

#### `users` — Staff accounts

| Column | What it is |
|--------|-----------|
| user_id | Unique ID |
| username | Login name |
| password_hash | Argon2id hashed password (never plain text) |
| mfa_secret_enc | Encrypted MFA secret key |
| mfa_enabled | YES/NO |
| mfa_recovery_codes_hashed | Backup codes (hashed) |
| failed_attempts | Count of failed logins |
| locked_until | If account is locked, until when |
| branch_id | Home branch |
| active | YES/NO |

---

#### `permissions` — What actions exist in the system

| Column | What it is |
|--------|-----------|
| permission_id | Unique ID |
| code | e.g. "unit.release", "donor.read_pii", "test.perform" |
| description | What this permission allows |

---

#### `roles` — Named groups of permissions (e.g. "Lab Technician")

| Column | What it is |
|--------|-----------|
| role_id | Unique ID |
| name | e.g. "Lab Technician", "Blood Bank Supervisor", "Medical Director" |
| branch_scoped | YES = this role only applies within a branch |

---

#### `user_roles` — Who has which role at which branch

| Column | What it is |
|--------|-----------|
| user_id | Staff member |
| role_id | Which role |
| branch_id | At which branch (null = all branches) |
| granted_by | Who gave them this role |
| granted_at | When |

---

#### `role_permissions` — Which roles have which permissions

| Column | What it is |
|--------|-----------|
| role_id | Which role |
| permission_id | Which permission |

---

#### `sod_conflicts` — Forbidden permission combinations (Separation of Duties)
This table defines which two permissions cannot be held at the same time.

| Column | What it is |
|--------|-----------|
| permission_a | First permission |
| permission_b | Second permission |
| reason | Why they conflict |

*Example: "test.perform" and "unit.quarantine_release" are a conflict — the tester cannot also release.*

---

#### `sessions` — Server-side login sessions

| Column | What it is |
|--------|-----------|
| session_id | Token |
| user_id | Who is logged in |
| created_at | When session started |
| last_activity_at | Last action |
| absolute_expires_at | Hard cutoff (e.g. 8 hours) |
| ip | Client IP |
| user_agent | Browser/device info |
| reauth_at | Last time password was re-entered (for signing) |

---

#### `break_glass_sessions` — Emergency access beyond normal permissions
For emergencies where staff need access they normally don't have.

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| user_id | Who elevated |
| reason_code | Category of emergency |
| justification | Free-text explanation |
| granted_at | When |
| expires_at | When elevated access ends |
| alert_sent_to | Supervisor notified |
| reviewed_by | Post-event review by |
| reviewed_at | When reviewed |

---

### GROUP N — Audit and Signatures

#### `audit_logs` — Every action ever taken (append-only, hash-chained)

| Column | What it is |
|--------|-----------|
| id | Unique row ID |
| seq | Sequential number (never has gaps) |
| occurred_at_utc | When (server clock only, never client clock) |
| actor_user_id | Who did it |
| action | What happened (e.g. "unit.status_changed") |
| action_meaning | Human-readable description |
| entity_table | Which table was affected |
| entity_id | Which record was affected |
| before_json | What it looked like before |
| after_json | What it looks like after |
| branch_id | Where |
| ruleset_version_id | Which compliance rules were active |
| prev_hash | Hash of the previous row |
| row_hash | Hash of this row (includes prev_hash) |
| esign_id | Electronic signature if required |
| source | online / offline_replay |

*Nobody in the application can UPDATE or DELETE from this table. The database account used by the app only has INSERT on this table.*

---

#### `audit_chain_anchors` — External proof that audit trail has not been changed
Periodically, the current chain head hash is saved externally.

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| chain_head_hash | The hash at the time of anchoring |
| anchored_at | When |
| tsa_token | Timestamp from an external timestamping authority (RFC 3161) |
| server_signature | System's own signature of the hash |

---

#### `electronic_signatures` — Digital signatures on important actions

| Column | What it is |
|--------|-----------|
| esign_id | Unique ID |
| signer_user_id | Who signed |
| signed_at_utc | When (server time) |
| meaning | reviewed / approved / released / verified / quarantine_release / recalled |
| auth_method | password_reauth / mfa |
| reauth_at | When they re-entered their password |
| signed_payload_hash | Hash of the record being signed (ties signature to that exact record) |
| audit_log_id | Which audit entry this is for |
| manifested_name | Printed name of signer at time of signing |

---

### GROUP O — Privacy

#### `consent_records` — Recorded consent from donors and patients

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| subject_id | Donor or patient ID |
| subject_type | donor / recipient |
| purpose | donation / health_screening / data_processing |
| lawful_basis | consent / vital_interest / healthcare_provision |
| notice_version | Which privacy notice version they were shown |
| captured_at | When |
| captured_by | Staff |
| withdrawn_at | If consent was later withdrawn |

---

#### `dsr_requests` — Data subject rights requests
When someone asks for their data, wants it corrected, or asks it to be deleted.

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| subject_id | Who is asking |
| type | access / rectify / erase / restrict / portability |
| status | received / processing / completed / refused |
| requested_at | When |
| handled_by | Staff member |
| outcome | What was done |
| refusal_reason | If refused: why (e.g. "30-year legal retention") |

---

#### `subject_identity` — Encrypted personal identifiers (separate from operational data)
Direct identifiers live here, not in the main operational tables.

| Column | What it is |
|--------|-----------|
| subject_id | Links to donor or patient |
| name_enc | Encrypted name |
| national_id_enc | Encrypted national ID |
| contact_enc | Encrypted contact info |
| national_id_blind_index | HMAC of normalized ID (for exact-match lookup without decrypting) |
| name_blind_index | HMAC of normalized name (for exact-match lookup) |

---

#### `key_refs` — Envelope encryption metadata
Tracks which encryption key was used for which record.

| Column | What it is |
|--------|-----------|
| key_ref_id | Unique ID |
| subject_id | Which record |
| wrapped_key | The data encryption key, itself encrypted by master key |
| key_version | Which master key version |
| kms_key_id | Reference to key in external KMS |

*The actual master key lives only in the external KMS (e.g. HashiCorp Vault), never in the database.*

---

### GROUP P — Multi-Branch / Sync

#### `unit_ownership_log` — History of which branch owned each unit
Append-only record of ownership transfers.

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| unit_id | Which unit |
| from_branch_id | Previous owner |
| to_branch_id | New owner |
| transferred_at | When |
| transfer_id | Links to transfer record |

---

#### `sync_events` — Events replicated between branches
When branches sync, every event gets a record.

| Column | What it is |
|--------|-----------|
| event_uuid | Unique event ID (used to prevent replaying twice) |
| branch_id | Which branch generated it |
| entity_din | Which blood unit |
| action | What happened |
| prior_version | Version of the record before the action |
| device_ts | Timestamp on the local device |
| server_received_ts | When the central server received it |
| apply_result | applied / rejected / conflict |

---

#### `sync_conflicts` — When two branches did conflicting things
Requires human resolution — never auto-merged.

| Column | What it is |
|--------|-----------|
| conflict_id | Unique ID |
| event_uuid_a | First conflicting event |
| event_uuid_b | Second conflicting event |
| blood_unit_id | Which unit |
| conflict_type | Description of the conflict |
| status | pending / resolved |
| resolved_by | Staff who resolved it |
| resolution | What was decided |

---

#### `inventory_change_feed` — Simple feed for checking what changed
Lets branches quickly check if anything has changed since their last sync.

| Column | What it is |
|--------|-----------|
| seq | Sequential number |
| branch_id | Which branch |
| event_type | What happened |
| entity_id | Which record |
| occurred_at | When |

---

### GROUP Q — Analytics and Forecasting

#### `unit_event_log` — Master event stream for all units
This is the unified append-only log that feeds both analytics and the audit trail.

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| unit_id | Which unit |
| event_type | collected / tested / available / reserved / crossmatched / issued / transfused / returned / discarded / expired / transferred |
| event_ts | When (UTC) |
| actor | Who |
| branch_id | Where |
| related_request_id | Which blood request |
| reason_code_id | Why |

---

#### `reason_codes` — Standard list of reasons for actions

| Column | What it is |
|--------|-----------|
| code | Short code |
| category | wastage / deferral / return / discard |
| description | Human-readable |

---

#### `demand_fact_daily` — Daily summary of demand (built each night)
Aggregated numbers for forecasting.

| Column | What it is |
|--------|-----------|
| date | The day |
| branch_id | Which branch |
| component_class | Blood type |
| abo | A / B / AB / O |
| rh | pos / neg |
| units_issued | How many were issued that day |
| units_requested | How many were requested |
| units_expired | How many expired |
| units_wasted | How many were wasted |
| stock_at_eod | How many were in stock at end of day |

---

#### `forecast` — Predicted demand for blood

| Column | What it is |
|--------|-----------|
| forecast_id | Unique ID |
| branch_id | Which branch |
| component_class | Blood type |
| abo, rh | Blood group |
| forecast_date | Which date is being predicted |
| predicted_units | How many units predicted |
| model_used | moving_avg / ses / holt_winters |
| generated_at | When forecast was made |
| safety_quantile | Safety stock level (e.g. 95th percentile) |

---

#### `forecast_accuracy` — How accurate past forecasts were

| Column | What it is |
|--------|-----------|
| id | Unique ID |
| forecast_id | Which forecast |
| actual_units | What actually happened |
| mase | Mean Absolute Scaled Error (accuracy metric) |

---

#### `kpi_daily` — Daily key performance indicators

| Column | What it is |
|--------|-----------|
| date | The day |
| branch_id | Which branch |
| component_class | Blood type |
| ct_ratio | Crossmatch to transfusion ratio (target ≤ 2.0) |
| wastage_pct | Percentage of units that expired unused |
| stock_out_events | How many times a requested blood type had zero stock |
| days_of_supply | How many days current stock would last at current demand |
| near_expiry_units | Units expiring within the alert window |
| tat_request_to_issue_min | Average minutes from request to issue |

---

#### `config_targets` — Performance targets (configurable per branch)

| Column | What it is |
|--------|-----------|
| branch_id | Which branch (null = system-wide) |
| component_class | Blood type |
| target_days_of_supply | How many days of stock to keep |
| max_wastage_pct | Maximum allowed wastage percentage |
| near_expiry_alert_hours | How many hours before expiry to flag a unit |
| abo_distribution_json | Expected ABO blood group mix for that region |

---

### GROUP R — Inter-Branch Transfers

#### `transfers` — Moving blood units between branches

| Column | What it is |
|--------|-----------|
| transfer_id | Unique ID |
| blood_unit_id | Which unit |
| from_branch_id | Sending branch |
| to_branch_id | Receiving branch |
| initiated_by | Staff |
| initiated_at | When |
| dispatched_at | When it left |
| received_at | When it arrived |
| received_by | Staff at receiving branch |
| status | requested / approved / in_transit / received / rejected |
| reason | Why it was transferred |
| cold_chain_ok | YES/NO (based on shipment temperature log) |

---

---

## PART 3 — NON-DATABASE REQUIREMENTS

These are things the system needs that are not just database tables.

---

### Background Worker Process
A separate program that runs continuously (not triggered by web requests):
- Checks sensor heartbeats every minute — if a sensor stops reporting, raise alarm
- Detects temperature excursions, quarantines affected units
- Checks for units about to expire — send alerts
- Sends escalating alarms (staff → supervisor → on-call) if not acknowledged
- Runs nightly KPI calculations and forecast updates

---

### Real-Time Alerts (Out-of-Band)
Critical alerts must reach people even if no browser is open:
- SMS or voice call for temperature alarms and sensor failures
- Email for escalated alerts
- At minimum: email gateway. Better: SMS gateway.
- Free options: integrate with Africa's Talking, Twilio (has a free tier), or facility's own SMTP

---

### Barcode Label Printing
- Use a Code 128 barcode library (many free: PHP-Barcode-Generator, libre-barcode, etc.)
- Print on validated label printer
- Every print is logged in `label_print_log`
- Optional: Codabar as secondary format (older blood bank scanners)

---

### HL7 / FHIR Interoperability (for hospital integration)
To connect to a hospital's existing systems:
- **HL7 v2 messages:** Used by most hospital labs and blood banks. Patient registration, orders, results.
- **FHIR R4:** Modern standard. Can be implemented as a REST API.
- Both are free to implement. No licensing needed.
- For HL7 v2 over TCP (called MLLP), use a background worker or dedicated interface engine. **Mirth Connect** is free and open source — the best option for HL7 v2 integration.

---

### Bedside Verification
Before giving blood to a patient at the bedside:
1. Scan patient wristband barcode
2. Scan blood unit DID barcode
3. System confirms they match
4. Two staff members confirm
This is the single most important safety check at point of care.

Can be built as a mobile PWA (Progressive Web App) — runs on any smartphone or tablet, no app store needed, works offline with limited functionality.

---

### Key Management System (KMS)
Encryption keys for patient/donor data must not be stored in the database or in PHP config files. Use:
- **HashiCorp Vault** — free, open source, industry standard
- Or a cloud KMS if deploying on cloud (AWS KMS, Google Cloud KMS)

The app fetches keys from the KMS at runtime. Keys can be rotated without re-encrypting all data.

---

### Audit Anchoring (External Proof of Audit Integrity)
The hash chain in `audit_logs` can detect tampering but not prevent a database admin from recomputing the whole chain. To prevent this:
- Periodically (e.g. nightly) send the current chain head hash to an external system
- Free options: self-hosted append-only log server, RFC 3161 free timestamping services
- Even logging the hash to a separate server the DBA does not control is sufficient for most deployments

---

### Forecasting Engine
Built into the main PHP app using standard algorithms:
1. Simple moving average (baseline)
2. Simple Exponential Smoothing (SES)
3. Holt-Winters Additive (handles seasonality — best for blood demand)
4. Auto-selects best model based on MASE (Mean Absolute Scaled Error)
5. Safety stock = demand forecast + Z × standard deviation (set Z for 95% service level)

All implemented in PHP/MySQL. No external ML service needed.

---

### Tech Stack Summary

| Component | Technology | Cost |
|-----------|-----------|------|
| Backend | PHP 8.2+ | Free |
| Database | MariaDB 11+ or MySQL 8+ | Free |
| Frontend | HTML/CSS/JavaScript (AJAX/SSE) | Free |
| Barcodes | PHP Barcode Generator (Code 128) | Free |
| MFA | TOTP (PHP otphp library) | Free |
| Password hashing | Argon2id (built into PHP) | Free |
| Encryption | libsodium (built into PHP 7.2+) | Free |
| Key management | HashiCorp Vault | Free |
| HL7 interface | Mirth Connect (NextGen Connect) | Free (open source) |
| Background worker | PHP CLI process / supervisor | Free |
| Real-time alerts | SMTP + optional SMS gateway | Free SMTP / paid SMS |
| Audit anchoring | Self-hosted or RFC 3161 TSA | Free |
| Bedside app | PWA (runs in browser) | Free |
| Field encryption | AES-256-GCM via libsodium | Free |

---

### What "International Level" Actually Means for This System

The system follows these free international standards:
- **WHO Blood Safety guidelines** — minimum testing, cold chain, traceability
- **AABB principles** — pretransfusion testing, two ABO determinations, electronic crossmatch rules
- **HL7 v2 / FHIR R4** — hospital system interoperability
- **ISO/IEC 15417** — Code 128 barcode (free, open)
- **ISO 7064 MOD 11-2** — check character algorithm (free)
- **GDPR principles** — privacy by design (applicable globally as best practice)
- **21 CFR Part 11 principles** — electronic records and signatures (US FDA, free to follow)
- **EU Blood Directives 2002/98/EC, 2005/61/EC, 2005/62/EC** — free to read and implement

What is skipped due to licensing cost:
- **ISBT 128 / ICCBBA registration** — paid, deferred. Upgrade path kept open.
- **Licensed ISBT 128 product code tables** — replaced with internal catalog
- **MySQL Enterprise TDE** — replaced with app-level AES-256-GCM encryption

---

*End of REQUIREMENTS-EASY.md*
