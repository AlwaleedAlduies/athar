import io
import json
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from apps.history.management.commands.import_dorar_pilot import DATA, validate_dataset
from apps.history.models import HistoricalEvent, HistoricalPerson, Status
from apps.sources.models import HistoricalSource, SourceChunk
from apps.knowledge.models import HistoricalClaim, Evidence, EntityRelationship
from apps.knowledge.selectors import trace_claim, graph_for
from apps.accounts.models import Bookmark, User
from apps.ai.services import retrieve


class DorarImportTests(TestCase):
    def setUp(self):
        call_command('seed_demo', stdout=io.StringIO())

    def apply(self):
        call_command('import_dorar_pilot', apply=True, stdout=io.StringIO())

    def test_preview_rolls_back_every_write(self):
        old_ids = list(HistoricalEvent.objects.values_list('pk', flat=True))
        call_command('import_dorar_pilot', stdout=io.StringIO())
        self.assertEqual(list(HistoricalEvent.objects.values_list('pk', flat=True)), old_ids)
        self.assertEqual(HistoricalSource.objects.filter(is_approved=True).count(), 0)
        self.assertEqual(HistoricalEvent.objects.filter(is_demo=True).count(), 3)
        self.assertEqual(Evidence.objects.count(), 0)

    def test_import_preserves_event_identity_bookmarks_and_real_user_links(self):
        event = HistoricalEvent.objects.get(slug='hijrah')
        user = User.objects.create_user(username='import-reader')
        Bookmark.objects.create(user=user, entity=event)
        person = HistoricalPerson.objects.create(title='رابط تحريري إضافي', slug='custom-person', status='PUBLISHED')
        event.persons.add(person)
        self.apply(); event.refresh_from_db()
        self.assertFalse(event.is_demo)
        self.assertTrue(event.persons.filter(pk=person.pk).exists())
        self.assertTrue(Bookmark.objects.filter(user=user, entity_id=event.pk).exists())
        self.assertEqual(HistoricalEvent.objects.visible().count(), 6)
        self.assertEqual(HistoricalSource.objects.filter(is_approved=True).count(), 6)
        self.assertEqual(event.claims.filter(is_demo=True, status=Status.ARCHIVED).count(), 1)
        self.assertTrue(all(not n['is_demo'] for n in graph_for(event)['nodes']))

    def test_all_published_claims_have_matching_short_evidence(self):
        self.apply()
        for claim in HistoricalClaim.objects.filter(is_demo=False):
            evidence = claim.evidence.get()
            evidence.full_clean()
            self.assertLessEqual(len(evidence.evidence_text.split()), 25)
            self.assertIsNone(evidence.page_number)
            self.assertEqual(trace_claim(claim)['evidence'][0]['text'], evidence.evidence_text)
        khandaq = HistoricalEvent.objects.get(slug='khandaq')
        self.assertEqual(khandaq.date_precision, 'approximate')
        self.assertEqual(trace_claim(khandaq.claims.get())['classification'], 'اختلاف روايات')

    def test_second_run_is_idempotent_and_preserves_editorial_edits(self):
        self.apply()
        counts = [m.objects.count() for m in [HistoricalEvent, HistoricalSource, SourceChunk, HistoricalClaim, Evidence, EntityRelationship]]
        event = HistoricalEvent.objects.get(slug='badr'); event.narrative = 'تعديل تحريري محفوظ'; event.save()
        self.apply(); event.refresh_from_db()
        self.assertEqual(event.narrative, 'تعديل تحريري محفوظ')
        self.assertEqual(counts, [m.objects.count() for m in [HistoricalEvent, HistoricalSource, SourceChunk, HistoricalClaim, Evidence, EntityRelationship]])

    def test_conflicting_non_demo_content_is_not_overwritten(self):
        event = HistoricalEvent.objects.get(slug='badr'); event.is_demo = False; event.save()
        with self.assertRaises(CommandError): self.apply()
        self.assertFalse(HistoricalSource.objects.filter(is_approved=True).exists())

    @override_settings(DEMO_MODE=False)
    def test_real_import_is_visible_and_retrievable_without_demo_content(self):
        from unittest.mock import patch
        import os
        self.apply()
        self.assertEqual(len(self.client.get('/journey/').context['stations']), 6)
        self.assertNotContains(self.client.get('/timeline/'), 'تجارب العرض موسومة')
        with patch.dict(os.environ, {'EMBEDDING_BACKEND': 'hash'}):
            chunks, _ = retrieve('ما شروط صلح الحديبية؟', HistoricalEvent.objects.get(slug='hudaybiyyah'))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].source.url, 'https://dorar.net/history/event/101')

    def test_dataset_requires_exact_dorar_urls(self):
        data = json.loads(DATA.read_text(encoding='utf-8'))
        data['events'][0]['url'] = 'https://other.test/'
        with self.assertRaises(CommandError): validate_dataset(data)

    def test_demo_startup_cannot_reintroduce_placeholder_relationships(self):
        self.apply()
        before = list(EntityRelationship.objects.order_by('pk').values_list('pk', 'status'))
        call_command('seed_demo', stdout=io.StringIO())
        self.assertEqual(before, list(EntityRelationship.objects.order_by('pk').values_list('pk', 'status')))
