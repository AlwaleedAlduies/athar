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
    def test_grouped_editors_preserve_every_field_once(self):
        from apps.dashboard.forms import editor_form
        from apps.dashboard.workflow import form_sections
        for section, (model, _) in REGISTRY.items():
            form = editor_form(model)()
            groups = form_sections(form, section)
            names = [field.name for group in groups for field in group['fields']]
            self.assertEqual(set(names), set(form.fields), section)
            self.assertEqual(len(names), len(set(names)), section)

    def test_prefilled_new_evidence_can_return_to_claim_after_first_save(self):
        url = reverse('dashboard-new', args=['evidence']) + f'?claim={self.claim.pk}'
        page = self.client.get(url)
        self.assertEqual(page.context['editor_parent']['url'], reverse('dashboard-edit', args=['claims', self.claim.pk]))
        response = self.client.post(url, {'claim':self.claim.pk, 'source':self.source.pk,
            'source_chunk':self.chunk.pk, 'evidence_text':self.chunk.text, 'section':self.chunk.section,
            'support_type':'SUPPORTS', '_intent':'save-return'})
        self.assertRedirects(response, reverse('dashboard-edit', args=['claims', self.claim.pk]))

    def test_source_to_studio_keeps_existing_source_and_event(self):
        page = self.client.get(reverse('extraction-studio'), {'source': self.source.pk, 'event': self.event.pk})
        self.assertEqual(page.context['form'].initial['source'], self.source.pk)
        self.assertEqual(page.context['form'].initial['input_kind'], 'existing')
        self.assertEqual(page.context['form'].initial['event'], str(self.event.pk))
        self.assertEqual(HistoricalSource.objects.count(), 1)
        invalid = self.client.get(reverse('extraction-studio'), {'source':'invalid'})
        self.assertEqual(invalid.context['form'].initial['input_kind'], 'url')

    def test_workflow_reports_real_readiness_without_mutating_records(self):
        from apps.dashboard.workflow import guidance
        ready = guidance('events', self.event)
        self.assertTrue(all(step['done'] for step in ready['steps']))
        self.assertEqual(ready['url'], self.event.get_absolute_url())
        self.source.is_approved = False
        self.source.save()
        blocked = guidance('events', self.event)
        self.assertFalse(blocked['steps'][0]['done'])
        self.assertFalse(blocked['steps'][1]['done'])
        self.assertFalse(blocked['steps'][4]['done'])
        self.assertEqual(blocked['url'], reverse('source-intake'))
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, 'PUBLISHED')

    def test_draft_event_guides_publication_before_publishing_its_story(self):
        from apps.dashboard.workflow import guidance
        self.event.status = 'DRAFT'
        self.event.save()
        guide = guidance('events', self.event)
        self.assertEqual(guide['url'], '#group-publication')
        self.assertIn('مسودات', guide['text'])
        page = self.client.get(reverse('dashboard-edit', args=['passages', self.passage.pk]))
        self.assertContains(page, 'الحدث ما زال غير متاح للزوار')
        self.assertEqual(page.context['editor_parent']['url'], reverse('dashboard-edit', args=['events', self.event.pk]))

    def test_save_return_uses_saved_parent_not_external_next_url(self):
        result = self.client.post(reverse('dashboard-edit', args=['passages', self.passage.pk]), {
            'event': self.event.pk, 'chapter': 'مراجعة', 'position': 2, 'text': 'نص محرر',
            'citations': [self.claim.pk], 'status': 'DRAFT', '_intent': 'save-return',
            'next': 'https://example.test/untrusted'})
        self.assertRedirects(result, reverse('dashboard-edit', args=['events', self.event.pk]))
        self.passage.refresh_from_db()
        self.assertEqual(self.passage.text, 'نص محرر')
        result = self.client.post(reverse('dashboard-edit', args=['evidence', self.proof.pk]), {
            'claim': self.claim.pk, 'source': self.source.pk, 'source_chunk': self.chunk.pk,
            'evidence_text': self.chunk.text, 'section': self.chunk.section,
            'support_type': 'SUPPORTS', '_intent': 'save-return'})
        self.assertRedirects(result, reverse('dashboard-edit', args=['claims', self.claim.pk]))

    def test_validation_summary_keeps_changes_and_opens_group_with_errors(self):
        result = self.client.post(reverse('dashboard-new', args=['persons']), {
            'title': 'عنوان احتفظ به', 'slug': self.event.slug, 'status': 'DRAFT', '_intent': 'save-return'})
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, 'لم يُحفظ المحتوى بعد')
        self.assertContains(result, 'عنوان احتفظ به')
        self.assertFalse(next(group for group in result.context['form_sections'] if group['key'] == 'advanced')['collapsed'])

    def test_review_queue_counts_match_pending_filter(self):
        HistoricalClaim.objects.create(event=self.event, claim_text='مسودة', status='DRAFT')
        HistoricalClaim.objects.create(event=self.event, claim_text='مراجعة', status='REVIEW')
        HistoricalClaim.objects.create(event=self.event, claim_text='أرشيف', status='ARCHIVED')
        home = self.client.get(reverse('dashboard'))
        listing = self.client.get(reverse('dashboard-list', args=['claims']), {'status': 'pending'})
        self.assertEqual(home.context['pending_claims'], 2)
        self.assertEqual(listing.context['page'].paginator.count, 2)
        self.assertContains(home, 'ترتيب المراجعة والنشر')

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
