"""Navigation and dependency information for the editorial screens."""
from django.db.models import Q, Max
from django.urls import reverse
from apps.history.models import HistoricalEvent, StoryPassage, Entity
from apps.knowledge.models import HistoricalClaim, Evidence, EntityRelationship
from apps.sources.models import HistoricalSource, SourceChunk, SourceMention


def initial_values(section, params):
    allowed = {'passages': ['event'], 'claims': ['event', 'person', 'place'], 'evidence': ['claim', 'source', 'source_chunk'],
               'chunks': ['source'], 'relationships': ['from_entity', 'to_entity', 'supporting_claim'],
               'mentions': ['source', 'entity', 'chunk'], 'simulations': ['event']}
    values = {key: int(params[key]) for key in allowed.get(section, []) if params.get(key, '').isdigit()}
    if section == 'passages' and values.get('event'):
        values['position'] = (StoryPassage.objects.filter(event_id=values['event']).aggregate(n=Max('position'))['n'] or 0) + 1
    if section == 'chunks' and values.get('source'):
        last = SourceChunk.objects.filter(source_id=values['source']).aggregate(n=Max('ordinal'))['n']
        values['ordinal'] = 0 if last is None else last + 1
    if section == 'evidence' and values.get('source_chunk'):
        chunk = SourceChunk.objects.filter(pk=values['source_chunk']).first()
        if chunk:
            values.update(source=chunk.source_id, evidence_text=chunk.text, page_number=chunk.page_number, section=chunk.section)
    return values


def workspace(record):
    groups = []
    def add(title, section, rows, query):
        groups.append({'title': title, 'section': section, 'rows': rows[:12], 'count': rows.count(),
                       'list_url': reverse('dashboard-list', args=[section]) + '?' + query,
                       'add_url': reverse('dashboard-new', args=[section]) + '?' + query})
    if isinstance(record, HistoricalEvent):
        add('الفصول وفقرات السرد', 'passages', record.story_passages.order_by('position', 'pk'), f'event={record.pk}')
        add('المعلومات واستشهاداتها', 'claims', record.claims.order_by('pk'), f'event={record.pk}')
        add('أدلة المعلومات', 'evidence', Evidence.objects.filter(claim__event=record).order_by('pk'), f'event={record.pk}')
        add('أدوار الشخصيات والأماكن وصلات الأحداث', 'relationships', EntityRelationship.objects.filter(Q(from_entity=record) | Q(to_entity=record)).order_by('pk'), f'event={record.pk}&to_entity={record.pk}')
        add('أنشطة المحاكاة', 'simulations', record.simulations.order_by('pk'), f'event={record.pk}')
    elif isinstance(record, HistoricalClaim):
        add('الأدلة المرتبطة بهذه المعلومة', 'evidence', record.evidence.order_by('pk'), f'claim={record.pk}')
        add('الفقرات التي تستخدم هذا الاستشهاد', 'passages', record.story_passages.order_by('position'), f'event={record.event_id}')
    elif isinstance(record, HistoricalSource):
        add('نصوص المصدر', 'chunks', record.chunks.order_by('ordinal'), f'source={record.pk}')
        add('أدلة تعتمد على المصدر', 'evidence', Evidence.objects.filter(source=record).order_by('pk'), f'source={record.pk}')
        add('الأسماء المذكورة في المصدر', 'mentions', record.mentions.order_by('pk'), f'source={record.pk}')
    elif isinstance(record, SourceChunk):
        add('أدلة تستخدم المقطع', 'evidence', Evidence.objects.filter(source_chunk=record).order_by('pk'), f'source={record.source_id}&source_chunk={record.pk}')
    elif isinstance(record, Entity) and record.kind in ['person', 'place', 'era']:
        add('الروابط والأدوار', 'relationships', EntityRelationship.objects.filter(Q(from_entity=record) | Q(to_entity=record)).order_by('pk'), f'entity={record.pk}&from_entity={record.pk}')
    return groups


def removal_impact(record):
    claims = HistoricalClaim.objects.none()
    if isinstance(record, HistoricalSource): claims = HistoricalClaim.objects.filter(evidence__source=record)
    elif isinstance(record, SourceChunk): claims = HistoricalClaim.objects.filter(evidence__source_chunk=record)
    elif isinstance(record, Evidence): claims = HistoricalClaim.objects.filter(pk=record.claim_id)
    elif isinstance(record, HistoricalClaim): claims = HistoricalClaim.objects.filter(pk=record.pk)
    elif isinstance(record, HistoricalEvent): claims = record.claims.all()
    return {'passages': StoryPassage.objects.filter(citations__in=claims).distinct().count(),
            'relationships': EntityRelationship.objects.filter(supporting_claim__in=claims).count(),
            'claims': claims.distinct().count(),
            'protected_chunk': isinstance(record, SourceChunk) and (record.evidence_set.exists() or record.mentions.exists())}
