"""
PDF report generation using ReportLab (BSD licence, free).
Each function returns a bytes object that can be streamed as application/pdf.
"""
from io import BytesIO
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# Colours
DARK    = colors.HexColor('#1a1a2e')
RED     = colors.HexColor('#c0392b')
LIGHT   = colors.HexColor('#f4f6f9')
GRAY    = colors.HexColor('#888888')


def _base_doc(title: str, branch_name: str) -> tuple:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
        title=title,
        author='BloodBank LIS',
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('ReportTitle', fontSize=16, textColor=DARK,
                              leading=20, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle('SubHead', fontSize=10, textColor=RED,
                              leading=14, fontName='Helvetica-Bold', spaceBefore=12))
    styles.add(ParagraphStyle('SmallGray', fontSize=8, textColor=GRAY, leading=11))
    story = []

    # Header
    story.append(Paragraph('BloodBank LIS', styles['SmallGray']))
    story.append(Paragraph(title, styles['ReportTitle']))
    story.append(Paragraph(
        f'Branch: {branch_name} &nbsp;&nbsp; Generated: {timezone.now().strftime("%d %b %Y %H:%M")}',
        styles['SmallGray'],
    ))
    story.append(HRFlowable(width='100%', thickness=1, color=RED, spaceAfter=8))
    return buf, doc, story, styles


def _table(data, col_widths=None):
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), DARK),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 0), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT]),
        ('FONTSIZE',   (0, 1), (-1, -1), 8),
        ('GRID',       (0, 0), (-1, -1), 0.25, colors.HexColor('#dddddd')),
        ('LEFTPADDING',  (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING',   (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
    ]))
    return t


def render_utilization_pdf(report: dict, branch_name: str) -> bytes:
    buf, doc, story, styles = _base_doc('Blood Utilization Report', branch_name)
    story.append(Paragraph(f"Period: Last {report['period_days']} days", styles['SmallGray']))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph('Units Issued by Component', styles['SubHead']))
    issued_data = [['Component', 'Issued']]
    for row in report.get('issued', []):
        issued_data.append([row.get('blood_unit__component_class', ''), str(row.get('count', 0))])
    if len(issued_data) > 1:
        story.append(_table(issued_data, col_widths=[12*cm, 5*cm]))

    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph('Crossmatch:Transfusion (C:T) Ratio', styles['SubHead']))
    ct_data = [['Component', 'C:T Ratio', 'Ideal (RBC ≤ 2.5)']]
    for comp, ratio in report.get('crossmatch_to_transfusion_ratio', {}).items():
        flag = ''
        if comp == 'RBC' and ratio and ratio > 2.5:
            flag = '⚠ HIGH'
        ct_data.append([comp, str(ratio) if ratio else 'N/A', flag])
    if len(ct_data) > 1:
        story.append(_table(ct_data, col_widths=[6*cm, 5*cm, 6*cm]))

    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph('Wasted / Expired Units', styles['SubHead']))
    we_data = [['Component', 'Wasted', 'Expired']]
    wasted_map  = {r['component_class']: r['count'] for r in report.get('wasted', [])}
    expired_map = {r['component_class']: r['count'] for r in report.get('expired', [])}
    all_comps = set(wasted_map) | set(expired_map)
    for comp in sorted(all_comps):
        we_data.append([comp, str(wasted_map.get(comp, 0)), str(expired_map.get(comp, 0))])
    if len(we_data) > 1:
        story.append(_table(we_data, col_widths=[6*cm, 6*cm, 5*cm]))

    doc.build(story)
    return buf.getvalue()


def render_inventory_age_pdf(rows: list, branch_name: str) -> bytes:
    buf, doc, story, styles = _base_doc('Inventory Age Report (FEFO)', branch_name)
    story.append(Paragraph('Units ordered by expiry date — First Expire, First Out', styles['SmallGray']))
    story.append(Spacer(1, 0.3*cm))

    data = [['DID', 'Component', 'ABO', 'Rh', 'Expires', 'Days Left', 'Urgency']]
    for u in rows:
        data.append([
            str(u.get('did', '')),
            str(u.get('component_class', '')),
            str(u.get('abo_type', '')),
            str(u.get('rh_d_type', '')),
            str(u['expiry_datetime'].strftime('%d %b %Y %H:%M')) if u.get('expiry_datetime') else '—',
            str(u.get('days_until_expiry', '—')),
            str(u.get('urgency', '')).upper(),
        ])
    if len(data) > 1:
        story.append(_table(data, col_widths=[3.5*cm, 2.5*cm, 1.5*cm, 1.5*cm, 4*cm, 2.5*cm, 2*cm]))

    doc.build(story)
    return buf.getvalue()


def render_donor_stats_pdf(report: dict, branch_name: str) -> bytes:
    buf, doc, story, styles = _base_doc('Donor Statistics Report', branch_name)
    story.append(Paragraph(f"Period: Last {report['period_days']} days", styles['SmallGray']))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph('Summary', styles['SubHead']))
    summary = [
        ['Total Donations', str(report.get('total_donations', 0))],
        ['Adverse Events', str(report.get('adverse_events', 0))],
        ['Adverse Event Rate', f"{report.get('adverse_rate_pct', 0)}%"],
    ]
    story.append(_table([['Metric', 'Value']] + summary, col_widths=[9*cm, 8*cm]))

    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph('Donations by Type', styles['SubHead']))
    type_data = [['Donation Type', 'Count']]
    for row in report.get('by_type', []):
        type_data.append([row.get('donation_type', ''), str(row.get('count', 0))])
    if len(type_data) > 1:
        story.append(_table(type_data, col_widths=[9*cm, 8*cm]))

    doc.build(story)
    return buf.getvalue()


def render_tti_pdf(rows: list, branch_name: str) -> bytes:
    buf, doc, story, styles = _base_doc('TTI Positivity Report', branch_name)
    story.append(Spacer(1, 0.3*cm))
    data = [['Test Code', 'Test Name', 'Total', 'Reactive', 'Rate (%)']]
    for row in rows:
        data.append([
            row.get('test_code', ''),
            row.get('test_name', ''),
            str(row.get('total', 0)),
            str(row.get('reactive', 0)),
            f"{row.get('rate_pct', 0):.3f}%",
        ])
    if len(data) > 1:
        story.append(_table(data, col_widths=[2.5*cm, 6*cm, 2*cm, 2.5*cm, 4*cm]))

    doc.build(story)
    return buf.getvalue()


def render_unit_pil_pdf(unit, branch_name: str) -> bytes:
    """Product Information Leaflet for a single blood unit — printed with the label."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
        title=f'PIL — {unit.did}',
        author='BloodBank LIS',
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('PILTitle', fontSize=14, textColor=DARK, fontName='Helvetica-Bold', leading=20))
    styles.add(ParagraphStyle('PILSection', fontSize=10, textColor=RED, fontName='Helvetica-Bold', spaceBefore=10))
    styles.add(ParagraphStyle('PILBody', fontSize=9, leading=13))
    styles.add(ParagraphStyle('PILSmall', fontSize=8, textColor=GRAY, leading=11))

    story = []
    story.append(Paragraph('Product Information Leaflet', styles['PILSmall']))
    story.append(Paragraph(f'Blood Component — {unit.did}', styles['PILTitle']))
    story.append(HRFlowable(width='100%', thickness=1, color=RED, spaceAfter=8))

    # Core identification
    story.append(Paragraph('Component Identity', styles['PILSection']))
    ident = [
        ['Donation ID (DID)', unit.did],
        ['Component Type', str(unit.component_type)],
        ['ABO Group', unit.abo_type],
        ['Rh D Type', unit.get_rh_d_type_display() if hasattr(unit, 'get_rh_d_type_display') else unit.rh_d_type],
        ['Volume', f'{unit.volume_ml} mL' if unit.volume_ml else '—'],
        ['Additive Solution', unit.additive_solution or '—'],
        ['Collection Date', unit.collection_datetime.strftime('%d %b %Y %H:%M') if unit.collection_datetime else '—'],
        ['Expiry Date/Time', unit.expiry_datetime.strftime('%d %b %Y %H:%M') if unit.expiry_datetime else '—'],
        ['Status', unit.status.replace('_', ' ').title()],
        ['Owner Branch', branch_name],
    ]
    story.append(_table([['Field', 'Value']] + ident, col_widths=[8*cm, 9*cm]))

    # Processing attributes
    story.append(Paragraph('Processing Attributes', styles['PILSection']))
    flags = [
        ('Leukoreduced', 'Yes' if unit.is_leukoreduced else 'No'),
        ('Irradiated', 'Yes' if unit.is_irradiated else 'No'),
        ('CMV Negative', 'Yes' if unit.is_cmv_negative else 'No'),
        ('Washed', 'Yes' if unit.is_washed else 'No'),
        ('Pathogen Reduced', 'Yes' if unit.pathogen_reduced else 'No'),
    ]
    story.append(_table([['Attribute', 'Status']] + [[f, s] for f, s in flags], col_widths=[8*cm, 9*cm]))

    if unit.antigen_negative_set:
        story.append(Paragraph('Antigen-Negative Set', styles['PILSection']))
        story.append(Paragraph(', '.join(
            f"{ag}: Negative" for ag, neg in unit.antigen_negative_set.items() if neg
        ), styles['PILBody']))

    # Storage and safety notice
    story.append(Paragraph('Storage Requirements', styles['PILSection']))
    story.append(Paragraph(
        f'Minimum: {unit.component_type.storage_temp_min_c}°C  |  '
        f'Maximum: {unit.component_type.storage_temp_max_c}°C',
        styles['PILBody'],
    ))

    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=GRAY))
    story.append(Paragraph(
        'This product has been tested and found non-reactive for HIV, HBV, HCV, and Syphilis '
        'using the tests mandated by the active compliance ruleset. No blood product can be guaranteed '
        'to be completely free of infectious agents. Transfuse through a blood administration set with '
        'a 170–200 µm filter. Inspect for abnormal colour, haemolysis, or clots before use.',
        styles['PILSmall'],
    ))

    doc.build(story)
    return buf.getvalue()


def render_patient_traceability_pdf(patient, transactions: list) -> bytes:
    """Complete transfusion history for a patient — vein-to-vein traceability."""
    buf, doc, story, styles = _base_doc(
        f'Patient Traceability Report — MPI {patient.mpi_uid}', 'Issuing Branch'
    )
    story.append(Paragraph(f'Patient #{patient.pk} | Sex: {patient.sex} | DOB: {patient.dob or "Unknown"}', styles['SmallGray']))
    story.append(Spacer(1, 0.3*cm))

    if not transactions:
        story.append(Paragraph('No transfusions recorded for this patient.', styles['SmallGray']))
    else:
        story.append(Paragraph('Transfusion History', styles['SubHead']))
        data = [['Date', 'DID', 'Component', 'ABO', 'Rh', 'Donation', 'Issuer', 'Branch']]
        for tx in transactions:
            unit = tx.blood_unit
            data.append([
                tx.issued_at.strftime('%d %b %Y %H:%M') if tx.issued_at else '—',
                unit.did if unit else '—',
                str(unit.component_type.code) if unit else '—',
                unit.abo_type if unit else '—',
                unit.rh_d_type if unit else '—',
                str(unit.donation_id) if unit else '—',
                tx.issued_by.username if tx.issued_by else '—',
                tx.intended_branch.name if tx.intended_branch else '—',
            ])
        story.append(_table(data, col_widths=[3.5*cm, 3*cm, 2.5*cm, 1.5*cm, 1.5*cm, 2*cm, 2.5*cm, 2.5*cm]))

    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=GRAY))
    story.append(Paragraph(
        'This report is confidential and subject to patient data protection regulations. '
        'Generated from the hash-chained audit trail.',
        styles['SmallGray'],
    ))
    doc.build(story)
    return buf.getvalue()


def render_donor_deferral_letter_pdf(donor, branch_name: str) -> bytes:
    """Formal deferral notification letter for a donor."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2.5*cm, rightMargin=2.5*cm,
        topMargin=3*cm, bottomMargin=3*cm,
        title=f'Donor Deferral Notice — {donor.pk}',
        author='BloodBank LIS',
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('LetterTitle', fontSize=15, textColor=DARK, fontName='Helvetica-Bold', leading=20, alignment=TA_CENTER))
    styles.add(ParagraphStyle('LetterBody', fontSize=10, leading=16, spaceBefore=6))
    styles.add(ParagraphStyle('LetterFooter', fontSize=8, textColor=GRAY, leading=11, alignment=TA_CENTER))

    story = []

    # Letterhead
    story.append(Paragraph(branch_name, styles['LetterTitle']))
    story.append(Paragraph('Blood Donation Service', styles['Normal']))
    story.append(HRFlowable(width='100%', thickness=1, color=RED, spaceAfter=12))

    story.append(Paragraph(f'Ref: DEFER/{donor.pk:06d}', styles['LetterBody']))
    story.append(Paragraph(f'Date: {timezone.now().strftime("%d %B %Y")}', styles['LetterBody']))
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph('DONOR DEFERRAL NOTIFICATION', styles['LetterTitle']))
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph('Dear Valued Donor,', styles['LetterBody']))
    story.append(Spacer(1, 0.3*cm))

    if donor.deferral_status == 'temporary_defer':
        period_text = ''
        if donor.deferral_until:
            period_text = f' until <b>{donor.deferral_until.strftime("%d %B %Y")}</b>'
        intro = (
            f'Following your recent assessment at <b>{branch_name}</b>, we regret to inform you '
            f'that you have been <b>temporarily deferred</b> from blood donation{period_text}. '
            'This is a precautionary measure to safeguard both your health and the safety of potential recipients.'
        )
    else:
        intro = (
            f'Following your recent assessment at <b>{branch_name}</b>, we regret to inform you '
            'that you have been <b>permanently deferred</b> from blood donation. '
            'This decision has been made in accordance with established blood safety criteria.'
        )

    story.append(Paragraph(intro, styles['LetterBody']))
    story.append(Spacer(1, 0.3*cm))

    if donor.deferral_reason:
        story.append(Paragraph('<b>Reason for deferral:</b>', styles['LetterBody']))
        story.append(Paragraph(donor.deferral_reason, styles['LetterBody']))
        story.append(Spacer(1, 0.3*cm))

    if donor.deferral_set_by:
        story.append(Paragraph(f'<b>Assessed by:</b> {donor.deferral_set_by.username}', styles['LetterBody']))

    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(
        'We sincerely appreciate your commitment to voluntary blood donation and your willingness '
        'to help save lives. We encourage you to revisit your eligibility in the future if your '
        'circumstances change, and warmly welcome you back as a donor when you are cleared to do so.',
        styles['LetterBody'],
    ))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(
        'If you have any questions regarding this decision, please contact the Blood Donation Service '
        'at the address shown above. Your information is treated with strict confidentiality.',
        styles['LetterBody'],
    ))
    story.append(Spacer(1, 0.8*cm))
    story.append(Paragraph('Yours sincerely,', styles['LetterBody']))
    story.append(Spacer(1, 1.2*cm))
    story.append(Paragraph('Blood Bank Medical Officer', styles['LetterBody']))
    story.append(Paragraph(branch_name, styles['LetterBody']))
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=GRAY))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        f'This letter was generated on {timezone.now().strftime("%d %B %Y at %H:%M")} by BloodBank LIS. '
        f'It is an official record. Donor ID: {donor.pk}',
        styles['LetterFooter'],
    ))

    doc.build(story)
    return buf.getvalue()


def render_lapsed_donors_pdf(donors: list, branch_name: str, months: int) -> bytes:
    """Re-engagement letter batch for lapsed donors."""
    buf, doc, story, styles = _base_doc(f'Lapsed Donor Re-engagement List — {months}+ Months', branch_name)
    story.append(Paragraph(
        f'Donors with no donation in the past {months} months who are eligible for re-contact.',
        styles['SmallGray'],
    ))
    story.append(Spacer(1, 0.3*cm))

    data = [['Donor #', 'Blood Group', 'Last Donation', 'Deferral Status']]
    for d in donors:
        abo = d.abo or '?'
        rh_map = {'pos': '+', 'neg': '−', 'weak_d': 'w', 'unknown': '?', '': ''}
        rh = rh_map.get(d.rh_d or '', '?')
        bg = f"{abo}{rh}" if abo != '?' else 'Unknown'
        last = str(getattr(d, 'last_donation_date', None) or 'Never')
        deferral = d.get_deferral_status_display()
        data.append([str(d.pk), bg, last, deferral])

    story.append(_table(data, col_widths=[2.5*cm, 3*cm, 4*cm, 7.5*cm]))
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph(
        f'Total: {len(donors)} donors. Contact according to your facility re-engagement protocol.',
        styles['SmallGray'],
    ))
    doc.build(story)
    return buf.getvalue()


def render_donor_blood_group_card_pdf(donor, branch_name: str) -> bytes:
    """
    Wallet-sized blood group ID card for a confirmed donor.
    Format: A6 (postcard/wallet card). Includes ABO/Rh, donor ID, and QR-equivalent DID.
    Only generated after a confirmed (2-determination) blood grouping.
    """
    from reportlab.lib.pagesizes import A6
    from reportlab.platypus import KeepTogether
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A6,
        leftMargin=1*cm, rightMargin=1*cm,
        topMargin=1.2*cm, bottomMargin=1*cm,
        title=f'Blood Group Card — Donor #{donor.pk}',
        author='BloodBank LIS',
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('CardTitle', fontSize=9, textColor=DARK,
                              leading=11, fontName='Helvetica-Bold', alignment=TA_CENTER))
    styles.add(ParagraphStyle('CardBG', fontSize=30, textColor=RED,
                              leading=36, fontName='Helvetica-Bold', alignment=TA_CENTER))
    styles.add(ParagraphStyle('CardSub', fontSize=7, textColor=GRAY,
                              leading=9, alignment=TA_CENTER))
    styles.add(ParagraphStyle('CardField', fontSize=8, textColor=DARK,
                              leading=10, alignment=TA_CENTER))

    abo = donor.blood_group_abo or '?'
    rh_map = {'pos': 'Rh D Positive', 'neg': 'Rh D Negative', 'weak_d': 'Weak D'}
    rh = donor.blood_group_rh or 'unknown'
    rh_label = rh_map.get(rh, rh)
    rh_short = {'pos': '+', 'neg': '−', 'weak_d': 'w+', 'unknown': '?'}.get(rh, '?')

    story = [
        Paragraph('BloodBank LIS', styles['CardSub']),
        Paragraph('DONOR BLOOD GROUP CARD', styles['CardTitle']),
        Spacer(1, 0.3*cm),
        Paragraph(f'{abo}{rh_short}', styles['CardBG']),
        Paragraph(rh_label, styles['CardField']),
        Spacer(1, 0.3*cm),
        Paragraph(f'Donor ID: <b>#{donor.pk}</b>', styles['CardField']),
        Paragraph(f'Branch: {branch_name}', styles['CardField']),
        Spacer(1, 0.2*cm),
        Paragraph(
            f'Confirmed typing on file. For transfusion compatibility, '
            'always perform crossmatch before issuing blood.',
            styles['CardSub'],
        ),
        Spacer(1, 0.2*cm),
        Paragraph(
            f'Printed: {timezone.now().strftime("%d %b %Y")}',
            styles['CardSub'],
        ),
    ]
    doc.build(story)
    return buf.getvalue()


def render_patient_blood_group_card_pdf(patient, branch_name: str) -> bytes:
    """
    Wallet-sized blood group card for a patient.
    Lists confirmed ABO/Rh, clinically significant antibodies, and special requirements.
    For patient to carry in case of emergency transfusion outside the issuing facility.
    """
    from reportlab.lib.pagesizes import A6
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A6,
        leftMargin=0.8*cm, rightMargin=0.8*cm,
        topMargin=1*cm, bottomMargin=0.8*cm,
        title=f'Patient Blood Group Card — Patient #{patient.pk}',
        author='BloodBank LIS',
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('PCT', fontSize=8, textColor=DARK,
                              leading=10, fontName='Helvetica-Bold', alignment=TA_CENTER))
    styles.add(ParagraphStyle('PBG', fontSize=32, textColor=RED,
                              leading=38, fontName='Helvetica-Bold', alignment=TA_CENTER))
    styles.add(ParagraphStyle('PSub', fontSize=7, textColor=GRAY,
                              leading=9, alignment=TA_CENTER))
    styles.add(ParagraphStyle('PFld', fontSize=7.5, textColor=DARK,
                              leading=10))
    styles.add(ParagraphStyle('PWarn', fontSize=7, textColor=RED,
                              leading=9))

    bg = patient.current_blood_group()
    abo = bg.abo if bg else (patient.abo or '?')
    rh = (bg.rh_d if bg else patient.rh_d) or 'unknown'
    rh_short = {'pos': '+', 'neg': '−', 'weak_d': 'wD', 'unknown': '?'}.get(rh, '?')
    rh_label = {'pos': 'Rh D Positive', 'neg': 'Rh D Negative',
                'weak_d': 'Weak D', 'unknown': 'Rh D Unknown'}.get(rh, rh)
    confirmed_label = 'Lab Confirmed' if bg else 'Declared (not lab-confirmed)'

    antibodies = list(patient.active_antibodies())
    special_reqs = list(patient.special_requirements.filter(active=True))

    story = [
        Paragraph('BloodBank LIS', styles['PSub']),
        Paragraph('PATIENT BLOOD GROUP CARD', styles['PCT']),
        Spacer(1, 0.2*cm),
        Paragraph(f'{abo}{rh_short}', styles['PBG']),
        Paragraph(rh_label, styles['PFld']),
        Paragraph(f'<i>({confirmed_label})</i>', styles['PSub']),
        Spacer(1, 0.2*cm),
        Paragraph(f'Patient ID: <b>#{patient.pk}</b>   MPI: {str(patient.mpi_uid)[:8]}…', styles['PSub']),
        Paragraph(f'Branch: {branch_name}', styles['PSub']),
    ]

    if antibodies:
        story.append(Spacer(1, 0.2*cm))
        ab_text = ', '.join(ab.specificity for ab in antibodies)
        story.append(Paragraph(f'<b>Antibodies:</b> {ab_text}', styles['PWarn']))

    if special_reqs:
        story.append(Spacer(1, 0.1*cm))
        req_text = ', '.join(r.get_requirement_display() for r in special_reqs)
        story.append(Paragraph(f'<b>Special requirements:</b> {req_text}', styles['PWarn']))

    story += [
        Spacer(1, 0.2*cm),
        Paragraph(
            'Always crossmatch before transfusion. Inform transfusing facility of this card.',
            styles['PSub'],
        ),
        Paragraph(f'Printed: {timezone.now().strftime("%d %b %Y")}', styles['PSub']),
    ]

    doc.build(story)
    return buf.getvalue()


def render_reaction_pdf(report: dict, branch_name: str) -> bytes:
    buf, doc, story, styles = _base_doc('Haemovigilance / Reaction Report', branch_name)
    story.append(Paragraph(f"Period: Last {report['period_days']} days  |  Total reactions: {report.get('total_reactions', 0)}", styles['SmallGray']))
    story.append(Spacer(1, 0.3*cm))

    for section, title in [('by_type', 'By Reaction Type'), ('by_severity', 'By Severity Grade'), ('by_outcome', 'By Outcome')]:
        story.append(Paragraph(title, styles['SubHead']))
        d = [['Category', 'Count']]
        for row in report.get(section, []):
            key = list(row.keys())[0]
            d.append([str(row[key]), str(row.get('count', 0))])
        if len(d) > 1:
            story.append(_table(d, col_widths=[9*cm, 8*cm]))
        story.append(Spacer(1, 0.2*cm))

    doc.build(story)
    return buf.getvalue()
