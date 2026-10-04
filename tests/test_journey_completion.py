import io
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from apps.history.audit import audit_content
from apps.history.models import HistoricalEvent, HistoricalPerson, StoryPassage, Status
from apps.knowledge.models import EntityRelationship, Evidence
from apps.knowledge.selectors import public_relationships
from apps.sources.models import HistoricalSource


@override_settings(DEMO_MODE=False)
class JourneyCompletionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for command in ['seed_demo', 'import_dorar_pilot', 'enrich_medina', 'enrich_stories']:
            call_command(command, **({} if command == 'seed_demo' else {'apply': True}), stdout=io.StringIO())

    def apply(self):
        call_command('complete_journey', apply=True, stdout=io.StringIO())

    def test_preview_is_read_only_and_repeated_apply_preserves_edits(self):
        before = [HistoricalSource.objects.count(), StoryPassage.objects.count(), EntityRelationship.objects.count()]
        call_command('complete_journey', stdout=io.StringIO())
        self.assertEqual(before, [HistoricalSource.objects.count(), StoryPassage.objects.count(), EntityRelationship.objects.count()])
        self.apply()
        count = StoryPassage.objects.count()
        passage = StoryPassage.objects.filter(event__slug='hijrah').first()
        passage.text = 'تحرير لاحق'; passage.save()
        self.apply()
        passage.refresh_from_db()
        self.assertEqual(passage.text, 'تحرير لاحق')
        self.assertEqual(StoryPassage.objects.count(), count)

    def test_edited_topic_is_preserved_and_partial_import_rolls_back(self):
        HistoricalEvent.objects.filter(slug='hijrah').update(description='نص محرر')
        with self.assertRaises(CommandError): self.apply()
        self.assertFalse(HistoricalSource.objects.filter(slug='bukhari-hijrah-3905').exists())

    def test_all_six_topics_have_readable_cited_stories_and_supported_roles(self):
        self.apply()
        report = audit_content()
        self.assertEqual(report['totals']['events'], 6)
        self.assertEqual(report['totals']['passages'], 46)
        self.assertEqual(report['issues'], [])
        for event in HistoricalEvent.objects.visible():
            self.assertContains(self.client.get(event.get_absolute_url()), 'كل فقرة باب إلى دليلها')
        for proof in Evidence.objects.filter(claim__review_notes__startswith='journey-completion-v1:'):
            proof.full_clean()

    def test_person_and_place_pages_show_reviewed_context_and_proofs(self):
        self.apply()
        person = HistoricalPerson.objects.get(slug='abu-bakr')
        response = self.client.get(person.get_absolute_url())
        self.assertContains(response, 'في قلب الأحداث')
        roles = list(response.context['role_history'])
        self.assertEqual([r.to_entity.slug for r in roles], ['hijrah', 'badr', 'hudaybiyyah'])
        self.assertContains(response, 'دليل الدور')
        event = HistoricalEvent.objects.get(slug='hijrah')
        self.assertContains(self.client.get(event.location.get_absolute_url()), 'الأحداث في هذا المكان')

    def test_withdrawn_reference_hides_person_role_and_event_paragraphs(self):
        self.apply()
        source = HistoricalSource.objects.get(slug='bukhari-hijrah-3905')
        source.is_approved = False; source.save()
        person = HistoricalPerson.objects.get(slug='asma-bint-abi-bakr')
        self.assertNotContains(self.client.get(person.get_absolute_url()), 'دليل الدور')
        self.assertFalse(public_relationships().filter(from_entity=person).exists())
        self.assertTrue(any(r['hidden_published_passages'] for r in audit_content()['events']))

    def test_narration_is_distinct_from_participation_and_sequence_skips_private_topics(self):
        self.apply()
        role = public_relationships().get(from_entity__slug='aisha', to_entity__slug='hijrah')
        self.assertEqual(role.relation_type, 'NARRATED')
        self.assertEqual(role.supporting_claim.person_id, role.from_entity_id)
        HistoricalEvent.objects.filter(slug='badr').update(status=Status.DRAFT)
        response = self.client.get(HistoricalEvent.objects.get(slug='hijrah').get_absolute_url())
        self.assertEqual(response.context['next_event'].slug, 'uhud')
        self.assertContains(response, 'قد تقع بينهما أحداث أخرى')
