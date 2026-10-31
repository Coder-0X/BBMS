"""
Transfusion Clinical Decision Support (CDS) — pre-transfusion guideline checks.

References:
  - BCSH (British Committee for Standards in Haematology) 2012 Red Cell Transfusion
  - AABB (American Association of Blood Banks) Technical Manual 20th Ed.
  - WHO Clinical Transfusion Practice guidelines (2010)
  - NICE NG24 (Blood Transfusion, UK, 2015)
"""

from decimal import Decimal


class GuidelineFlag:
    """A single pass/fail check with guideline citation."""
    def __init__(self, code, label, passed, threshold_text, citation):
        self.code           = code          # e.g. 'rbc_hb_restrictive'
        self.label          = label         # human-readable
        self.passed         = passed        # True = meets guideline
        self.threshold_text = threshold_text
        self.citation       = citation

    def to_dict(self):
        return {
            'code':           self.code,
            'label':          self.label,
            'passed':         self.passed,
            'threshold_text': self.threshold_text,
            'citation':       self.citation,
        }


def check_transfusion_guideline(
    component_class: str,
    *,
    pre_transfusion_hb_g_dl=None,
    pre_transfusion_plt_per_nl=None,
    pre_transfusion_fibrinogen_g_l=None,
    pt_ratio=None,       # PT as ratio of normal (e.g. 1.6)
    aptt_ratio=None,     # APTT as ratio of normal
    is_actively_bleeding: bool = False,
    is_critical_care: bool = False,
    is_cardiac_surgery: bool = False,
    is_orthopaedic: bool = False,
    is_neurosurgery: bool = False,
    is_obstetric: bool = False,
    clinical_indication: str = '',
) -> dict:
    """
    Evaluate whether a transfusion request meets clinical guideline thresholds.

    Returns:
        {
          'meets_guideline': bool,
          'flags': [GuidelineFlag, ...],
          'summary': str,
          'override_required': bool,  # True if any flag fails (clinician must justify)
        }
    """
    flags = []

    if component_class == 'RBC':
        flags.extend(_check_rbc(
            hb=pre_transfusion_hb_g_dl,
            is_bleeding=is_actively_bleeding,
            is_cardiac=is_cardiac_surgery,
            is_ortho=is_orthopaedic,
            is_icu=is_critical_care,
        ))

    elif component_class == 'PLT':
        flags.extend(_check_plt(
            plt=pre_transfusion_plt_per_nl,
            is_bleeding=is_actively_bleeding,
            is_neuro=is_neurosurgery,
            indication=clinical_indication,
        ))

    elif component_class == 'FFP':
        flags.extend(_check_ffp(
            pt_ratio=pt_ratio,
            aptt_ratio=aptt_ratio,
            is_bleeding=is_actively_bleeding,
            indication=clinical_indication,
        ))

    elif component_class == 'CRYO':
        flags.extend(_check_cryo(
            fibrinogen=pre_transfusion_fibrinogen_g_l,
            is_bleeding=is_actively_bleeding,
            is_obstetric=is_obstetric,
        ))

    else:
        # WB, GRAN, etc. — no automated check available
        flags.append(GuidelineFlag(
            'no_check', 'No automated guideline available for this component',
            True, 'Manual clinician assessment required', 'Local policy',
        ))

    any_fail = any(not f.passed for f in flags)
    meets    = not any_fail

    if meets:
        summary = 'Transfusion meets clinical guideline thresholds.'
    elif is_actively_bleeding:
        summary = 'Active haemorrhage override — guideline thresholds relaxed. Justification required.'
    else:
        failing = [f.threshold_text for f in flags if not f.passed]
        summary = 'Guideline thresholds NOT met: ' + '; '.join(failing) + '. Override justification required.'

    return {
        'meets_guideline':  meets,
        'flags':            flags,
        'summary':          summary,
        'override_required': any_fail and not is_actively_bleeding,
    }


# ────────────────────────────────────────────────────────────────────────────
# Component-specific checks
# ────────────────────────────────────────────────────────────────────────────

def _check_rbc(*, hb, is_bleeding, is_cardiac, is_ortho, is_icu):
    flags = []
    if hb is None:
        flags.append(GuidelineFlag(
            'rbc_hb_missing', 'Pre-transfusion Hb not recorded',
            False, 'Hb must be documented before RBC transfusion',
            'BCSH 2012, NICE NG24',
        ))
        return flags

    hb = Decimal(str(hb))

    # Restrictive threshold (standard)
    threshold = Decimal('7.0')
    label     = 'Hb < 7 g/dL (restrictive threshold — stable adults)'
    citation  = 'BCSH 2012 / NICE NG24 / AABB 2016'

    if is_cardiac or is_ortho:
        threshold = Decimal('8.0')
        label     = 'Hb < 8 g/dL (perioperative / cardiac / orthopaedic threshold)'
        citation  = 'NICE NG24 / ACC/AHA 2011'

    if is_icu:
        threshold = Decimal('7.0')
        label     = 'Hb < 7 g/dL (ICU restrictive strategy — TRICC / TRISS trial)'
        citation  = 'Hébert et al. NEJM 1999; Holst et al. NEJM 2014'

    if is_bleeding:
        flags.append(GuidelineFlag(
            'rbc_active_bleed', 'Active haemorrhage — Hb threshold does not apply',
            True, 'Target Hb > 8 g/dL during active bleeding (MTP context)',
            'BCSH Major Haemorrhage 2015',
        ))
    else:
        flags.append(GuidelineFlag(
            'rbc_hb_threshold', label,
            hb < threshold, f'Patient Hb {hb} g/dL vs threshold {threshold} g/dL',
            citation,
        ))

    return flags


def _check_plt(*, plt, is_bleeding, is_neuro, indication):
    flags = []
    if plt is None:
        flags.append(GuidelineFlag(
            'plt_count_missing', 'Platelet count not recorded',
            False, 'Platelet count must be documented',
            'BCSH 2003 / AABB Technical Manual',
        ))
        return flags

    plt = int(plt)

    if is_bleeding:
        threshold = 50 if not is_neuro else 100
        label = (
            f'PLT < {threshold} ×10⁹/L during active bleeding'
            + (' (neurosurgical patient)' if is_neuro else '')
        )
        citation = 'BCSH 2003; NICE NG24'
        flags.append(GuidelineFlag(
            'plt_active_bleed', label, plt < threshold,
            f'Platelet count {plt} ×10⁹/L vs threshold {threshold}', citation,
        ))
    else:
        # Prophylactic threshold
        threshold = 10
        label = 'PLT < 10 ×10⁹/L (prophylactic threshold — stable, non-bleeding)'
        citation = 'BCSH 2003 / AABB 2014 / NICE NG24'

        indic_lower = (indication or '').lower()
        if 'procedure' in indic_lower or 'surgery' in indic_lower or 'biopsy' in indic_lower:
            threshold = 50
            label = 'PLT < 50 ×10⁹/L (pre-procedure threshold)'
            citation = 'BCSH 2003'
        if is_neuro:
            threshold = 100
            label = 'PLT < 100 ×10⁹/L (neurosurgery / ophthalmology threshold)'
            citation = 'BCSH 2003; NICE NG24'

        flags.append(GuidelineFlag(
            'plt_prophylactic', label, plt < threshold,
            f'Platelet count {plt} ×10⁹/L vs threshold {threshold}', citation,
        ))

    return flags


def _check_ffp(*, pt_ratio, aptt_ratio, is_bleeding, indication):
    flags = []
    has_coag = pt_ratio is not None or aptt_ratio is not None

    if not has_coag:
        flags.append(GuidelineFlag(
            'ffp_coag_missing', 'PT/APTT ratio not recorded',
            False, 'Coagulation tests (PT, APTT) must be documented',
            'BCSH 2004; NICE NG24',
        ))
        return flags

    # FFP is only appropriate when PT or APTT > 1.5× normal + active bleeding / invasive procedure
    ratio_exceeded = False
    if pt_ratio is not None and float(pt_ratio) > 1.5:
        ratio_exceeded = True
    if aptt_ratio is not None and float(aptt_ratio) > 1.5:
        ratio_exceeded = True

    indic_lower = (indication or '').lower()
    has_indication = is_bleeding or 'invasive' in indic_lower or 'procedure' in indic_lower or 'warfarin' in indic_lower

    flags.append(GuidelineFlag(
        'ffp_coag_ratio', 'PT or APTT > 1.5× normal with bleeding or invasive procedure',
        ratio_exceeded and has_indication,
        (
            f'PT ratio: {pt_ratio or "–"}, APTT ratio: {aptt_ratio or "–"}; '
            f'Active bleeding: {"Yes" if is_bleeding else "No"}'
        ),
        'BCSH 2004; NICE NG24 CG199',
    ))

    return flags


def _check_cryo(*, fibrinogen, is_bleeding, is_obstetric):
    flags = []
    if fibrinogen is None:
        flags.append(GuidelineFlag(
            'cryo_fibrinogen_missing', 'Fibrinogen level not recorded',
            False, 'Fibrinogen must be documented before cryoprecipitate',
            'BCSH 2004; NICE NG24',
        ))
        return flags

    fibrinogen = Decimal(str(fibrinogen))

    threshold = Decimal('1.5')
    label     = 'Fibrinogen < 1.5 g/L with active bleeding'
    citation  = 'BCSH 2004; NICE NG24'

    if is_obstetric:
        threshold = Decimal('2.0')
        label     = 'Fibrinogen < 2.0 g/L in obstetric haemorrhage (PPH)'
        citation  = 'RCOG (2016); BCSH Major Haemorrhage'

    if not is_bleeding:
        flags.append(GuidelineFlag(
            'cryo_no_bleeding', 'Cryoprecipitate not indicated without active bleeding (routine)',
            False, 'Cryoprecipitate is NOT indicated prophylactically without bleeding',
            'BCSH 2004',
        ))
    else:
        flags.append(GuidelineFlag(
            'cryo_fibrinogen', label,
            fibrinogen < threshold,
            f'Fibrinogen {fibrinogen} g/L vs threshold {threshold} g/L',
            citation,
        ))

    return flags
