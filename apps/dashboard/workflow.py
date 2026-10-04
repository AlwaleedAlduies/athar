"""Read-only editorial guidance. Publication still uses the validated forms."""
from django.db.models import Q
from django.urls import reverse
from apps.history.models import HistoricalEvent, StoryPassage, Entity, Status
from apps.sources.models import HistoricalSource, SourceChunk
from apps.knowledge.models import HistoricalClaim, Evidence


def route(section, pk=None, **filters):
    from urllib.parse import urlencode
    url = reverse('dashboard-edit', args=[section, pk]) if pk else reverse('dashboard-new', args=[section])
    return url + ('?' + urlencode(filters) if filters else '')


def parent_context(record):
    if isinstance(record, Evidence):
        return {'title': 'العودة إلى المعلومة', 'url': route('claims', record.claim_id)} if record.claim_id else None
    if isinstance(record, SourceChunk):
        return {'title': 'العودة إلى المصدر', 'url': route('sources', record.source_id)} if record.source_id else None
    if getattr(record, 'event_id', None):
        return {'title': 'العودة إلى الحدث', 'url': route('events', record.event_id)}
    return None


def form_parent(form):
    parent = parent_context(form.instance)
    if parent:
        return parent
    # Prefilled new forms can return to their context after the first save.
    for field, model, section, label in [('claim', HistoricalClaim, 'claims', 'العودة إلى المعلومة'),
            ('event', HistoricalEvent, 'events', 'العودة إلى الحدث'),
            ('source', HistoricalSource, 'sources', 'العودة إلى المصدر')]:
        value = form.initial.get(field)
        if field in form.fields and str(value or '').isdigit() and model.objects.filter(pk=value).exists():
            return {'title': label, 'url': route(section, int(value))}
    return None


def form_sections(form, section):
    definitions = {
        'events': [('basic', 'هوية الحدث', ['title', 'description', 'era', 'event_type', 'featured_image']),
                   ('dates', 'الزمان والمكان', ['hijri_label', 'gregorian_label', 'year_order', 'date_precision', 'location']),
                   ('links', 'الشخصيات والمصادر والروابط', ['persons', 'places', 'sources', 'related_events']),
                   ('summary', 'الملخص البديل عند غياب السرد المنشور', ['narrative', 'context', 'causes', 'decisions', 'consequences', 'aftermath'])],
        'passages': [('basic', 'الفقرة داخل الحكاية', ['event', 'chapter', 'position', 'text']),
                     ('links', 'استشهادات الفقرة', ['citations'])],
        'claims': [('basic', 'المعلومة وسياقها', ['event', 'claim_text', 'claim_type', 'person', 'place']),
                   ('review', 'ملاحظات المراجع', ['review_notes'])],
        'sources': [('basic', 'بيانات المرجع', ['title', 'author', 'source_type', 'language', 'description']),
                    ('document', 'النص الأصلي وموضعه', ['url', 'file', 'publication_information'])],
        'evidence': [('basic', 'ربط الدليل', ['claim', 'source', 'source_chunk']),
                     ('quote', 'الاقتباس وموضعه', ['evidence_text', 'page_number', 'section']),
                     ('review', 'كيف يدعم المعلومة؟', ['support_type', 'notes'])],
    }
    groups, assigned = [], set()
    def add(key, title, names, collapsed=False):
        fields = [form[name] for name in names if name in form.fields and name not in assigned]
        if fields:
            groups.append({'key': key, 'title': title, 'fields': fields,
                           'collapsed': collapsed and not any(field.errors for field in fields)})
            assigned.update(field.name for field in fields)
    for key, title, names in definitions.get(section, []):
        add(key, title, names, collapsed=key == 'summary')
    reserved = ['slug', 'english_title', 'status', 'is_approved', 'is_demo', 'ai_suggested']
    add('details', 'بيانات المحتوى', [name for name in form.fields if name not in reserved])
    add('publication', 'المراجعة والظهور للزوار', ['status', 'is_approved'])
    add('advanced', 'خيارات إضافية', ['slug', 'english_title', 'is_demo', 'ai_suggested'], collapsed=True)
    return groups


def guidance(section, record):
    guide = {'title': 'ابدأ بحفظ مسودة', 'text': 'املأ الحقول الأساسية؛ يمكنك إكمال الربط والمراجعة بعد الحفظ.', 'steps': []}
    if record is None:
        if section == 'evidence':
            guide.update(title='وثّق المعلومة باقتباس', text='اختر المعلومة ثم المصدر والمقطع، وانسخ الاقتباس وحدد نوع دعمه. بعد الحفظ عد إلى المعلومة لاعتمادها.')
        return guide
    guide.update(title='راجع المحتوى واحفظ التغييرات', text='حرر البيانات والروابط، ثم راجع حالة الظهور قبل الحفظ. لا تنشر التغييرات بمجرد مغادرة الصفحة.')
    if getattr(record, 'status', None) == Status.ARCHIVED:
        return {**guide, 'title': 'هذا المحتوى في الأرشيف', 'text': 'استخدم الاستعادة كمسودة أسفل الصفحة، ثم راجع الروابط قبل إعادة نشره.'}
    if isinstance(record, HistoricalEvent):
        live_states = [Status.APPROVED, Status.PUBLISHED]
        sources = HistoricalSource.objects.filter(Q(events=record) | Q(evidence__claim__event=record)).distinct()
        ready_sources = sources.filter(is_approved=True, status__in=live_states, is_demo=False, deleted_at__isnull=True).exists()
        claims = record.claims.exclude(status__in=[Status.ARCHIVED, Status.REJECTED]).filter(is_demo=False)
        ready_claims = claims.filter(status__in=live_states, evidence__source__is_approved=True,
            evidence__source__status__in=live_states, evidence__source__is_demo=False,
            evidence__source__deleted_at__isnull=True).exists()
        passages = record.story_passages.exclude(status__in=[Status.ARCHIVED, Status.REJECTED])
        visible = Entity.objects.visible().filter(pk=record.pk).exists()
        from apps.history.story import public_passages
        shown = public_passages().filter(event=record).count()
        guide['steps'] = [
            {'title': 'المصدر', 'done': ready_sources, 'detail': 'مرجع معتمد يدعم الحدث'},
            {'title': 'المعلومات والأدلة', 'done': ready_claims, 'detail': 'معلومات مراجعة باقتباساتها'},
            {'title': 'مسودة الحكاية', 'done': passages.exists(), 'detail': 'فقرات مرتبة واستشهادات'},
            {'title': 'ظهور الحدث', 'done': visible, 'detail': 'مراجعة حالة الحدث'},
            {'title': 'نشر السرد', 'done': shown > 0 and shown == passages.count(), 'detail': f'{shown} فقرات متاحة للزائر'},
        ]
        if not ready_sources:
            guide.update(title='الخطوة التالية: جهّز مصدرًا موثقًا', text='أضف مصدرًا أو اختر مصدرًا محفوظًا في روابط الحدث، ثم راجع نصه واعتمده.', action='أضف مصدرًا', url=reverse('source-intake'))
        elif not ready_claims:
            first = claims.order_by('pk').first()
            guide.update(title='الخطوة التالية: وثّق المعلومات', text='احفظ المعلومة كمسودة، وأضف اقتباسها من مصدر معتمد، ثم عد لاعتمادها.', action='راجع المعلومة' if first else 'أضف معلومة', url=route('claims', first.pk) if first else route('claims', event=record.pk))
        elif not passages.exists():
            guide.update(title='الخطوة التالية: اكتب الحكاية', text='أنشئ فقرات السرد كمسودات، ورتبها داخل الفصول واربط كل فقرة بمعلوماتها.', action='أضف فقرة سردية', url=route('passages', event=record.pk))
        elif not visible:
            guide.update(title='الخطوة التالية: راجع ظهور الحدث', text='المعلومات الموثقة جاهزة. راجع بيانات الحدث واختر «منشور» في حالة النشر واحفظ، ثم انشر فقراته. تبقى الفقرات مسودات حتى تراجعها.', action='راجع حالة النشر', url='#group-publication')
        elif shown != passages.count():
            first = passages.exclude(pk__in=public_passages().values('pk')).order_by('position', 'pk').first()
            guide.update(title='الخطوة التالية: راجع فقرات السرد', text='افحص الاستشهادات ثم انشر الفقرات. قد تبقى فقرة مخفية إذا أصبح مصدرها غير معتمد.', action='راجع الفقرة التالية', url=route('passages', first.pk))
        else:
            guide.update(title='الحكاية متاحة للقراءة', text='هذه مؤشرات جاهزية النشر، وليست حكمًا باكتمال التغطية التاريخية. يمكنك متابعة إثراء الفقرات والأدوار من المحتوى المرتبط.', action='افتح صفحة الزائر', url=record.get_absolute_url())
    elif isinstance(record, HistoricalClaim):
        if not record.evidence.exists():
            guide.update(title='الخطوة التالية: أضف الدليل', text='المعلومة محفوظة. اربط اقتباسًا حرفيًا من مصدر معتمد قبل تغيير حالة المراجعة.', action='أضف دليلًا لهذه المعلومة', url=route('evidence', claim=record.pk))
        elif record.status not in [Status.APPROVED, Status.PUBLISHED]:
            guide.update(title='الخطوة التالية: راجع المعلومة واعتمدها', text='راجع الأدلة المرتبطة وتصنيف المعلومة، ثم اختر «معتمد» واحفظ. سيوضح النموذج أي نقص يمنع اعتمادها.', action='راجع حالة المراجعة', url='#group-publication')
        else:
            guide.update(title='المعلومة مراجعة', text='ارجع إلى الحدث لإكمال الحكاية وربط الفقرات بهذه المعلومة.', action='تابع تحرير الحدث', url=route('events', record.event_id))
    elif isinstance(record, Evidence):
        guide.update(title='الخطوة التالية: راجع المعلومة الأصلية', text='حفظ الدليل لا يعتمد المعلومة تلقائيًا. تأكد من صحة الاقتباس وموضعه ثم عد لمراجعة المعلومة.', action='افتح المعلومة', url=route('claims', record.claim_id))
    elif isinstance(record, StoryPassage):
        if not Entity.objects.visible().filter(pk=record.event_id).exists():
            guide.update(title='الحدث ما زال غير متاح للزوار', text='احفظ الفقرة كمسودة. راجع مصادر الحدث ومعلوماته، ثم انشر الحدث قبل نشر فقراته.', action='راجع جاهزية الحدث', url=route('events', record.event_id))
        else:
            guide.update(title='راجع الاستشهادات ثم حالة الفقرة', text='اختر معلومات الحدث التي تدعم النص، وحدد الفصل والترتيب. المسودة لا تظهر للزائر؛ النشر يتطلب مصدرًا معتمدًا لكل استشهاد.', action='راجع استشهادات الفقرة', url='#group-links')
    elif isinstance(record, HistoricalSource):
        guide.update(title='اقرأ النص قبل اعتماده', text='اتبع خطوات جاهزية المصدر أدناه: قراءة النص، مراجعة المقاطع، الاعتماد، ثم مراجعة اقتراحات التحليل. اعتماد المصدر لا ينشر المقترحات.')
    return guide
