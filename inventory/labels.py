"""
Blood unit label generation.
Produces Code 128 barcodes (ISO/IEC 15417 — free, no license).
Requires: pip install python-barcode[images] Pillow
"""
import io
import base64

try:
    import barcode
    from barcode.writer import ImageWriter
    BARCODE_AVAILABLE = True
except ImportError:
    BARCODE_AVAILABLE = False


def generate_barcode_b64(value: str, barcode_format: str = 'code128') -> str:
    """
    Generate a Code 128 barcode for the given value.
    Returns a base64-encoded PNG string suitable for embedding in HTML: <img src="data:image/png;base64,...">
    Returns empty string if python-barcode is not installed.
    """
    if not BARCODE_AVAILABLE:
        return ''

    BarcodeClass = barcode.get_barcode_class(barcode_format)
    buffer = io.BytesIO()
    options = {
        'module_height': 10.0,
        'module_width': 0.35,
        'quiet_zone': 3.0,
        'font_size': 8,
        'text_distance': 2.0,
    }
    BarcodeClass(value, writer=ImageWriter()).write(buffer, options=options)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode('ascii')


def print_label(unit, actor) -> dict:
    """
    Generate label data for a blood unit.
    Returns a dict with all fields needed to render the label template.
    Also logs the print event.
    """
    from inventory.models import LabelTemplate, LabelPrintLog

    template = LabelTemplate.objects.filter(
        active=True,
        component_class=unit.component_class,
    ).order_by('-approved_at').first()

    if not template:
        template = LabelTemplate.objects.filter(active=True, component_class='').order_by('-approved_at').first()

    barcode_png = generate_barcode_b64(unit.did)

    label_data = {
        'did': unit.did,
        'component': str(unit.component_type),
        'abo_rh': f"{unit.abo_type} {unit.rh_d_type}",
        'expiry': unit.expiry_datetime.strftime('%d %b %Y %H:%M') if unit.expiry_datetime else '',
        'branch': str(unit.owner_branch),
        'barcode_b64': barcode_png,
        'template': template,
    }

    if template:
        LabelPrintLog.objects.create(
            blood_unit=unit,
            template=template,
            did=unit.did,
            printed_by=actor,
        )

    return label_data
