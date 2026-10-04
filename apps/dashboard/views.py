from functools import wraps
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone
from apps.accounts.permissions import is_admin
from apps.accounts.models import User
from apps.ai.models import AIQueryLog
from apps.ai.services import ask
from apps.history.models import Status, HistoricalEvent
from apps.sources.models import HistoricalSource, SourceChunk
from apps.sources.services import process_source
from apps.knowledge.models import HistoricalClaim
from .forms import REGISTRY, editor_form
from .editorial import initial_values, workspace, removal_impact

def admin_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('/login/?next=' + request.path)
        if not is_admin(request.user):
            return render(request, 'error.html', {'message': 'هذه الرحلة مخصصة لأمناء المعرفة.'}, status=403)
        return view(request, *args, **kwargs)
    return wrapped

def admin_context(**kwargs):
    return {'admin_nav': [(key, value[1]) for key, value in REGISTRY.items()], **kwargs}

@admin_required
def dashboard(request):
    stats = [(label, model.objects.count(), key) for key, (model, label) in REGISTRY.items() if key in ['events', 'persons', 'places', 'sources']]
    stats += [('ادعاءات تنتظر المراجعة', HistoricalClaim.objects.filter(status__in=[Status.DRAFT, Status.REVIEW]).count(), 'claims'),
              ('مصادر غير معالجة', HistoricalSource.objects.filter(processed_at__isnull=True).count(), 'sources'),
              ('أسئلة تحتاج مراجعة', AIQueryLog.objects.filter(needs_review=True).count(), 'logs')]
    return render(request, 'dashboard/home.html', admin_context(stats=stats, logs=AIQueryLog.objects.select_related('user', 'event')[:6]))

@admin_required
def collection(request, section):
    if section == 'users':
        rows, title = User.objects.order_by('-date_joined'), 'المستخدمون'
    elif section == 'logs':
        rows, title = AIQueryLog.objects.select_related('user', 'event').all(), 'سجل أسئلة الذكاء الاصطناعي'
        if request.GET.get('review'):
            rows = rows.filter(needs_review=True)
    elif section in REGISTRY:
        model, title = REGISTRY[section]
        rows = model.objects.order_by('-pk')
        names = {field.name for field in model._meta.fields}
        if 'status' in names:
            state = request.GET.get('status', '')
            if state in Status.values:
                rows = rows.filter(status=state)
            elif state != 'all':
                rows = rows.exclude(status=Status.ARCHIVED)
        query = request.GET.get('q', '').strip()[:200]
        if query:
            search = Q()
            for name in ['title', 'description', 'chapter', 'text', 'claim_text', 'evidence_text', 'notes', 'context', 'section', 'key', 'value']:
                if name in names: search |= Q(**{name + '__icontains': query})
            if 'event' in names: search |= Q(event__title__icontains=query)
            if 'source' in names: search |= Q(source__title__icontains=query)
            if 'from_entity' in names: search |= Q(from_entity__title__icontains=query) | Q(to_entity__title__icontains=query)
            if query.isdigit(): search |= Q(pk=int(query))
            rows = rows.filter(search)
        event_id = request.GET.get('event', '')
        if event_id.isdigit():
            if 'event' in names: rows = rows.filter(event_id=event_id)
            elif section == 'evidence': rows = rows.filter(claim__event_id=event_id)
            elif section == 'relationships': rows = rows.filter(Q(from_entity_id=event_id) | Q(to_entity_id=event_id))
        entity_id = request.GET.get('entity', '')
        if entity_id.isdigit() and section == 'relationships':
            rows = rows.filter(Q(from_entity_id=entity_id) | Q(to_entity_id=entity_id))
        for field in ['source', 'claim', 'source_chunk']:
            if field in names and request.GET.get(field, '').isdigit(): rows = rows.filter(**{field + '_id': request.GET[field]})
        if section == 'passages': rows = rows.order_by('event__year_order', 'event_id', 'position', 'pk')
    else:
        raise Http404()
    page = Paginator(rows, 20).get_page(request.GET.get('page'))
    filters = request.GET.copy(); filters.pop('page', None)
    return render(request, 'dashboard/list.html', admin_context(section=section, title=title, page=page, editable=section in REGISTRY,
        query=request.GET.get('q', ''), filter_query=filters.urlencode(), statuses=Status.choices,
        supports_status=section in REGISTRY and hasattr(REGISTRY[section][0], 'status'),
        events=HistoricalEvent.objects.filter(deleted_at__isnull=True).order_by('year_order', 'pk'),
        supports_event=section in ['passages', 'claims', 'evidence', 'relationships', 'simulations']))

@admin_required
def edit(request, section, pk=None):
    if section == 'sources' and pk is None and request.method == 'GET' and request.GET.get('manual') != '1':
        return redirect('source-intake')
    if section not in REGISTRY:
        raise Http404()
    model, title = REGISTRY[section]
    instance = get_object_or_404(model, pk=pk) if pk else None
    form = editor_form(model)(request.POST if request.method == 'POST' else None, request.FILES or None,
                              instance=instance, initial=initial_values(section, request.GET) if not pk else None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            record = form.save(commit=False)
            if isinstance(record, SourceChunk):
                from apps.ai.embeddings import HashEmbedding
                engine = HashEmbedding()
                record.embedding = engine.embed(record.text)
                record.embedding_reference = engine.reference
            if not pk and hasattr(record, 'created_by'):
                record.created_by = request.user
            if getattr(record, 'status', None) in [Status.APPROVED, Status.PUBLISHED]:
                if hasattr(record, 'reviewed_by'):
                    record.reviewed_by = request.user
                if hasattr(record, 'approved_by'):
                    record.approved_by = request.user
            record.save()
            form.save_m2m()
            from apps.history.models import StoryPassage
            if isinstance(record, StoryPassage):
                from apps.history.story import sync_story_references
                sync_story_references(record)
        if section == 'sources' and request.FILES.get('file'):
            from .source_analysis import create_analysis, start_analysis
            try:
                process_source(record)
                run = create_analysis(record, request.user)
                transaction.on_commit(lambda: start_analysis(run.pk))
                return redirect('source-analysis', pk=run.pk)
            except Exception:
                messages.error(request, 'حُفظ المصدر، لكن تعذرت قراءة الملف للتحليل. راجع نوعه ثم أعد المعالجة.')
        messages.success(request, 'حُفظ المحتوى. تنعكس حالة النشر مباشرة في رحلة المستكشف.')
        return redirect('dashboard-edit', section=section, pk=record.pk)
    return render(request, 'dashboard/edit.html', admin_context(section=section, title=title, form=form, record=instance,
                  workspace=workspace(instance) if instance else [],
                  chunks=instance.chunks.all()[:100] if section == 'sources' and instance else []))

@admin_required
@require_POST
def process(request, pk):
    source = get_object_or_404(HistoricalSource, pk=pk)
    try:
        count = process_source(source)
        messages.success(request, f'أصبحت {count} مقاطع جاهزة للاسترجاع. حُفظت مواضع النص والاستشهادات؛ يظهر المصدر للمرشد بعد اعتماده.')
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    except Exception:
        messages.error(request, 'تعذرت معالجة المصدر. تحقق من الملف وإعداد خدمة التضمين.')
    return redirect('dashboard-edit', section='sources', pk=pk)


@admin_required
@require_POST
def approve_source(request, pk):
    source = get_object_or_404(HistoricalSource,pk=pk)
    try:
        if source.is_demo or source.deleted_at or source.status in [Status.ARCHIVED,Status.REJECTED]:
            raise ValidationError('راجع حالة المصدر أولًا؛ لا يُعتمد المصدر التجريبي أو المؤرشف أو المرفوض.')
        process_source(source)
        with transaction.atomic():
            source = HistoricalSource.objects.select_for_update().get(pk=pk)
            if source.is_demo or source.deleted_at or source.status in [Status.ARCHIVED,Status.REJECTED]:
                raise ValidationError('تغيرت حالة المصدر أثناء المعالجة؛ أعد مراجعته.')
            source.is_approved = True
            if source.status != Status.PUBLISHED: source.status = Status.APPROVED
            source.reviewed_by = request.user
            source.full_clean(); source.save()
        messages.success(request,'اعتُمد المصدر وأصبح متاحًا للاسترجاع. تبقى المعلومات والشخصيات المستخرجة خاضعة لمراجعتها المستقلة.')
    except ValidationError as error:
        messages.error(request,' '.join(error.messages))
    except Exception:
        messages.error(request,'تعذرت تهيئة المصدر للاعتماد. بقيت حالته السابقة؛ راجع النص أو إعداد خدمة التضمين.')
    return redirect('dashboard-edit',section='sources',pk=pk)

@admin_required
@require_POST
def remove(request, section, pk):
    if section not in REGISTRY:
        raise Http404()
    record = get_object_or_404(REGISTRY[section][0], pk=pk)
    if hasattr(record, 'status'):
        record.status = Status.ARCHIVED
        if hasattr(record, 'is_approved'):
            record.is_approved = False
        record.save()
    else:
        try:
            record.delete()
        except ProtectedError:
            messages.error(request, 'هذا المقطع مستخدم في أدلة أو روابط ذكر. صحح هذه الروابط أو انقلها إلى مقطع بديل قبل حذفه.')
            return redirect('dashboard-edit', section=section, pk=pk)
    messages.success(request, 'تمت إزالة المحتوى من العرض.')
    return redirect('dashboard-list', section=section)


@admin_required
def removal_preview(request, section, pk):
    if section not in REGISTRY:
        raise Http404()
    record = get_object_or_404(REGISTRY[section][0], pk=pk)
    return render(request, 'dashboard/remove.html', admin_context(section=section, record=record,
        title=REGISTRY[section][1], impact=removal_impact(record), can_restore=hasattr(record, 'status')))


@admin_required
@require_POST
def restore(request, section, pk):
    if section not in REGISTRY or not hasattr(REGISTRY[section][0], 'status'):
        raise Http404()
    record = get_object_or_404(REGISTRY[section][0], pk=pk, status=Status.ARCHIVED)
    record.status = Status.DRAFT
    if hasattr(record, 'deleted_at'): record.deleted_at = None
    if hasattr(record, 'is_approved'): record.is_approved = False
    record.save()
    messages.success(request, 'استُعيد المحتوى كمسودة. راجعه ثم اعتمده أو انشره من النموذج.')
    return redirect('dashboard-edit', section=section, pk=pk)


@admin_required
def editor_options(request):
    if request.GET.get('source', '').isdigit():
        chunks = SourceChunk.objects.filter(source_id=request.GET['source']).order_by('ordinal')
        return JsonResponse({'items': [{'id': c.pk, 'label': str(c), 'text': c.text, 'page': c.page_number, 'section': c.section} for c in chunks]})
    if request.GET.get('event', '').isdigit():
        claims = HistoricalClaim.objects.filter(event_id=request.GET['event']).order_by('pk')
        return JsonResponse({'items': [{'id': c.pk, 'label': str(c), 'status': c.get_status_display()} for c in claims]})
    return JsonResponse({'items': []})

@admin_required
@require_POST
def suggest(request, pk):
    event = get_object_or_404(HistoricalEvent, pk=pk)
    answer = ask('ما أهم ما ورد في المصادر عن هذا الحدث؟', request.user, event)
    if answer['segments']:
        claim = HistoricalClaim.objects.create(event=event, claim_text=answer['answer'], claim_type='UNCERTAIN',
                                               ai_suggested=True, created_by=request.user, status=Status.DRAFT,
                                               review_notes='اقتراح يحتاج تدقيقًا وربطًا بالأدلة. لا ينشر تلقائيًا.')
        return redirect('dashboard-edit', section='claims', pk=claim.pk)
    messages.error(request, 'لم يتوفر دليل معتمد كافٍ لإنشاء اقتراح.')
    return redirect('dashboard-edit', section='events', pk=pk)
