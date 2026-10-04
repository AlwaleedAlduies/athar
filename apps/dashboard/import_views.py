import os
import uuid
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.ai.embeddings import HashEmbedding
from apps.history.models import Status
from apps.sources.models import HistoricalSource, SourceChunk
from apps.sources.services import process_source, split_text
from apps.sources.web_import import fetch_page
from .models import ExtractionRun
from .views import admin_required, admin_context
from .import_forms import ImportSourceForm, SuggestionReviewForm
from .extraction import generate_suggestions, save_drafts
from apps.ai.configuration import active_identity


@admin_required
def studio(request):
    initial = {'input_kind': 'url', 'event': request.GET.get('event')}
    source_id = request.GET.get('source', '')
    if source_id.isdigit() and HistoricalSource.objects.filter(pk=source_id, is_demo=False, deleted_at__isnull=True).exists():
        initial.update(input_kind='existing', source=int(source_id))
    form = ImportSourceForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        previous = ExtractionRun.objects.filter(token=data['token'], created_by=request.user).first()
        if previous:
            return redirect('extraction-run', pk=previous.pk)
        source = None
        uploaded_name = None
        try:
            text, final_url = '', ''
            if data['input_kind'] == 'url':
                final_url, text = fetch_page(data['url'])
            with transaction.atomic():
                if data['input_kind'] == 'existing':
                    source = data['source']
                    if not source.chunks.exists():
                        process_source(source)
                else:
                    source = HistoricalSource.objects.create(title=data['title'], slug=f'import-{uuid.uuid4().hex}',
                        source_type='digital' if text else 'other', url=final_url, status=Status.DRAFT, is_approved=False,
                        created_by=request.user, file=data['document'] if data['input_kind'] == 'file' else '',
                        publication_information=f'استيراد خاص للمراجعة بتاريخ {timezone.localdate()}.',
                        description='مصدر مستورد ينتظر مراجعة أمين المعرفة.')
                    if text:
                        engine = HashEmbedding()
                        SourceChunk.objects.bulk_create([SourceChunk(source=source, ordinal=i, section=f'نص الصفحة · مقطع {i + 1}',
                            text=part, embedding=engine.embed(part), embedding_reference=engine.reference) for i, part in enumerate(split_text(text))])
                        source.processed_at = timezone.now(); source.save(update_fields=['processed_at'])
                    else:
                        uploaded_name = source.file.name
                        process_source(source)
                run = ExtractionRun.objects.create(token=data['token'], event=data['event'], source=source, created_by=request.user, focus=data['focus'])
            return redirect('extraction-run', pk=run.pk)
        except ValidationError as exc:
            if uploaded_name:
                source.file.storage.delete(uploaded_name)
            form.add_error(None, ' '.join(exc.messages))
        except Exception:
            if uploaded_name:
                source.file.storage.delete(uploaded_name)
            form.add_error(None, 'تعذر تجهيز المصدر. تحقق من الملف أو الرابط ثم أعد المحاولة.')
    return render(request, 'dashboard/studio.html', admin_context(section='studio', form=form, runs=ExtractionRun.objects.select_related('source', 'event')[:12]))


@admin_required
def run_detail(request, pk):
    run = get_object_or_404(ExtractionRun.objects.select_related('source', 'event'), pk=pk)
    rows, selections, forms_valid = [], {}, True
    chunks = {c.pk: c for c in run.source.chunks.all()}
    for index, row in enumerate(run.suggestions):
        initial = {**row, 'person': row.get('person_id'), 'place': row.get('place_id'), 'role': row.get('role') or 'RELATED_TO'}
        form = SuggestionReviewForm(request.POST if request.method == 'POST' else None, prefix=str(index), initial=initial)
        if request.method == 'POST' and request.POST.get(f'{index}-selected'):
            if form.is_valid():
                data = form.cleaned_data
                selections[index] = {k: data[k] for k in ['claim', 'chapter', 'story', 'classification', 'role']}
                selections[index].update(person_id=data['person'].pk if data['person'] else None, place_id=data['place'].pk if data['place'] else None)
            else:
                forms_valid = False
        rows.append({'form': form, 'number': index + 1, 'citations': [{**ref, 'chunk': chunks.get(ref['chunk_id'])} for ref in row['citations']]})
    if request.method == 'POST' and forms_valid:
        try:
            save_drafts(run, selections, request.user)
            messages.success(request, 'حُفظت المعلومات وأدلتها والفقرات كمسودات مرتبطة. راجع المصدر ثم اعتمد المعلومات والفقرات للنشر.')
            return redirect('extraction-run', pk=run.pk)
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
    return render(request, 'dashboard/extraction_run.html', admin_context(section='studio', run=run, chunks=list(chunks.values()),
        rows=rows, **active_identity(),
        claim_ids=run.created_claim_ids, passage_ids=run.created_passage_ids))


@admin_required
@require_POST
def extract(request, pk):
    run = get_object_or_404(ExtractionRun, pk=pk)
    try:
        ids = request.POST.getlist('chunks')
        if any(not i.isdigit() for i in ids):
            raise ValidationError('اختيار المقاطع غير صالح.')
        generate_suggestions(run, [int(i) for i in ids])
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    return redirect('extraction-run', pk=pk)
