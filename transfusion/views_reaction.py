"""Transfusion reaction recording and investigation views."""
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone

from .models import IssueTransaction, TransfusionReaction, ReactionInvestigation
from .haemovigilance import record_reaction
from accounts.permissions import has_permission
from audit.utils import write_audit, create_signature


@login_required
def record_reaction_view(request, transaction_id):
    tx = get_object_or_404(IssueTransaction, pk=transaction_id)

    # Prevent duplicate reactions
    if hasattr(tx, 'reaction'):
        messages.warning(request, "A reaction has already been recorded for this transfusion.")
        return redirect('transfusion:reaction_detail', pk=tx.reaction.pk)

    if request.method == 'POST':
        reauth_at = request.session.get('reauth_at')
        onset_str = request.POST.get('onset_datetime')
        onset = timezone.datetime.fromisoformat(onset_str) if onset_str else timezone.now()

        reaction = record_reaction(
            issue_transaction=tx,
            reaction_type=request.POST['reaction_type'],
            onset_datetime=onset,
            severity=request.POST['severity'],
            imputability=request.POST['imputability'],
            outcome=request.POST['outcome'],
            clinical_description=request.POST['clinical_description'],
            actor=request.user,
            reauth_at=reauth_at,
            investigation_summary=request.POST.get('investigation_summary', ''),
        )
        messages.warning(request, f"Transfusion reaction #{reaction.pk} recorded. Clinical team notified.")
        return redirect('transfusion:reaction_detail', pk=reaction.pk)

    return render(request, 'transfusion/record_reaction.html', {'tx': tx})


@login_required
def reaction_detail(request, pk):
    """Detail view for a transfusion reaction, showing investigation status."""
    reaction = get_object_or_404(
        TransfusionReaction.objects.select_related(
            'issue_transaction__request', 'patient', 'blood_unit', 'recorded_by',
        ),
        pk=pk,
    )
    investigation = getattr(reaction, 'investigation', None)
    return render(request, 'transfusion/reaction_detail.html', {
        'reaction': reaction,
        'investigation': investigation,
    })


@login_required
def start_investigation(request, reaction_pk):
    """Open a new investigation workup for a reaction."""
    reaction = get_object_or_404(TransfusionReaction, pk=reaction_pk)

    if hasattr(reaction, 'investigation'):
        return redirect('transfusion:investigation_update', reaction_pk=reaction_pk)

    investigation = ReactionInvestigation.objects.create(
        reaction=reaction,
        started_by=request.user,
    )
    write_audit(
        actor=request.user, action='investigation.start',
        entity_table='transfusion_reactioninvestigation', entity_id=investigation.pk,
        action_meaning=f'Started investigation workup for reaction #{reaction.pk}',
    )
    messages.info(request, 'Investigation workup opened.')
    return redirect('transfusion:investigation_update', reaction_pk=reaction_pk)


@login_required
def investigation_update(request, reaction_pk):
    """Update (or complete) the investigation workup."""
    reaction = get_object_or_404(TransfusionReaction, pk=reaction_pk)
    investigation = get_object_or_404(ReactionInvestigation, reaction=reaction)

    if request.method == 'POST':
        completing = 'complete' in request.POST

        # ABO repeat
        investigation.repeat_abo_patient = request.POST.get('repeat_abo_patient', '')
        investigation.repeat_abo_unit    = request.POST.get('repeat_abo_unit', '')
        abo_disc = request.POST.get('abo_discrepancy')
        investigation.abo_discrepancy = True if abo_disc == 'yes' else (
            False if abo_disc == 'no' else None
        )

        # DAT
        investigation.dat_result     = request.POST.get('dat_result', 'not_done')
        investigation.dat_specificity = request.POST.get('dat_specificity', '')

        # Haemolysis
        investigation.plasma_haemoglobin = request.POST.get('plasma_haemoglobin', 'not_done')
        investigation.urine_haemoglobin  = request.POST.get('urine_haemoglobin',  'not_done')
        bil = request.POST.get('plasma_bilirubin_umol', '').strip()
        investigation.plasma_bilirubin_umol = float(bil) if bil else None
        ldh = request.POST.get('plasma_ldh_iu', '').strip()
        investigation.plasma_ldh_iu = int(ldh) if ldh else None

        # Post-reaction serology
        investigation.repeat_antibody_screen   = request.POST.get('repeat_antibody_screen', 'not_done')
        investigation.new_antibody_identified   = request.POST.get('new_antibody_identified', '')

        # Bacteriology
        investigation.unit_culture          = request.POST.get('unit_culture', 'not_done')
        investigation.unit_culture_organism = request.POST.get('unit_culture_organism', '')
        investigation.patient_blood_culture = request.POST.get('patient_blood_culture', 'not_done')

        # DIC
        investigation.dic_screen_done = 'dic_screen_done' in request.POST
        for fld in ('dic_fibrinogen_g_l', 'dic_pt_seconds', 'dic_aptt_seconds'):
            val = request.POST.get(fld, '').strip()
            setattr(investigation, fld, float(val) if val else None)
        investigation.dic_d_dimer = request.POST.get('dic_d_dimer', '')

        # Conclusion
        investigation.conclusion     = request.POST.get('conclusion', '')
        investigation.shot_category  = request.POST.get('shot_category', '')
        investigation.shot_reportable = 'shot_reportable' in request.POST
        investigation.narrative      = request.POST.get('narrative', '')

        if completing:
            reauth_at = request.session.get('reauth_at')
            esign = create_signature(
                signer=request.user,
                meaning='verified',
                payload_data={'investigation_id': investigation.pk, 'reaction_id': reaction.pk},
                reauth_at=reauth_at,
            )
            investigation.esign        = esign
            investigation.completed_at = timezone.now()
            investigation.completed_by = request.user
            # Mirror SHOT reportable back to reaction
            reaction.reported_to_authority = investigation.shot_reportable
            reaction.save(update_fields=['reported_to_authority'])

        investigation.save()
        write_audit(
            actor=request.user,
            action='investigation.complete' if completing else 'investigation.update',
            entity_table='transfusion_reactioninvestigation', entity_id=investigation.pk,
            action_meaning='Investigation workup updated' + (' and completed' if completing else ''),
        )
        msg = 'Investigation completed and signed.' if completing else 'Investigation progress saved.'
        messages.success(request, msg)
        return redirect('transfusion:reaction_detail', pk=reaction.pk)

    return render(request, 'transfusion/investigation_update.html', {
        'reaction': reaction,
        'investigation': investigation,
        'dat_choices':    ReactionInvestigation.DAT_RESULTS,
        'haem_choices':   ReactionInvestigation.HAEMOLYSIS,
        'screen_choices': ReactionInvestigation.SCREEN_RESULT,
        'culture_choices': ReactionInvestigation.CULTURE_RESULT,
        'blood_culture_choices': ReactionInvestigation.BLOOD_CULTURE,
        'conclusion_choices': ReactionInvestigation.CONCLUSION,
        'shot_choices': ReactionInvestigation.SHOT_CATEGORIES,
    })
