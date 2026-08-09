from django.forms.widgets import (
    CheckboxInput,
    DateInput,
    DateTimeInput,
    RadioSelect,
    Select,
    SelectMultiple,
)
from django.utils import timezone


class BootstrapFormMixin:
    now_default_field_names = frozenset({
        'donation_datetime',
        'tested_at',
        'request_date',
        'crossmatched_at',
        'issued_datetime',
    })

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        is_new_record = (
            not self.is_bound
            and getattr(self, 'instance', None) is not None
            and self.instance.pk is None
        )

        for name, field in self.fields.items():
            widget = field.widget
            existing_classes = widget.attrs.get('class', '')
            if isinstance(widget, (Select, SelectMultiple)):
                next_classes = 'form-select'
                widget.attrs['data-searchable'] = 'true'
            elif isinstance(widget, (CheckboxInput, RadioSelect)):
                next_classes = 'form-check-input'
            else:
                next_classes = 'form-control'

            widget.attrs['class'] = (
                f'{existing_classes} {next_classes}'.strip()
            )



            if isinstance(widget, DateTimeInput):
                widget.input_type = 'datetime-local'
                widget.format = '%Y-%m-%dT%H:%M'
                field.input_formats = [
                    '%Y-%m-%dT%H:%M',
                    '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%d %H:%M',
                ]
                if is_new_record and name in self.now_default_field_names:
                    field.initial = timezone.localtime()
            elif isinstance(widget, DateInput):
                widget.input_type = 'date'
                widget.format = '%Y-%m-%d'
                field.input_formats = ['%Y-%m-%d']