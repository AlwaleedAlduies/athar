import json
import os
import time
from django.db.models import Q
from django.db import transaction
from apps.history.search import tokens, search_entities
from apps.sources.models import SourceChunk
from apps.knowledge.selectors import approved_evidence, graph_for, public_mentions
from apps.history.models import Entity
from .embeddings import embedding_service, similarity
from .providers import get_provider, ProviderUnavailable
from .prompts import HISTORIAN_PROMPT
from .models import AIConversation, AIMessage, AIQueryLog
from .configuration import active_identity

NO_EVIDENCE = 'لا تتوفر في المصادر المعتمدة حاليًا أدلة كافية للجزم بهذه المسألة.'

def retrieve(question, event=None):
    engine = embedding_service()
    vector = engine.embed(question)
    query_tokens = tokens(question)
    entity_scope = Entity.objects.visible()
    queryset = SourceChunk.objects.filter(source__is_approved=True, source__is_demo=False,
                                          source__in=Entity.objects.visible(), embedding_reference=engine.reference).select_related('source')
    # A source may cover many events. Only reviewed links to this specific
    # passage establish context; a source-level relation is not sufficient.
    if event:
        evidence = approved_evidence().filter(claim__event=event)
        mentions = public_mentions().filter(entity=event)
        queryset = queryset.filter(Q(pk__in=evidence.values('source_chunk_id')) |
                                   Q(pk__in=mentions.values('chunk_id')))
        entity_scope = entity_scope.filter(
            Q(pk=event.pk) | Q(pk__in=event.persons.values('pk')) |
            Q(pk__in=event.places.values('pk')) | Q(pk=event.location_id) |
            Q(pk__in=evidence.values('source_id')) | Q(pk__in=mentions.values('source_id')))
    matched_entities = search_entities(question, queryset=entity_scope, semantic=False)[:8]
    broad_context = event and any(x in question for x in ['أهم', 'مهم', 'نتائج', 'أثر', 'سبق', 'شارك', 'مصدر', 'حدث', 'قرار'])
    ranked = []
    for chunk in queryset.iterator():
        overlap = len(query_tokens & tokens(chunk.text + ' ' + chunk.source.title))
        score = similarity(vector, chunk.embedding)
        semantic = engine.reference.startswith('ollama:') and score >= .55
        if overlap or broad_context or semantic:
            ranked.append((score + min(overlap, 5) * .1, chunk))
    chunks = [c for _, c in sorted(ranked, key=lambda row: row[0], reverse=True)[:5]]
    return chunks, matched_entities

def parse_answer(raw, allowed_ids):
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('segments'), list) or len(data['segments']) > 8:
        raise ValueError('Invalid answer schema')
    for segment in data['segments']:
        if not isinstance(segment, dict) or not isinstance(segment.get('text'), str) or not segment['text'].strip() or len(segment['text']) > 2500:
            raise ValueError('Invalid segment')
        ids = segment.get('chunk_ids')
        if not isinstance(ids, list) or not ids or any(type(i) is not int or i not in allowed_ids for i in ids):
            raise ValueError('Unsupported citation')
    return data['segments']

def ask(question, user=None, event=None):
    started = time.monotonic()
    result = {'answer': NO_EVIDENCE, 'classification': 'UNCERTAIN', 'sources': [], 'evidence': [],
              'related_entities': [], 'confidence': 'الأدلة غير كافية', 'needs_review': True, 'mode': 'extractive', 'segments': []}
    chunks, failure = [], ''
    identity = active_identity()
    provider_name = identity['provider']
    try:
        chunks, entities = retrieve(question, event)
        result['related_entities'] = [{'id': e.pk, 'title': e.title, 'url': e.get_absolute_url()} for e in entities]
        if chunks:
            evidence_query = approved_evidence().filter(source_chunk__in=chunks)
            if event:
                evidence_query = evidence_query.filter(claim__event=event)
            evidence = list(evidence_query)
            result['evidence'] = [{'id': e.pk, 'claim_id': e.claim_id, 'claim': e.claim.claim_text,
                                   'event_id': e.claim.event_id, 'chunk_id': e.source_chunk_id,
                                   'text': e.evidence_text, 'support': e.get_support_type_display()} for e in evidence]
            provider = get_provider()
            if provider:
                payload = {'question': question, 'event': event.title if event else None,
                           'graph': graph_for(event) if event else {},
                           'chunks': [{'id': c.pk, 'text': c.text, 'source': c.source.title} for c in chunks],
                           'evidence': result['evidence']}
                result['segments'] = parse_answer(provider.generate(HISTORIAN_PROMPT, payload), {c.pk for c in chunks})
                result['mode'] = provider.name
                if result['segments']:
                    result['answer'] = '\n\n'.join(s['text'] for s in result['segments'])
                    result.update(classification='INTERPRETATION', confidence='شرح مستند إلى مصادر — يحتاج مراجعة', needs_review=True)
            else:
                # This is explicitly an extractive reader, never a simulated LLM response.
                result['segments'] = [{'text': c.text, 'chunk_ids': [c.pk]} for c in chunks[:3]]
                result['answer'] = 'هذه مقتطفات ذات صلة من المصادر المعتمدة:\n\n' + '\n\n'.join(s['text'] for s in result['segments'])
                result.update(classification='INTERPRETATION', confidence='مقتطفات مصدرية — دون استنتاج آلي')
            cited = {i for s in result['segments'] for i in s['chunk_ids']}
            result['evidence'] = [row for row in result['evidence'] if row['chunk_id'] in cited]
            evidence = [row for row in evidence if row.source_chunk_id in cited]
            result['sources'] = [{'id': c.source_id, 'chunk_id': c.pk, 'title': c.source.title, 'page': c.page_number,
                                  'section': c.section, 'url': c.source.get_absolute_url(), 'excerpt': c.text} for c in chunks if c.pk in cited]
            if result['segments'] and any(e.support_type == 'CONTRADICTS' or e.claim.claim_type == 'MULTIPLE_ACCOUNTS' for e in evidence):
                result['classification'] = 'MULTIPLE_ACCOUNTS'
                result['confidence'] = 'توجد روايات متعددة'
    except Exception as exc:
        # Never return provider payloads, keys, or raw server exceptions to the browser.
        failure = str(exc) if isinstance(exc, ProviderUnavailable) else type(exc).__name__
        result.update(answer='تعذر الوصول إلى المرشد الذكي حاليًا، وما زال بإمكانك استكشاف المحتوى الموثق والمصادر.',
                      classification='UNCERTAIN', confidence='تعذرت الإجابة', needs_review=True, segments=[], sources=[],
                      evidence=[], related_entities=[], mode='unavailable')
    with transaction.atomic():
        log = AIQueryLog.objects.create(user=user if user and user.is_authenticated else None, question=question, event=event,
                              answer=result['answer'], structured_answer=result,
                              retrieved_source_ids=list({c.source_id for c in chunks}), retrieved_chunk_ids=[c.pk for c in chunks],
                              classification=result['classification'], confidence=result['confidence'], needs_review=result['needs_review'],
                              latency_ms=int((time.monotonic() - started) * 1000), provider=provider_name,
                              model=identity['model'], failure_reason=failure)
        if user and user.is_authenticated:
            conversation = AIConversation.objects.create(user=user, event=event)
            AIMessage.objects.bulk_create([AIMessage(conversation=conversation, role='user', content=question),
                                       AIMessage(conversation=conversation, role='assistant', content=result['answer'], structured_answer=result)])
    if user and user.is_authenticated:
        result['history_url'] = f'/library/answers/{log.pk}/'
    return result
