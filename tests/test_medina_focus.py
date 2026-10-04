import io
import json
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from apps.history.models import HistoricalEvent, HistoricalPerson, Status
from apps.sources.models import HistoricalSource, SourceChunk
from apps.knowledge.models import HistoricalClaim, Evidence, EntityRelationship
from apps.knowledge.selectors import graph_for, public_relationships, trace_claim


@override_settings(DEMO_MODE=False)
class MedinaFocusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo', stdout=io.StringIO())
        call_command('import_dorar_pilot', apply=True, stdout=io.StringIO())

    def apply(self):
        call_command('enrich_medina', apply=True, stdout=io.StringIO())

    def counts(self):
        return [m.objects.count() for m in [HistoricalEvent, HistoricalPerson, HistoricalSource, SourceChunk, HistoricalClaim, Evidence, EntityRelationship]]

    def test_preview_rolls_back_and_import_does_not_expand_topics(self):
        before = self.counts()
        call_command('enrich_medina', stdout=io.StringIO())
        self.assertEqual(before, self.counts())
        self.apply()
        self.assertEqual(HistoricalEvent.objects.visible().count(), 6)
        self.assertEqual(HistoricalSource.objects.filter(is_approved=True).count(), 12)
        self.assertEqual(HistoricalClaim.objects.filter(review_notes__startswith='medina-focus-v1:').count(), 17)

    def test_idempotence_preserves_editorial_work(self):
        self.apply()
        before = self.counts()
        HistoricalEvent.objects.filter(slug='badr').update(narrative='تحرير لاحق محفوظ')
        self.apply()
        self.assertEqual(before, self.counts())
        self.assertEqual(HistoricalEvent.objects.get(slug='badr').narrative, 'تحرير لاحق محفوظ')

    def test_preexisting_edits_abort_before_writing(self):
        before = self.counts()
        HistoricalEvent.objects.filter(slug='uhud').update(narrative='تحرير المستخدم')
        with self.assertRaises(CommandError):
            self.apply()
        self.assertEqual(before, self.counts())

    def test_each_role_has_same_person_event_and_public_evidence(self):
        self.apply()
        roles = public_relationships().filter(from_entity__kind='person', supporting_claim__isnull=False)
        self.assertEqual(roles.count(), 16)
        for edge in roles:
            edge.full_clean()
            self.assertEqual(edge.from_entity_id, edge.supporting_claim.person_id)
            self.assertEqual(edge.to_entity_id, edge.supporting_claim.event_id)
            self.assertEqual(trace_claim(edge.supporting_claim)['confidence'], 'موثق')
        narrator = roles.get(from_entity__slug='anas-ibn-malik')
        self.assertEqual(narrator.relation_type, 'NARRATED')
        caravan = roles.get(from_entity__slug='abu-sufyan', to_entity__slug='badr')
        self.assertEqual(caravan.relation_type, 'RELATED_TO')
        self.assertFalse(roles.filter(relation_type='CAUSED_BY').exists())

    def test_wrong_person_or_event_evidence_is_rejected(self):
        self.apply()
        edge = public_relationships().get(from_entity__slug='hudhayfah', to_entity__slug='khandaq')
        edge.from_entity = HistoricalPerson.objects.get(slug='aisha')
        with self.assertRaises(ValidationError):
            edge.full_clean()
        edge.from_entity = HistoricalPerson.objects.get(slug='hudhayfah')
        edge.to_entity = HistoricalEvent.objects.get(slug='uhud')
        with self.assertRaises(ValidationError):
            edge.full_clean()

    def test_private_proof_disappears_from_graph_api_and_page(self):
        self.apply()
        edge = public_relationships().get(from_entity__slug='hudhayfah', to_entity__slug='khandaq')
        event = HistoricalEvent.objects.get(slug='khandaq')
        edge.supporting_claim.status = Status.DRAFT
        edge.supporting_claim.save()
        self.assertNotIn(edge.pk, [e['id'] for e in graph_for(event)['edges']])
        self.assertEqual(self.client.get(f'/api/v1/relationships/{edge.pk}/').status_code, 404)
        response = self.client.get(event.get_absolute_url())
        self.assertNotContains(response, f'data-trace="{edge.supporting_claim_id}"')

    def test_unapproved_source_hides_proof_and_source_claims(self):
        self.apply()
        source = HistoricalSource.objects.get(slug='dorar-khandaq-hudhayfah-7125')
        source.is_approved = False; source.save()
        self.assertFalse(public_relationships().filter(from_entity__slug='hudhayfah', to_entity__slug='khandaq').exists())
        self.assertNotContains(self.client.get(source.get_absolute_url()), 'تتبّع الاستشهاد')

    def test_later_claim_edits_cannot_leave_a_mismatched_public_role(self):
        self.apply()
        edge = public_relationships().get(from_entity__slug='hudhayfah', to_entity__slug='khandaq')
        claim = edge.supporting_claim
        claim.person = HistoricalPerson.objects.get(slug='aisha'); claim.save()
        self.assertFalse(public_relationships().filter(pk=edge.pk).exists())
        claim.person = HistoricalPerson.objects.get(slug='hudhayfah')
        claim.event = HistoricalEvent.objects.get(slug='badr'); claim.save()
        self.assertFalse(public_relationships().filter(pk=edge.pk).exists())

    def test_quotes_belong_to_sources_and_web_numbers_are_not_pages(self):
        self.apply()
        for evidence in Evidence.objects.filter(claim__review_notes__startswith='medina-focus-v1:'):
            evidence.full_clean()
            self.assertIsNone(evidence.page_number)
            self.assertEqual(evidence.source_id, evidence.source_chunk.source_id)
        for source in HistoricalSource.objects.filter(is_approved=True):
            self.assertLessEqual(sum(len(c.text.split()) for c in source.chunks.all()), 25)

    def test_focused_journey_and_bidirectional_role_and_source_navigation(self):
        self.apply()
        response = self.client.get('/journey/?path=medina')
        self.assertEqual([s['title'] for s in response.context['stations']], ['غزوة بدر الكبرى', 'غزوة أُحد', 'غزوة الخندق — الأحزاب'])
        uhud = HistoricalEvent.objects.get(slug='uhud')
        response = self.client.get(uhud.get_absolute_url())
        self.assertContains(response, 'دليل الدور')
        self.assertContains(response, 'لماذا هذه الرابطة؟')
        person = HistoricalPerson.objects.get(slug='aisha')
        self.assertContains(self.client.get(person.get_absolute_url()), uhud.get_absolute_url())
        source = HistoricalSource.objects.get(slug='hadeethenc-uhud-service-66336')
        self.assertContains(self.client.get(source.get_absolute_url()), 'ما الذي يدعمه هذا المصدر؟')
        HistoricalEvent.objects.filter(slug='uhud').update(status=Status.DRAFT)
        self.assertEqual(len(self.client.get('/journey/?path=medina').context['stations']), 2)
