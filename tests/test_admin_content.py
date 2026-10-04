from django.test import TestCase, Client, override_settings
from django.urls import reverse
from apps.accounts.models import User
from apps.history.models import HistoricalEra, HistoricalEvent, HistoricalPerson, HistoricalPlace, StoryPassage, Status
from apps.history.story import public_passages
from apps.sources.models import HistoricalSource, SourceChunk, SourceMention
from apps.knowledge.models import HistoricalClaim, Evidence, EntityRelationship
from apps.dashboard.forms import REGISTRY


@override_settings(DEMO_MODE=False)
class AdminContentTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('content-editor', password='test-only', role='ADMIN')
        self.client.force_login(self.admin)
        self.era = HistoricalEra.objects.create(title='حقبة اختبار', slug='test-era', status='PUBLISHED')
        self.event = HistoricalEvent.objects.create(title='حدث اختبار', slug='test-event', era=self.era, status='PUBLISHED')
        self.source = HistoricalSource.objects.create(title='مصدر اختبار', slug='test-source', status='APPROVED', is_approved=True)
        self.chunk = SourceChunk.objects.create(source=self.source, text='هذا نص موثق للاختبار.', section='القسم الأول', ordinal=0, embedding_reference='test')
        self.claim = HistoricalClaim.objects.create(event=self.event, claim_text='نص موثق', claim_type='FACT', status='APPROVED')
        self.proof = Evidence.objects.create(claim=self.claim, source=self.source, source_chunk=self.chunk, evidence_text=self.chunk.text, section=self.chunk.section)
        self.passage = StoryPassage.objects.create(event=self.event, chapter='بداية', position=1, text='سرد الاختبار', status='PUBLISHED')
        self.passage.citations.add(self.claim)

    def post_new(self, section, data):
        result = self.client.post(reverse('dashboard-new', args=[section]), data)
        self.assertEqual(result.status_code, 302, result.context['form'].errors if result.context and 'form' in result.context else result.content)
        return result

    def test_each_editor_and_collection_renders_and_event_has_linked_workspace(self):
        for section in REGISTRY:
            self.assertEqual(self.client.get(reverse('dashboard-list', args=[section])).status_code, 200, section)
            self.assertEqual(self.client.get(reverse('dashboard-new', args=[section]), {'manual': '1'}).status_code, 200, section)
        page = self.client.get(reverse('dashboard-edit', args=['events', self.event.pk]))
        self.assertContains(page, 'الفصول وفقرات السرد')
        self.assertContains(page, reverse('dashboard-edit', args=['passages', self.passage.pk]))
        self.assertContains(page, f'event={self.event.pk}')

    def test_create_and_edit_person_place_era_event_and_manual_source(self):
        for section in ['persons', 'places', 'eras']:
            response = self.post_new(section, {'title': 'سجل جديد ' + section, 'status': 'DRAFT'})
            instance = REGISTRY[section][0].objects.get(title='سجل جديد ' + section)
            self.assertTrue(instance.slug)
            response = self.client.post(response.url, {'title': 'تحرير ' + section, 'slug': instance.slug, 'status': 'PUBLISHED'})
            self.assertEqual(response.status_code, 302)
            instance.refresh_from_db(); self.assertEqual(instance.title, 'تحرير ' + section)
        self.post_new('events', {'title':'حدث جديد', 'status':'DRAFT', 'era':self.era.pk, 'date_precision':'year', 'event_type':'journey'})
        self.post_new('sources', {'title':'مرجع يدوي', 'status':'DRAFT', 'source_type':'book', 'language':'العربية'})

    def test_add_evidence_then_publish_claim_and_cited_story_via_forms(self):
        self.post_new('claims', {'event':self.event.pk, 'claim_text':'معلومة جديدة', 'claim_type':'FACT', 'status':'DRAFT'})
        claim = HistoricalClaim.objects.get(claim_text='معلومة جديدة')
        page = self.client.get(reverse('dashboard-new', args=['evidence']), {'claim':claim.pk,'source_chunk':self.chunk.pk})
        self.assertEqual(page.context['form'].initial['evidence_text'], self.chunk.text)
        self.post_new('evidence', {'claim':claim.pk,'source':self.source.pk,'source_chunk':self.chunk.pk,
            'evidence_text':self.chunk.text,'section':self.chunk.section,'support_type':'SUPPORTS'})
        result = self.client.post(reverse('dashboard-edit', args=['claims',claim.pk]),
            {'event':self.event.pk,'claim_text':claim.claim_text,'claim_type':'FACT','status':'APPROVED'})
        self.assertEqual(result.status_code, 302)
        self.post_new('passages', {'event':self.event.pk,'chapter':'فصل جديد','position':2,'text':'سرد جديد موثق','status':'PUBLISHED','citations':[claim.pk]})
        passage = StoryPassage.objects.get(text='سرد جديد موثق')
        self.assertTrue(public_passages().filter(pk=passage.pk).exists())
        result = self.client.post(reverse('dashboard-edit', args=['passages',passage.pk]),
            {'event':self.event.pk,'chapter':'عنوان معدل','position':3,'text':'سرد معدل','status':'PUBLISHED','citations':[claim.pk]})
        self.assertEqual(result.status_code,302)
        passage.refresh_from_db(); self.assertEqual((passage.position, passage.chapter),(3,'عنوان معدل'))
        self.assertContains(self.client.get(self.event.get_absolute_url()),'سرد معدل')

    def test_citation_choices_are_checkboxes_scoped_to_event_and_reject_wrong_event(self):
        another = HistoricalEvent.objects.create(title='آخر',slug='other',era=self.era)
        wrong = HistoricalClaim.objects.create(event=another,claim_text='دليل آخر')
        page = self.client.get(reverse('dashboard-new', args=['passages']),{'event':self.event.pk})
        self.assertContains(page, f'name="citations" value="{self.claim.pk}"')
        self.assertNotContains(page, f'name="citations" value="{wrong.pk}"')
        result = self.client.post(reverse('dashboard-new', args=['passages']),
            {'event':self.event.pk,'chapter':'خطأ','position':2,'text':'غير صحيح','status':'PUBLISHED','citations':[wrong.pk]})
        self.assertEqual(result.status_code,200)
        self.assertFalse(StoryPassage.objects.filter(text='غير صحيح').exists())

    def test_add_relationship_and_mention_with_matching_evidence(self):
        person = HistoricalPerson.objects.create(title='شخصية',slug='person',status='PUBLISHED')
        self.claim.person=person;self.claim.save()
        self.post_new('relationships', {'from_entity':person.pk,'to_entity':self.event.pk,'relation_type':'PARTICIPATED_IN','status':'PUBLISHED','supporting_claim':self.claim.pk,'notes':'دور موثق'})
        self.post_new('mentions', {'source':self.source.pk,'entity':person.pk,'chunk':self.chunk.pk,'quote':self.chunk.text,'context':'سياق','status':'PUBLISHED'})
        self.assertTrue(SourceMention.objects.filter(entity=person).exists())

    def test_edit_unused_chunk_refreshes_embedding_and_used_chunk_is_protected(self):
        self.post_new('chunks', {'source':self.source.pk,'ordinal':1,'section':'قسم جديد','text':'نص جديد'})
        chunk = SourceChunk.objects.get(source=self.source,ordinal=1)
        self.assertTrue(chunk.embedding)
        result = self.client.post(reverse('dashboard-edit',args=['chunks',chunk.pk]), {'source':self.source.pk,'ordinal':1,'section':'معدل','text':'نص معدل'})
        self.assertEqual(result.status_code,302)
        chunk.refresh_from_db();self.assertEqual(chunk.text,'نص معدل')
        result = self.client.post(reverse('dashboard-edit',args=['chunks',self.chunk.pk]), {'source':self.source.pk,'ordinal':0,'section':self.chunk.section,'text':'تغيير يكسر الدليل'})
        self.assertEqual(result.status_code,200)
        self.chunk.refresh_from_db();self.assertEqual(self.chunk.text,'هذا نص موثق للاختبار.')
        result = self.client.post(reverse('dashboard-remove',args=['chunks',self.chunk.pk]))
        self.assertEqual(result.status_code,302)
        self.assertTrue(SourceChunk.objects.filter(pk=self.chunk.pk).exists())
        self.client.post(reverse('dashboard-remove',args=['chunks',chunk.pk]))
        self.assertFalse(SourceChunk.objects.filter(pk=chunk.pk).exists())

    def test_archive_preview_is_read_only_and_restore_returns_draft(self):
        page = self.client.get(reverse('dashboard-removal-preview',args=['sources',self.source.pk]))
        self.assertEqual(page.context['impact']['passages'],1)
        self.source.refresh_from_db();self.assertTrue(self.source.is_approved)
        self.assertEqual(self.client.get(reverse('dashboard-remove',args=['sources',self.source.pk])).status_code,405)
        self.client.post(reverse('dashboard-remove',args=['sources',self.source.pk]))
        self.assertFalse(public_passages().filter(pk=self.passage.pk).exists())
        self.client.post(reverse('dashboard-restore',args=['sources',self.source.pk]))
        self.source.refresh_from_db()
        self.assertEqual(self.source.status,Status.DRAFT);self.assertFalse(self.source.is_approved)
        self.assertTrue(Evidence.objects.filter(pk=self.proof.pk).exists())

    def test_search_pagination_and_archive_filter_keep_context(self):
        for i in range(24): StoryPassage.objects.create(event=self.event,chapter='فصل',position=i+2,text='نص قابل للبحث')
        StoryPassage.objects.create(event=self.event,chapter='مؤرشف',text='قديم',status='ARCHIVED')
        response=self.client.get(reverse('dashboard-list',args=['passages']),{'q':'قابل','event':self.event.pk,'status':'DRAFT'})
        self.assertEqual(response.context['page'].paginator.count,24)
        self.assertContains(response,f'event={self.event.pk}&amp;status=DRAFT&amp;page=2')
        response=self.client.get(reverse('dashboard-list',args=['passages']),{'status':'ARCHIVED'})
        self.assertEqual(response.context['page'].paginator.count,1)

    def test_admin_options_and_mutations_require_admin_and_csrf(self):
        data=self.client.get(reverse('editor-options'),{'source':self.source.pk}).json()
        self.assertEqual(data['items'][0]['text'],self.chunk.text)
        guarded=Client(enforce_csrf_checks=True);guarded.force_login(self.admin)
        self.assertEqual(guarded.post(reverse('dashboard-remove',args=['passages',self.passage.pk])).status_code,403)
        ordinary=User.objects.create_user('reader',password='test-only')
        self.client.force_login(ordinary)
        self.assertEqual(self.client.get(reverse('editor-options'),{'source':self.source.pk}).status_code,403)
        self.assertEqual(self.client.post(reverse('dashboard-remove',args=['passages',self.passage.pk])).status_code,403)

    def test_simulation_and_public_settings_can_be_managed(self):
        response = self.post_new('simulations', {'title':'نشاط اختبار','event':self.event.pk,'decision_point':'موقف',
            'alternative':'افتراض','possible_consequences':'احتمال','influencing_factors':'عوامل','status':'DRAFT'})
        self.assertContains(self.client.get(response.url),'نشاط اختبار')
        response = self.post_new('settings', {'key':'library_notice','value':'إشعار تجريبي','description':'تنبيه المكتبة'})
        record=REGISTRY['settings'][0].objects.get(key='library_notice')
        self.client.post(reverse('dashboard-edit',args=['settings',record.pk]), {'key':'library_notice','value':'إشعار معدل','description':'تنبيه'})
        self.assertContains(self.client.get('/'),'إشعار معدل')
        self.client.post(reverse('dashboard-remove',args=['settings',record.pk]))
        self.assertNotContains(self.client.get('/'),'إشعار معدل')

    def test_removing_evidence_hides_unverifiable_story_without_destroying_it(self):
        self.client.post(reverse('dashboard-remove',args=['evidence',self.proof.pk]))
        self.assertFalse(public_passages().filter(pk=self.passage.pk).exists())
        self.assertTrue(StoryPassage.objects.filter(pk=self.passage.pk).exists())
