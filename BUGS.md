# Blood Bank LIS — Bug Audit Log
> Audited: 2026-06-18 | Method: full source read across all apps

---

## transfusion app

### BUG-001: `neonatal_order_detail` — wrong field `branch` on BloodUnit filter ✅ SOLVED
**File:** `transfusion/views.py:1200`
**Symptom:** `FieldError: Cannot resolve keyword 'branch' into field` — page crashes with 500 on every Neonatal Order detail view.
**Detail:** `BloodUnit.objects.filter(branch=order.blood_request.branch, ...)` — the BloodUnit FK field is named `owner_branch`, not `branch`. Django raises FieldError at runtime.
**Fix:** Changed `branch=` to `owner_branch=` — 2026-06-18

### BUG-002: `neonatal_order_detail` — wrong field `expiry_date` in order_by ✅ SOLVED
**File:** `transfusion/views.py:1202`
**Symptom:** `FieldError: Cannot resolve keyword 'expiry_date' into field` — same page crash as BUG-001.
**Detail:** `.order_by('expiry_date')` — BloodUnit stores expiry as `expiry_datetime` (DateTimeField), not `expiry_date`.
**Fix:** Changed to `.order_by('expiry_datetime')` — 2026-06-18

### BUG-003: `mtp_activate` — wrong field `expiry_date` in O-neg unit order_by ✅ SOLVED
**File:** `transfusion/views.py:1337`
**Symptom:** `FieldError: Cannot resolve keyword 'expiry_date'` — MTP activation crashes on POST.
**Detail:** Same wrong field as BUG-002. `BloodUnit.objects.filter(...).order_by('expiry_date')` — must be `expiry_datetime`.
**Fix:** Changed to `.order_by('expiry_datetime')` — 2026-06-18

### BUG-004: `mtp_activate` — `messages.error()` used when stock is ADEQUATE ✅ SOLVED
**File:** `transfusion/views.py:1344-1348`
**Symptom:** When MTP is activated and ≥6 O-neg RBC units are available (the good outcome), a red error banner appears instead of a green success banner.
**Detail:** `if oneg_count < 6: messages.warning(...)` (correct) but the `else` branch uses `messages.error(...)` (wrong — should be `messages.success`). A successful MTP with adequate stock looks like an error to staff.
**Fix:** Changed `messages.error(` → `messages.success(` — 2026-06-18

### BUG-005: `new_antibody_screen` — silent fallback redirect to request #1 ✅ SOLVED
**File:** `transfusion/views.py:205`
**Symptom:** If antibody screen form is submitted without a `request_id` field, redirects to blood request #1 (wrong patient) instead of failing cleanly.
**Detail:** `redirect('transfusion:request_detail', pk=request.POST.get('request_id', 1))` — the default `1` means any request-less submission goes to the first request ever created.
**Fix:** Now redirects to `core:dashboard` if no `request_id` in POST — 2026-06-18

### BUG-006: `record_tti_result` — redirects to dashboard, loses donor context ✅ SOLVED
**File:** `transfusion/views.py:185`
**Symptom:** After recording a TTI result, user is sent to the dashboard. If they need to record a second test for the same donation, they must navigate back manually.
**Detail:** `return redirect('core:dashboard')` had no `donation_id` context to redirect back.
**Fix:** Now redirects to `donors:detail pk=donation.donor_id` — 2026-06-18

### BUG-007: `DonationTestResult._quarantine_donation_units` — `system_user` can be None ✅ SOLVED
**File:** `transfusion/models.py:98`
**Symptom:** If a reactive TTI result is saved and no superuser exists in the database, `transition_unit(unit, 'quarantined', None, ...)` is called with `None` as actor. This may cause an IntegrityError on the audit log (actor FK not nullable).
**Detail:** `system_user = User.objects.filter(is_superuser=True).first()` returns `None` when database has no superuser. `transition_unit` writes to audit with `actor=None`.
**Fix:** Now uses `self.performed_by` first, then falls back to superuser, guards if both None — 2026-06-18

---

## patients app

### BUG-008: `hdfn_list` — HDFN cases invisible if mother has no blood request at branch ✅ SOLVED
**File:** `patients/views.py:931-933`
**Symptom:** HDFN cases for mothers who were never blood-requested at this branch don't appear in the list, even if the mother is registered here.
**Detail:** `qs.filter(mother__blood_requests__branch_id=branch_id)` — required the mother to have a `BloodRequest` at this branch. Mothers managed purely in obs/gynae without a transfusion service request were excluded.
**Fix:** Changed to `mother__registration_branch_id=branch_id` — 2026-06-18

### BUG-009: `antenatal_detail` — `administered_at` passed as raw string to DateTimeField ✅ SOLVED
**File:** `patients/views.py:861`
**Symptom:** If the `administered_at` datetime-local input contains an invalid value (e.g. empty, wrong format), Django raises `ValidationError` / `ValueError` unhandled — 500 error.
**Detail:** `AntiDProphylaxis.administered_at` is a `DateTimeField`. The view passed the raw POST string directly without `try/except`.
**Fix:** Added `parse_datetime()` validation with user-facing error message — 2026-06-18

---

## inventory app

### BUG-010: `record_processing` — ProcessingEvent not linked to the processed unit ✅ SOLVED
**File:** `inventory/views.py:80-88`
**Symptom:** Processing events (leukoreduction, irradiation, etc.) were created but not linked to the specific blood unit. Audit trail showed event but not which unit was processed.
**Detail:** `ProcessingEvent.objects.create(event_type=proc_type, ...)` had no reference to the unit.
**Fix:** Added `blood_unit` FK to `ProcessingEvent` model + migration `0007_processingevent_blood_unit.py`. View now passes `blood_unit=unit` on create — 2026-06-18

---

## donors app

### BUG-011: `donor_detail` — no branch permission check ✅ SOLVED
**File:** `donors/views.py:78-84`
**Symptom:** Any logged-in user could view any donor's detail page regardless of branch or role.
**Detail:** `donor_detail` had `@login_required` but no branch check. User from Branch A could access Branch B donors by guessing pk.
**Fix:** Added check: `if donor.registration_branch_id != branch_id and not request.user.is_superuser: redirect with error` — 2026-06-18

---

## Already fixed this session

### BUG-F01: Blood grouping not propagated to units — crossmatch invisible ✅ SOLVED
**File:** `transfusion/views.py` `record_donation_blood_grouping`
**Detail:** `donation.units.update(abo_type=..., rh_d_type=...)` was never called. Fixed 2026-06-18.

### BUG-F02: Crossmatch special-requirements filter loop no-op ✅ SOLVED
**File:** `transfusion/views.py` `new_crossmatch`
**Detail:** `for qs in (qs_avail, qs_locked): qs = qs.filter(...)` reassigned local variable only. Fixed 2026-06-18.

### BUG-F03: Migration conflict — two leaf nodes in transfusion ✅ SOLVED
**File:** `transfusion/migrations/0009_post_transfusion_outcome.py`
**Detail:** Added `('transfusion', '0004_donation_blood_grouping')` to dependencies. Fixed 2026-06-18.

### BUG-F04: NeonatalTransfusionOrder forward-ref NameError ✅ SOLVED
**File:** `transfusion/models.py:212`
**Detail:** Changed direct class ref `BloodRequest` → string `'BloodRequest'`. Fixed 2026-06-18.

### BUG-F05: Therapeutic Phlebotomy nav icon was 💋 (kiss mark) ✅ SOLVED
**File:** `templates/base.html:503`
**Detail:** Changed `&#128139;` → `&#128137;` (💉 syringe). Fixed 2026-06-18.
