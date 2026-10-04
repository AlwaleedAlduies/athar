import json
import os
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from apps.ai.embeddings import HashEmbedding
from apps.ai.models import AIQueryLog
from apps.ai.services import ask, retrieve
from apps.history.models import HistoricalEra, HistoricalEvent, HistoricalPerson
from apps.knowledge.models import Evidence, HistoricalClaim
from apps.sources.models import HistoricalSource, SourceChunk, SourceMention


@override_settings(DEMO_MODE=False)
class AskEventScopeTests(TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'EMBEDDING_BACKEND': 'hash', 'LLM_PROVIDER': 'extractive'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        era = HistoricalEra.objects.create(title='حقبة', slug='scope-era', status='PUBLISHED')
        self.event = HistoricalEvent.objects.create(title='الخندق', slug='scope-event', era=era, status='PUBLISHED')
        self.other = HistoricalEvent.objects.create(title='أُحد', slug='scope-other', era=era, status='PUBLISHED')
        self.source = HistoricalSource.objects.create(title='مرجع متعدد الأحداث', slug='scope-source', status='APPROVED', is_approved=True)
        self.event.sources.add(self.source)
        self.other.sources.add(self.source)
        self.chunk, self.claim = self.add_evidence(self.event, 0, 'خبر الحفر في الخندق')
        self.other_chunk, self.other_claim = self.add_evidence(self.other, 1, 'خبر الرماة في أُحد')
        # One passage can also support distinct claims for different events.
        self.shared_claim = HistoricalClaim.objects.create(event=self.other, claim_text='مقارنة تخص أُحد', status='APPROVED')
        Evidence.objects.create(claim=self.shared_claim, source=self.source, source_chunk=self.chunk, evidence_text=self.chunk.text)

    def add_evidence(self, event, ordinal, text):
        engine = HashEmbedding()
        chunk = SourceChunk.objects.create(source=self.source, ordinal=ordinal, text=text,
            embedding=engine.embed(text), embedding_reference=engine.reference)
        claim = HistoricalClaim.objects.create(event=event, claim_text=text, status='APPROVED')
        Evidence.objects.create(claim=claim, source=self.source, source_chunk=chunk, evidence_text=text)
        return chunk, claim

    def test_shared_source_does_not_expand_event_to_unrelated_chunks(self):
        chunks, _ = retrieve('ما مصدر هذه المعلومة؟', self.event)
        self.assertEqual([c.pk for c in chunks], [self.chunk.pk])
        self.claim.status = 'DRAFT'
        self.claim.save()
        self.assertEqual(retrieve('ما مصدر هذه المعلومة؟', self.event)[0], [])

    def test_reviewed_event_mention_can_supply_context_without_a_claim(self):
        self.claim.status = 'DRAFT'
        self.claim.save()
        mention = SourceMention.objects.create(source=self.source, chunk=self.chunk, entity=self.event,
            quote=self.chunk.text, status='PUBLISHED')
        self.assertEqual([c.pk for c in retrieve('ما مصدر هذه المعلومة؟', self.event)[0]], [self.chunk.pk])
        mention.status = 'DRAFT'
        mention.save()
        self.assertEqual(retrieve('ما مصدر هذه المعلومة؟', self.event)[0], [])

    def test_shared_chunk_evidence_and_provider_payload_remain_in_event(self):
        provider = Mock(name='provider')
        provider.name = 'test'
        provider.generate.return_value = json.dumps({'segments': [{'text': 'شرح مسند', 'chunk_ids': [self.chunk.pk]}]})
        with patch('apps.ai.services.get_provider', return_value=provider):
            result = ask('ما مصدر هذه المعلومة؟', event=self.event)
        self.assertEqual({e['claim_id'] for e in result['evidence']}, {self.claim.pk})
        self.assertEqual({e['event_id'] for e in result['evidence']}, {self.event.pk})
        payload = provider.generate.call_args.args[1]
        self.assertEqual({e['claim_id'] for e in payload['evidence']}, {self.claim.pk})
        self.assertEqual({c['id'] for c in payload['chunks']}, {self.chunk.pk})
        self.assertEqual(result['evidence'][0]['claim'], self.claim.claim_text)

    def test_only_chunks_actually_cited_supply_answer_links(self):
        second, second_claim = self.add_evidence(self.event, 2, 'خبر آخر من الخندق')
        provider = Mock()
        provider.name = 'test'
        provider.generate.return_value = json.dumps({'segments': [{'text': 'شرح مسند', 'chunk_ids': [second.pk]}]})
        with patch('apps.ai.services.get_provider', return_value=provider):
            result = ask('ما مصدر هذه المعلومة؟', event=self.event)
        self.assertEqual({e['claim_id'] for e in result['evidence']}, {second_claim.pk})
        self.assertEqual([s['chunk_id'] for s in result['sources']], [second.pk])

    def test_failure_and_refusal_have_no_spurious_evidence_links(self):
        for raw in [None, '{"segments":[]}']:
            provider = Mock()
            provider.name = 'test'
            if raw is None:
                provider.generate.side_effect = TimeoutError('private failure')
            else:
                provider.generate.return_value = raw
            with patch('apps.ai.services.get_provider', return_value=provider):
                result = ask('ما مصدر هذه المعلومة؟', event=self.event)
            self.assertEqual(result['sources'], [])
            self.assertEqual(result['evidence'], [])
            saved = AIQueryLog.objects.latest('pk')
            self.assertEqual(saved.structured_answer['evidence'], [])
            self.assertEqual(saved.retrieved_chunk_ids, [self.chunk.pk])
            if raw is None:
                self.assertEqual(result['related_entities'], [])

    def test_related_entity_search_is_scoped_but_global_search_remains_available(self):
        linked = HistoricalPerson.objects.create(title='شخصية الاختبار القريبة', slug='linked-person', status='PUBLISHED')
        distant = HistoricalPerson.objects.create(title='شخصية الاختبار البعيدة', slug='distant-person', status='PUBLISHED')
        self.event.persons.add(linked)
        _, entities = retrieve('شخصية الاختبار', self.event)
        self.assertEqual([e.pk for e in entities], [linked.pk])
        _, global_entities = retrieve('شخصية الاختبار')
        self.assertIn(distant.pk, [e.pk for e in global_entities])
