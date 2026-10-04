import io
import json
import os
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import Mock, patch
from django.test import TestCase, Client, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.accounts.models import User
from apps.ai.models import ProviderConfiguration
from apps.ai.providers import get_provider, LocalProvider, ProviderUnavailable
from apps.ai.configuration import validate_endpoint
from apps.dashboard.models import SourceAnalysis
from apps.dashboard.source_analysis import parse_discovery, matching_entities, run_analysis, save_discoveries
from apps.dashboard.source_analysis import anchor_quote
from apps.history.models import HistoricalEra, HistoricalEvent, HistoricalPerson, HistoricalPlace, Entity
from apps.sources.models import HistoricalSource, SourceChunk, SourceMention
from apps.sources.services import process_source
from apps.knowledge.models import EntityRelationship, HistoricalClaim
from apps.knowledge.selectors import graph_for, public_mentions


class ProviderConfigurationTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user('ai-admin',role='ADMIN')
        self.config=ProviderConfiguration.objects.create(name='Local',kind='local',base_url='http://127.0.0.1:11434',model='phi4:latest',timeout_seconds=600)
        self.client.force_login(self.admin)

    def test_encrypted_key_never_appears_in_editor(self):
        self.config.set_key('private-test-secret'); self.config.save()
        self.assertNotIn('private-test-secret',self.config.encrypted_key)
        self.assertEqual(self.config.get_key(),'private-test-secret')
        response=self.client.get(f'/dashboard/ai-providers/{self.config.pk}/')
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'private-test-secret'); self.assertNotContains(response,self.config.encrypted_key)

    def test_edit_form_preserves_saved_provider_and_model(self):
        self.config.kind='gemini';self.config.model='saved-model';self.config.base_url='https://generativelanguage.googleapis.com/v1beta';self.config.save()
        form=self.client.get(f'/dashboard/ai-providers/{self.config.pk}/').context['form']
        self.assertEqual(form['kind'].value(),'gemini');self.assertEqual(form['model'].value(),'saved-model')

    def test_activation_requires_success_and_has_one_active_provider(self):
        self.client.post(f'/dashboard/ai-providers/{self.config.pk}/activate/')
        self.config.refresh_from_db(); self.assertFalse(self.config.is_active)
        other=ProviderConfiguration.objects.create(name='Other',kind='local',base_url='http://localhost:11434',model='other',is_active=True,test_ok=True)
        self.config.test_ok=True; self.config.save()
        self.client.post(f'/dashboard/ai-providers/{self.config.pk}/activate/')
        self.assertEqual(ProviderConfiguration.objects.filter(is_active=True).get(),self.config)
        self.assertIsInstance(get_provider(),LocalProvider)
        self.assertEqual(get_provider().model,'phi4:latest')

    @patch('apps.dashboard.provider_views.validate_endpoint',side_effect=lambda url,kind:url)
    def test_save_test_and_active_edit_keeps_previous_connection_until_replacement_is_activated(self,_):
        self.config.is_active=True; self.config.test_ok=True; self.config.save()
        data={'name':'New endpoint','kind':'local','base_url':'http://localhost:11434','model':'phi4:latest','timeout_seconds':600,'analysis_chunk_limit':30,'action':'test'}
        provider=Mock(); provider.generate.return_value='{"ok":true}'
        with patch('apps.dashboard.provider_views.get_provider',return_value=provider):
            response=self.client.post(f'/dashboard/ai-providers/{self.config.pk}/',data)
        self.assertEqual(response.status_code,302)
        self.config.refresh_from_db(); self.assertTrue(self.config.is_active)
        self.assertEqual(self.config.base_url,'http://127.0.0.1:11434')
        new=ProviderConfiguration.objects.exclude(pk=self.config.pk).get()
        self.assertTrue(new.test_ok); self.assertFalse(new.is_active)

    def test_provider_uses_selected_endpoint_timeout_schema_and_key(self):
        self.config.set_key('private-test-secret')
        with patch('apps.ai.providers.post_json',return_value={'message':{'content':'{"ok":true}'},'done_reason':'stop'}) as post:
            result=get_provider(self.config).generate('system',{},schema={'type':'object'})
        self.assertEqual(result,'{"ok":true}')
        self.assertEqual(post.call_args.args[0],'http://127.0.0.1:11434/api/chat')
        self.assertEqual(post.call_args.args[1]['format'],{'type':'object'})
        self.assertEqual(post.call_args.kwargs['timeout'],600)
        self.assertEqual(post.call_args.args[2]['Authorization'],'Bearer private-test-secret')

    @patch('apps.dashboard.provider_views.validate_endpoint',side_effect=lambda url,kind:url)
    def test_endpoint_change_does_not_reuse_the_previous_key(self,_):
        self.config.set_key('old-endpoint-secret'); self.config.save()
        data={'name':'Local','kind':'local','base_url':'http://localhost:11434','model':'phi4:latest','timeout_seconds':600,'analysis_chunk_limit':30,'action':'save'}
        self.assertEqual(self.client.post(f'/dashboard/ai-providers/{self.config.pk}/',data).status_code,302)
        self.config.refresh_from_db(); self.assertEqual(self.config.get_key(),'')
        data.update(base_url='http://127.0.0.1:11434',api_key='replacement-secret')
        self.client.post(f'/dashboard/ai-providers/{self.config.pk}/',data)
        self.config.refresh_from_db(); self.assertEqual(self.config.get_key(),'replacement-secret')

    @patch.dict(os.environ,{'GEMINI_API_KEY':'env-secret'})
    def test_environment_key_is_not_forwarded_to_custom_gemini_host(self):
        self.config.kind='gemini'; self.config.base_url='https://other.example/v1beta'
        with self.assertRaisesMessage(ProviderUnavailable,'credentials_missing'):
            get_provider(self.config).generate('system',{})

    def test_provider_settings_permissions_csrf_and_endpoint_validation(self):
        client=Client(enforce_csrf_checks=True); client.force_login(self.admin)
        self.assertEqual(client.post(f'/dashboard/ai-providers/{self.config.pk}/activate/').status_code,403)
        self.client.force_login(User.objects.create_user('reader'))
        self.assertEqual(self.client.get('/dashboard/ai-providers/').status_code,403)
        for url in ['file:///etc/passwd','http://169.254.169.254/','https://user:secret@example.com/','https://example.com/?key=secret']:
            with self.subTest(url=url),self.assertRaises(ValidationError):validate_endpoint(url,'local')


class SourceDiscoveryTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('discovery-admin',role='ADMIN')
        self.era=HistoricalEra.objects.create(title='عصر النبوة',slug='era',status='PUBLISHED')
        self.event=HistoricalEvent.objects.create(title='غزوة أُحد',slug='uhud',era=self.era,status='PUBLISHED')
        self.person=HistoricalPerson.objects.create(title='عبد الله بن جبير',slug='jubayr',alternative_names='ابن جبير',status='PUBLISHED')
        self.source=HistoricalSource.objects.create(title='مصدر جديد',slug='source',status='DRAFT',created_by=self.user)
        self.chunk=SourceChunk.objects.create(source=self.source,text='تذكر غزوة أُحد وعبد الله بن جبير. وروى البراء بن عازب الخبر.',section='الفصل الأول',page_number=2,embedding_reference='test')
        self.config=ProviderConfiguration.objects.create(name='Local',kind='local',base_url='http://localhost:11434',model='phi4',analysis_chunk_limit=30)
        self.run=SourceAnalysis.objects.create(source=self.source,created_by=self.user,configuration=self.config)
        self.rows=[{'kind':'event','name':'غزوة أُحد','summary':'تذكر المادة غزوة أُحد.','evidence':[{'chunk_id':self.chunk.pk,'quote':'تذكر غزوة أُحد'}]},
            {'kind':'person','name':'البراء بن عازب','summary':'روى البراء الخبر.','evidence':[{'chunk_id':self.chunk.pk,'quote':'وروى البراء بن عازب الخبر.'}]}]

    def complete(self):
        provider=Mock(); provider.name='local'; provider.model='phi4'; provider.generate.return_value=json.dumps({'entities':self.rows})
        with patch('apps.dashboard.source_analysis.get_provider',return_value=provider),patch('apps.dashboard.source_analysis.close_old_connections'):
            run_analysis(self.run.pk)
        self.run.refresh_from_db()
        return provider

    def test_analysis_only_proposes_and_does_not_create_public_data(self):
        before=(Entity.objects.count(),EntityRelationship.objects.count())
        self.complete()
        self.assertEqual(self.run.status,'REVIEW'); self.assertEqual(len(self.run.entities),2)
        self.assertEqual(self.run.processed_chunk_ids,[self.chunk.pk])
        self.assertEqual(before,(Entity.objects.count(),EntityRelationship.objects.count()))
        self.assertFalse(SourceMention.objects.exists())

    def test_exact_and_alias_matches_are_suggestions_with_type_boundaries(self):
        exact=matching_entities(self.rows[0]); self.assertEqual(exact[0]['entity'],self.event.entity_ptr); self.assertTrue(exact[0]['exact'])
        alias=matching_entities({'kind':'person','name':'ابن جبير'}); self.assertEqual(alias[0]['entity'].pk,self.person.pk); self.assertTrue(alias[0]['exact'])
        self.assertEqual(matching_entities({'kind':'place','name':'غزوة أُحد'}),[])

    def test_link_existing_and_create_new_preserve_quotes_without_inventing_roles(self):
        self.complete()
        saved=save_discoveries(self.run,{0:{'action':'link','entity_id':self.event.pk},1:{'action':'create','title':'البراء بن عازب','description':'روى الخبر.'}},self.user)
        person=HistoricalPerson.objects.get(title='البراء بن عازب')
        self.assertEqual(person.status,'DRAFT'); self.assertTrue(person.ai_suggested)
        self.assertEqual(SourceMention.objects.count(),2)
        self.assertEqual(SourceMention.objects.get(entity=person).chunk.page_number,2)
        self.assertEqual(SourceMention.objects.get(entity=self.event).quote,'تذكر غزوة أُحد')
        self.assertTrue(self.event.sources.filter(pk=self.source.pk).exists())
        self.assertFalse(EntityRelationship.objects.exists()); self.assertFalse(self.event.persons.filter(pk=person.pk).exists())
        self.assertEqual(HistoricalClaim.objects.get().status,'DRAFT')
        with self.assertRaises(ValidationError):save_discoveries(saved,{0:{'action':'link','entity_id':self.event.pk}},self.user)

    def test_new_event_requires_era_and_stays_draft(self):
        self.complete()
        with self.assertRaises(ValidationError):save_discoveries(self.run,{0:{'action':'create','title':'حدث جديد'}},self.user)
        self.assertFalse(HistoricalEvent.objects.filter(title='حدث جديد').exists())
        save_discoveries(self.run,{0:{'action':'create','title':'حدث جديد','era_id':self.era.pk}},self.user)
        self.assertEqual(HistoricalEvent.objects.get(title='حدث جديد').status,'DRAFT')

    def test_duplicate_name_wrong_type_and_changed_quotes_roll_back(self):
        self.complete()
        for choice in [{'action':'create','title':'غزوة أحد','era_id':self.era.pk},{'action':'link','entity_id':self.person.pk}]:
            with self.subTest(choice=choice),self.assertRaises(ValidationError): save_discoveries(self.run,{0:choice},self.user)
        self.chunk.text='نص مختلف';self.chunk.save()
        with self.assertRaises(ValidationError):save_discoveries(self.run,{0:{'action':'link','entity_id':self.event.pk}},self.user)
        self.assertFalse(SourceMention.objects.exists())

    def test_invalid_evidence_ids_quotes_and_invented_names_are_rejected(self):
        for row in [{**self.rows[0],'name':'اسم مخترع'}, {**self.rows[0],'evidence':[{'chunk_id':999,'quote':'غير موجود'}]}]:
            with self.subTest(row=row),self.assertRaises(ValidationError): parse_discovery(json.dumps({'entities':[row]}),{self.chunk.pk:self.chunk})
        valid,rejected=parse_discovery(json.dumps({'entities':[self.rows[0],{**self.rows[1],'name':'اختراع'}]}),{self.chunk.pk:self.chunk})
        self.assertEqual(len(valid),1);self.assertEqual(rejected,1)

    def test_existing_person_alias_cannot_create_duplicate_record(self):
        self.complete()
        with self.assertRaises(ValidationError):
            save_discoveries(self.run,{1:{'action':'create','title':'ابن جبير'}},self.user)
        self.assertFalse(HistoricalPerson.objects.filter(title='ابن جبير').exists())

    def test_vocalization_is_restored_from_one_exact_source_span_only(self):
        self.assertEqual(anchor_quote('غزوة أحد','خبر غزوة أُحد.'),'غزوة أُحد')
        self.assertIsNone(anchor_quote('غزوة أحد','غزوة أُحد ثم غزوة أُحد'))
        self.assertIsNone(anchor_quote('شارك خالد','لم يشارك خَالِد'))

    def test_partial_coverage_and_retry_do_not_repeat_completed_chunks(self):
        second=SourceChunk.objects.create(source=self.source,ordinal=1,text='نص بلا أسماء.',embedding_reference='test')
        self.config.analysis_chunk_limit=1;self.config.save()
        self.complete();self.assertEqual(self.run.status,'PARTIAL')
        self.run.status='QUEUED';self.run.save()
        provider=Mock();provider.name='local';provider.model='phi4';provider.generate.return_value='{"entities":[]}'
        with patch('apps.dashboard.source_analysis.get_provider',return_value=provider),patch('apps.dashboard.source_analysis.close_old_connections'):
            run_analysis(self.run.pk)
        sent=provider.generate.call_args.args[1]['chunks']
        self.assertEqual([r['id'] for r in sent],[second.pk])
        self.run.refresh_from_db();self.assertEqual(self.run.status,'REVIEW');self.assertEqual(len(self.run.entities),2)

    def test_provider_failure_retains_source_and_can_retry(self):
        with patch('apps.dashboard.source_analysis.get_provider',side_effect=ProviderUnavailable('connection_failed')),patch('apps.dashboard.source_analysis.close_old_connections'):
            run_analysis(self.run.pk)
        self.run.refresh_from_db();self.assertEqual(self.run.status,'FAILED');self.assertTrue(self.source.chunks.exists())
        self.client.force_login(self.user)
        with patch('apps.dashboard.intake_views.start_analysis') as start,self.captureOnCommitCallbacks(execute=True):
            self.client.post(f'/dashboard/intake/{self.run.pk}/retry/')
        start.assert_called_once_with(self.run.pk)

    def test_public_mentions_require_review_and_approved_visible_source(self):
        self.complete();save_discoveries(self.run,{0:{'action':'link','entity_id':self.event.pk}},self.user)
        mention=SourceMention.objects.get();self.assertFalse(public_mentions().exists())
        mention.status='APPROVED';mention.save();self.assertFalse(public_mentions().exists())
        self.source.status='PUBLISHED';self.source.is_approved=True;self.source.save()
        self.assertEqual(public_mentions().get(),mention)
        graph=graph_for(self.event);self.assertTrue(any(e.get('mention_id')==mention.pk for e in graph['edges']))
        self.assertContains(self.client.get(self.person.get_absolute_url()),self.person.title)
        self.assertContains(self.client.get(self.event.get_absolute_url()),mention.quote)
        self.source.is_approved=False;self.source.save();self.assertFalse(public_mentions().exists())

    def test_upload_automatically_queues_once_and_private_source_has_no_event_requirement(self):
        self.client.force_login(self.user)
        with tempfile.TemporaryDirectory() as folder,override_settings(MEDIA_ROOT=folder),patch('apps.dashboard.intake_views.start_analysis') as start,self.captureOnCommitCallbacks(execute=True):
            token=uuid.uuid4()
            def upload():return self.client.post('/dashboard/intake/',{'token':str(token),'title':'مستند','input_kind':'file','document':SimpleUploadedFile('history.txt','مصدر جديد يحوي أسماء.'.encode())})
            first=upload();self.assertEqual(first.status_code,302)
            run=SourceAnalysis.objects.get(source__slug=f'intake-{token.hex}')
            self.assertEqual(run.status,'QUEUED');self.assertFalse(run.source.is_approved)
            self.assertEqual(upload().url,first.url)
        start.assert_called_once_with(run.pk)

    def test_admin_review_form_creates_selected_records_and_other_users_cannot_poll(self):
        self.complete();self.client.force_login(self.user)
        page=self.client.get(f'/dashboard/intake/{self.run.pk}/');self.assertEqual(page.status_code,200)
        self.assertContains(page,'سجلات قد تطابق هذا الاسم')
        result=self.client.post(f'/dashboard/intake/{self.run.pk}/',{'0-action':'link','0-entity':self.event.pk,'1-action':'create','1-title':'البراء بن عازب','1-description':'راوي الخبر'})
        self.assertEqual(result.status_code,302)
        self.assertTrue(HistoricalPerson.objects.filter(title='البراء بن عازب').exists())
        self.client.force_login(User.objects.create_user('normal'))
        self.assertEqual(self.client.get(f'/dashboard/intake/{self.run.pk}/status/').status_code,403)

    def test_running_job_only_becomes_retryable_when_stale(self):
        self.client.force_login(self.user);self.run.status='RUNNING';self.run.save()
        self.assertFalse(self.client.get(f'/dashboard/intake/{self.run.pk}/status/').json()['can_retry'])
        SourceAnalysis.objects.filter(pk=self.run.pk).update(updated_at=timezone.now()-timedelta(hours=1))
        self.assertTrue(self.client.get(f'/dashboard/intake/{self.run.pk}/status/').json()['can_retry'])
