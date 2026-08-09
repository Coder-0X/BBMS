from django.db.models import Q
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.html import format_html
from django.views.generic import CreateView, DeleteView, ListView, UpdateView


def format_display_value(value):
    if callable(value):
        value = value()
    if value is None:
        return '-'
    if hasattr(value, 'strftime'):
        # datetime (has a time component) -> render as browser-local time
        # via the [data-utc] JS in base.html. Plain dates (no time, e.g.
        # BloodUnit.expiry_date) don't need timezone conversion at all,
        # so they're left as a plain formatted string.
        if hasattr(value, 'hour'):
            fallback = value.strftime('%Y-%m-%d %H:%M') + ' UTC'
            return format_html(
                '<time data-utc="{}">{}</time>', value.isoformat(), fallback,
            )
        return value.strftime('%Y-%m-%d')
    return str(value)


class BloodBankListView(LoginRequiredMixin, ListView):
    template_name = 'crud/list.html'
    context_object_name = 'items'
    fields = []
    search_fields = []
    select_related_fields = []
    prefetch_related_fields = []
    create_url_name = ''
    edit_url_name = ''
    delete_url_name = ''
    page_title = 'Records'
    page_intro = ''

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.select_related_fields:
            queryset = queryset.select_related(*self.select_related_fields)
        if self.prefetch_related_fields:
            queryset = queryset.prefetch_related(*self.prefetch_related_fields)
        query = self.request.GET.get('q', '').strip()
        if query and self.search_fields:
            filters = Q()
            for field_name in self.search_fields:
                filters |= Q(**{f'{field_name}__icontains': query})
            queryset = queryset.filter(filters).distinct()
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = []
        for item in context['items']:
            rows.append(
                {
                    'object': item,
                    'item': item,
                    'values': [
                        format_display_value(getattr(item, field_name))
                        for _, field_name in self.fields
                    ],
                    'edit_url': (
                        reverse_lazy(self.edit_url_name, args=[item.pk])
                        if self.edit_url_name
                        else None
                    ),
                    'delete_url': (
                        reverse_lazy(self.delete_url_name, args=[item.pk])
                        if self.delete_url_name
                        else None
                    ),
                }
            )

        context['headers'] = [label for label, _ in self.fields]
        context['rows'] = rows
        context['create_url'] = reverse_lazy(self.create_url_name)
        context['page_title'] = self.page_title
        context['page_intro'] = self.page_intro
        context['search_query'] = self.request.GET.get('q', '').strip()
        return context


class BloodBankCreateView(LoginRequiredMixin, CreateView):
    template_name = 'crud/form.html'
    success_url_name = ''
    page_title = 'Add Record'
    page_intro = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = self.page_title
        context['page_intro'] = self.page_intro
        context['submit_label'] = 'Save Record'
        return context

    def get_success_url(self):
        return reverse_lazy(self.success_url_name)


class BloodBankUpdateView(LoginRequiredMixin, UpdateView):
    template_name = 'crud/form.html'
    success_url_name = ''
    page_title = 'Edit Record'
    page_intro = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = self.page_title
        context['page_intro'] = self.page_intro
        context['submit_label'] = 'Update Record'
        return context

    def get_success_url(self):
        return reverse_lazy(self.success_url_name)


class BloodBankDeleteView(LoginRequiredMixin, DeleteView):
    template_name = 'crud/confirm_delete.html'
    success_url_name = ''
    page_title = 'Delete Record'
    page_intro = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = self.page_title
        context['page_intro'] = self.page_intro
        return context

    def get_success_url(self):
        return reverse_lazy(self.success_url_name)
