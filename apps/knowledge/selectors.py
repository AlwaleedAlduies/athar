from django.db.models import Q, F, Exists, OuterRef
from apps.history.models import Entity, Status
from .models import Evidence, HistoricalClaim, EntityRelationship

def public_claims():
    return HistoricalClaim.objects.filter(status__in=[Status.APPROVED, Status.PUBLISHED], event__in=Entity.objects.visible()).select_related('event').prefetch_related('evidence__source')

def approved_evidence():
    return Evidence.objects.filter(claim__in=public_claims().filter(is_demo=False), source__is_approved=True,
                                   source__is_demo=False, source__in=Entity.objects.visible()).select_related('source', 'source_chunk', 'claim')

def trace_claim(claim):
    evidence = approved_evidence().filter(claim=claim)
    rows = [{'id': e.pk, 'text': e.evidence_text, 'source_id': e.source_id, 'source_title': e.source.title,
             'source_url': e.source.get_absolute_url(), 'page': e.page_number, 'section': e.section,
             'support': e.get_support_type_display(), 'support_type': e.support_type, 'notes': e.notes,
             'chunk_id': e.source_chunk_id, 'original_url': e.source.url, 'reference': e.source.publication_information} for e in evidence]
    kinds = {e['support_type'] for e in rows}
    confidence = 'الأدلة غير كافية'
    if rows:
        confidence = 'توجد روايات متعددة' if 'CONTRADICTS' in kinds or claim.claim_type == 'MULTIPLE_ACCOUNTS' else 'موثق' if claim.claim_type == 'FACT' and 'SUPPORTS' in kinds else 'مدعوم جزئيًا'
    classification = claim.get_claim_type_display() if rows else 'غير محسوم'
    if 'CONTRADICTS' in kinds:
        classification = 'تفسير / اختلاف روايات'
    elif claim.claim_type == 'FACT' and 'SUPPORTS' not in kinds:
        classification = 'غير محسوم' if not rows else 'تفسير / دعم جزئي'
    return {'id': claim.pk, 'claim': claim.claim_text, 'classification': classification,
            'evidence': rows, 'confidence': confidence, 'review_status': 'محتوى تجريبي — يحتاج مراجعة المصدر' if claim.is_demo else claim.get_status_display(),
            'context': claim.event.description,
            'other_accounts': list(public_claims().filter(event=claim.event, claim_type='MULTIPLE_ACCOUNTS', is_demo=False).exclude(pk=claim.pk).values('id', 'claim_text'))}

def graph_for(entity):
    edges = public_relationships().filter(Q(from_entity=entity) | Q(to_entity=entity))[:100]
    nodes = {entity.pk: entity}
    relations = []
    for edge in edges:
        nodes[edge.from_entity_id] = edge.from_entity
        nodes[edge.to_entity_id] = edge.to_entity
        relations.append({'id': edge.pk, 'source': edge.from_entity_id, 'target': edge.to_entity_id, 'label': edge.get_relation_type_display(),
                          'notes': edge.notes, 'claim_id': edge.supporting_claim_id})
    for mention in public_mentions().filter(Q(entity_id=entity.pk) | Q(source_id=entity.pk))[:60]:
        nodes[mention.entity_id] = mention.entity
        nodes[mention.source_id] = mention.source
        if not any(r['source']==mention.entity_id and r['target']==mention.source_id for r in relations):
            relations.append({'id':f'mention-{mention.pk}','source':mention.entity_id,'target':mention.source_id,
                'label':'مذكور في','notes':mention.context,'claim_id':None,'mention_id':mention.pk})
    return {'center': entity.pk, 'nodes': [{'id': n.pk, 'title': n.title, 'kind': n.kind, 'url': n.get_absolute_url(), 'is_demo': n.is_demo} for n in nodes.values()], 'edges': relations}


def public_mentions():
    from apps.sources.models import SourceMention
    return SourceMention.objects.filter(status__in=[Status.APPROVED,Status.PUBLISHED],
        entity__in=Entity.objects.visible(),source__in=Entity.objects.visible(),source__is_approved=True,
        source__is_demo=False,entity__is_demo=False,chunk__source_id=F('source_id')).select_related('entity','source','chunk')


def public_relationships():
    visible = Entity.objects.visible()
    supported = approved_evidence().filter(support_type__in=['SUPPORTS', 'PARTIALLY_SUPPORTS', 'CONTEXTUALIZES']).values('claim_id')
    consistent_event = Q(supporting_claim__event_id=F('from_entity_id')) | Q(supporting_claim__event_id=F('to_entity_id'))
    person_role = Q(from_entity__kind='person', to_entity__kind='event')
    source_link = Q(to_entity__kind='source', relation_type__in=['MENTIONED_IN', 'SUPPORTED_BY'])
    return EntityRelationship.objects.filter(status__in=[Status.APPROVED, Status.PUBLISHED],
        from_entity__in=visible, to_entity__in=visible).annotate(
        has_matching_source=Exists(approved_evidence().filter(claim_id=OuterRef('supporting_claim_id'), source_id=OuterRef('to_entity_id')))
    ).filter(
        Q(supporting_claim__isnull=True) | (Q(supporting_claim_id__in=supported) & consistent_event &
            (~person_role | Q(supporting_claim__person_id=F('from_entity_id'))) & (~source_link | Q(has_matching_source=True)))
    ).select_related('from_entity', 'to_entity', 'supporting_claim')
