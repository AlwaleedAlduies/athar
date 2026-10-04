import json
import os
from unittest.mock import Mock, patch
from django.test import TestCase, SimpleTestCase, Client
from django.core.exceptions import ValidationError
from django.core import signing
from apps.accounts.models import User
from apps.history.models import HistoricalEra, HistoricalEvent
from apps.sources.models import HistoricalSource, SourceChunk, SourceMention
from apps.sources.services import process_source
from apps.sources.web_import import PageText
from apps.knowledge.models import HistoricalClaim, Evidence
from apps.dashboard.forms import editor_form
from apps.ai.models import AIQueryLog, AIConversation, AIMessage
from apps.ai.services import ask, retrieve


class ReadingBodyTests(SimpleTestCase):
    def read(self,markup,url='https://example.org/article'):
        parser=PageText(url);parser.feed(markup);return parser.text()

    def test_dorar_event_body_excludes_committees_and_furniture_but_keeps_dates(self):
        text=self.read('''<html><head><title>الموقع</title><script>secret</script></head><body>
        <div>لجنة الموقع وأسماء أعضاء المراجعة</div><div class="event-container"><h2>عنوان الحدث</h2>
        <div>العام الهجري: 5</div><p>وقائع تاريخية معروفة في سياقها.</p><div class="modal">مشاركة وحفظ</div>
        <ol class="footnotes"><li>مرجع الكتاب، صفحة 30.</li></ol></div><footer>روابط هامة</footer></body></html>''','https://dorar.net/history/event/84')
        for value in ['عنوان الحدث','العام الهجري: 5','وقائع تاريخية','مرجع الكتاب']:self.assertIn(value,text)
        for value in ['لجنة الموقع','مشاركة وحفظ','روابط هامة','secret']:self.assertNotIn(value,text)

    def test_changed_dorar_markup_fails_instead_of_importing_navigation(self):
        with self.assertRaises(ValidationError):self.read('<body><p>قائمة الموقع فقط</p></body>','https://dorar.net/history/event/84')

    def test_nested_articles_hidden_metadata_and_inline_text(self):
        text=self.read('''<head><title>Site metadata</title></head><main><article><header><h1>عنوان</h1></header>
        <p>قبل <strong>وسط</strong> بعد.</p><div class="post-meta">Author biography</div><aside>Recommended</aside>
        <div hidden>Hidden</div><div style="display: none">Hidden too</div><p>نهاية المتن.</p>
        <section class="footnotes">أصل الرواية ومرجعها.</section></article></main>''')
        self.assertIn('قبل وسط بعد.',text);self.assertEqual(text.count('عنوان'),1);self.assertIn('أصل الرواية',text)
        for value in ['Site metadata','Author biography','Recommended','Hidden']:self.assertNotIn(value,text)

    def test_unmarked_page_prefers_prose_container(self):
        text=self.read('<div><a>القائمة الأولى</a><a>القائمة الثانية</a></div><div><h2>المقال</h2><p>'+'المتن التاريخي المفصل. '*20+'</p></div>')
        self.assertIn('المتن التاريخي',text);self.assertNotIn('القائمة الأولى',text)


@patch.dict(os.environ,{'EMBEDDING_BACKEND':'hash','LLM_PROVIDER':'extractive'})
class SourceRepairTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user('repair-admin',role='ADMIN')
        self.client.force_login(self.admin)
        self.source=HistoricalSource.objects.create(title='مصدر رابط',slug='web-source',url='https://example.org/article')
        self.text='ورد خبر الحفر في المصدر مع أسماء الرواة ومواضع الرواية.'

    def test_url_only_processing_and_second_run_reuses_chunk_ids_without_fetch(self):
        page=self.client.get(f'/dashboard/sources/{self.source.pk}/')
        self.assertContains(page,f'action="/dashboard/sources/{self.source.pk}/process/"')
        self.assertNotContains(page,f'action="/api/v1/sources/{self.source.pk}/process/"')
        with patch('apps.sources.web_import.fetch_page',return_value=(self.source.url,self.text)) as fetch:
            self.assertEqual(process_source(self.source),1)
            chunk=self.source.chunks.get();self.assertEqual(process_source(self.source),1)
        fetch.assert_called_once();self.assertEqual(self.source.chunks.get().pk,chunk.pk)
        self.assertEqual(len(self.source.chunks.get().embedding),256)

    def test_reindex_keeps_citations_quotes_and_mentions(self):
        chunk=SourceChunk.objects.create(source=self.source,text=self.text,embedding_reference='old',embedding=[])
        era=HistoricalEra.objects.create(title='حقبة',slug='era');event=HistoricalEvent.objects.create(title='الحفر',slug='event',era=era)
        claim=HistoricalClaim.objects.create(event=event,claim_text=self.text)
        evidence=Evidence.objects.create(source=self.source,source_chunk=chunk,claim=claim,evidence_text=self.text)
        mention=SourceMention.objects.create(source=self.source,chunk=chunk,entity=event,quote=self.text)
        self.client.post(f'/dashboard/sources/{self.source.pk}/process/')
        chunk.refresh_from_db();evidence.refresh_from_db();mention.refresh_from_db()
        self.assertEqual(chunk.text,self.text);self.assertEqual(evidence.source_chunk_id,chunk.pk);self.assertEqual(mention.chunk_id,chunk.pk)
        self.assertEqual(chunk.embedding_reference,'hash-lexical-v1:256')

    def test_approval_button_indexes_then_approves_and_retrieval_finds_text(self):
        with patch('apps.sources.web_import.fetch_page',return_value=(self.source.url,self.text)):
            response=self.client.post(f'/dashboard/sources/{self.source.pk}/approve/',follow=True)
        self.assertContains(response,'اعتُمد المصدر');self.source.refresh_from_db()
        self.assertTrue(self.source.is_approved);self.assertEqual(self.source.status,'APPROVED')
        self.assertEqual(self.source.reviewed_by,self.admin);self.assertEqual(retrieve('الحفر')[0][0].source_id,self.source.pk)

    def test_approval_failure_keeps_draft_and_archive_is_not_approved(self):
        with patch('apps.sources.web_import.fetch_page',side_effect=ValidationError('لا يوجد متن')):
            self.client.post(f'/dashboard/sources/{self.source.pk}/approve/')
        self.source.refresh_from_db();self.assertFalse(self.source.is_approved);self.assertEqual(self.source.status,'DRAFT')
        self.source.status='ARCHIVED';self.source.save()
        with patch('apps.dashboard.views.process_source') as process:
            self.client.post(f'/dashboard/sources/{self.source.pk}/approve/')
        process.assert_not_called()

    def test_checkbox_approval_promotes_draft_in_editor(self):
        form=editor_form(HistoricalSource)({'title':self.source.title,'slug':self.source.slug,'url':self.source.url,
            'source_type':'digital','language':'العربية','status':'DRAFT','is_approved':'on'},instance=self.source)
        self.assertTrue(form.is_valid(),form.errors);self.assertEqual(form.save().status,'APPROVED')

    def test_revision_preview_and_save_preserve_old_chunks_and_are_idempotent(self):
        chunk=SourceChunk.objects.create(source=self.source,text='نص سابق مع قوائم الموقع',embedding_reference='test')
        with patch('apps.dashboard.source_refresh.fetch_page',return_value=(self.source.url,self.text)):
            preview=self.client.post(f'/dashboard/sources/{self.source.pk}/refresh/',{'action':'preview'})
        self.assertContains(preview,self.text);token=preview.context['preview']
        with patch('apps.dashboard.source_refresh.start_analysis') as start,self.captureOnCommitCallbacks(execute=True):
            first=self.client.post(f'/dashboard/sources/{self.source.pk}/refresh/',{'action':'apply','preview':token})
            second=self.client.post(f'/dashboard/sources/{self.source.pk}/refresh/',{'action':'apply','preview':token})
        self.assertEqual(first.url,second.url);start.assert_called_once()
        revision=self.source.revisions.get();self.assertFalse(revision.is_approved);self.assertEqual(revision.chunks.get().text,self.text)
        chunk.refresh_from_db();self.assertEqual(chunk.text,'نص سابق مع قوائم الموقع')

    def test_preview_token_tampering_other_admin_and_csrf_are_rejected(self):
        response=self.client.post(f'/dashboard/sources/{self.source.pk}/refresh/',{'action':'apply','preview':'tampered'})
        self.assertEqual(response.status_code,302);self.assertFalse(self.source.revisions.exists())
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin)
        self.assertEqual(secure.post(f'/dashboard/sources/{self.source.pk}/approve/').status_code,403)
        self.client.force_login(User.objects.create_user('ordinary'))
        self.assertEqual(self.client.post(f'/dashboard/sources/{self.source.pk}/refresh/').status_code,403)


@patch.dict(os.environ,{'EMBEDDING_BACKEND':'hash','LLM_PROVIDER':'extractive'})
class AnswerRetentionTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('history-reader')
        self.other=User.objects.create_user('other-reader')
        self.admin=User.objects.create_user('history-admin',role='ADMIN')

    def test_question_answer_and_sources_are_saved_for_signed_in_and_guest(self):
        for user in [self.user,None]:
            result=ask('سؤال لا توجد له أدلة',user)
            log=AIQueryLog.objects.latest('pk')
            self.assertEqual(log.answer,result['answer']);self.assertEqual(log.structured_answer['sources'],result['sources'])
        self.assertEqual(AIConversation.objects.count(),1);self.assertEqual(AIMessage.objects.count(),2)

    def test_provider_failure_is_retained_without_secret_and_history_access_is_private(self):
        with patch('apps.ai.services.retrieve',side_effect=RuntimeError('private-secret')):
            result=ask('سؤال محفوظ',self.user)
        log=AIQueryLog.objects.get();self.assertEqual(log.structured_answer['mode'],'unavailable')
        self.assertNotIn('private-secret',log.answer+json.dumps(log.structured_answer))
        self.client.force_login(self.user);self.assertContains(self.client.get(result['history_url']),result['answer'])
        self.client.force_login(self.other);self.assertEqual(self.client.get(result['history_url']).status_code,404)
        self.assertNotContains(self.client.get('/library/answers/'),'سؤال محفوظ')
        self.client.force_login(self.admin);self.assertContains(self.client.get(result['history_url']),'سؤال محفوظ')
        self.assertContains(self.client.get('/dashboard/logs/'),result['answer'])

    def test_valid_response_keeps_exact_citation_snapshot_and_escapes_html(self):
        source=HistoricalSource.objects.create(title='مرجع',slug='ref',is_approved=True,status='APPROVED')
        chunk=SourceChunk.objects.create(source=source,text='نص الدليل القديم',section='باب الخبر',embedding_reference='test')
        provider=Mock(name='provider');provider.name='local';provider.generate.return_value=json.dumps({'segments':[{'text':'<script>test</script> جواب','chunk_ids':[chunk.pk]}]})
        with patch('apps.ai.services.retrieve',return_value=([chunk],[])),patch('apps.ai.services.get_provider',return_value=provider):result=ask('ما الخبر؟',self.user)
        chunk.text='تغير النص';chunk.save()
        self.client.force_login(self.user);page=self.client.get(result['history_url'])
        self.assertContains(page,'نص الدليل القديم');self.assertNotContains(page,'<script>test</script>');self.assertContains(page,'&lt;script&gt;')
