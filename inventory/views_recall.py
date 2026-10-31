"""Recall management views."""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from donors.models import Donation
from .recall import find_units_for_donation, execute_recall
from accounts.permissions import has_permission


@login_required
def recall_lookup(request):
    """Look up all units from a donation before executing a recall."""
    donation = None
    units = None
    if request.method == 'GET' and request.GET.get('donation_id'):
        try:
            donation_id_val = int(request.GET['donation_id'])
        except (ValueError, TypeError):
            donation_id_val = None
        if donation_id_val:
            donation = get_object_or_404(Donation, pk=donation_id_val)
            units = find_units_for_donation(donation.pk)

    return render(request, 'inventory/recall_lookup.html', {
        'donation': donation,
        'units': units,
    })


@login_required
def recall_execute(request, donation_id):
    donation = get_object_or_404(Donation, pk=donation_id)
    if not has_permission(request.user, 'recall.manage', request.session.get('branch_id')):
        messages.error(request, "Permission denied.")
        return redirect('inventory:recall_lookup')

    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        reauth_at = request.session.get('reauth_at')
        summary = execute_recall(donation.pk, request.user, reason, reauth_at)
        return render(request, 'inventory/recall_result.html', {
            'donation': donation,
            'summary': summary,
        })
    return redirect('inventory:recall_lookup')
