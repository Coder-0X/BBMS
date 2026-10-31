from django.contrib import admin
from django.contrib import messages
from .models import SubjectIdentity, ConsentRecord, DSRRequest


@admin.register(SubjectIdentity)
class SubjectIdentityAdmin(admin.ModelAdmin):
    list_display = ['pk', 'subject_type']
    # Never show encrypted fields in admin
    exclude = ['name_enc', 'national_id_enc', 'contact_enc']


@admin.register(ConsentRecord)
class ConsentRecordAdmin(admin.ModelAdmin):
    list_display = ['subject', 'purpose', 'lawful_basis', 'captured_at', 'withdrawn_at']
    list_filter = ['lawful_basis', 'subject_type']
    readonly_fields = ['captured_at']

    def has_change_permission(self, request, obj=None):
        return False  # Append-only


@admin.register(DSRRequest)
class DSRRequestAdmin(admin.ModelAdmin):
    list_display = ['subject', 'request_type', 'status', 'requested_at', 'completed_at']
    list_filter = ['status', 'request_type']
    readonly_fields = ['requested_at', 'completed_at', 'outcome', 'refusal_reason']
    actions = ['process_selected_requests']

    @admin.action(description='Process selected DSR requests (run handler)')
    def process_selected_requests(self, request, queryset):
        processed = refused = errors = 0
        for dsr in queryset.filter(status='received'):
            try:
                from .dsr_handler import handle_erasure_request, handle_access_request
                if dsr.request_type == 'erase':
                    result = handle_erasure_request(dsr, actor=request.user)
                    if result.get('decision') == 'full_pseudonymisation':
                        processed += 1
                    else:
                        refused += 1
                elif dsr.request_type == 'access':
                    handle_access_request(dsr, actor=request.user)
                    processed += 1
                else:
                    # For restrict, rectify, portability: mark processing
                    dsr.status = 'processing'
                    dsr.handled_by = request.user
                    dsr.save(update_fields=['status', 'handled_by'])
                    processed += 1
            except Exception as exc:
                errors += 1
                self.message_user(
                    request,
                    f"Error processing DSR #{dsr.pk}: {exc}",
                    level=messages.ERROR,
                )

        parts = []
        if processed:
            parts.append(f"{processed} processed")
        if refused:
            parts.append(
                f"{refused} partially refused (blood-safety records retained under "
                "EU Blood Directive 30-year rule; marketing data erased)"
            )
        if errors:
            parts.append(f"{errors} errors")
        if parts:
            self.message_user(request, "; ".join(parts) + ".", level=messages.SUCCESS if not errors else messages.WARNING)
