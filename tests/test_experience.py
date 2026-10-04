import io
import json
import os
from unittest.mock import patch, Mock
from urllib.error import HTTPError
from django.test import TestCase, override_settings
from django.core.management import call_command
from apps.history.models import HistoricalEra, HistoricalEvent, HistoricalPerson, HistoricalPlace
from apps.sources.models import HistoricalSource
from apps.ai.providers import GeminiProvider, ProviderUnavailable, post_json
from apps.ai.services import parse_answer, ask, NO_EVIDENCE


class JourneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.era = HistoricalEra.objects.create(title='حقبة منشورة', slug='journey-era', status='PUBLISHED')
        cls.private_era = HistoricalEra.objects.create(title='حقبة سرية', slug='secret-era')
        cls.place = HistoricalPlace.objects.create(title='مكان سري', slug='secret-place')
        cls.person = HistoricalPerson.objects.create(title='شخصية سرية', slug='secret-person')
        cls.source = HistoricalSource.objects.create(title='مصدر غير معتمد', slug='unapproved-source', status='PUBLISHED')
        cls.event = HistoricalEvent.objects.create(title='المحطة الأولى', slug='first', era=cls.private_era,
            location=cls.place, status='PUBLISHED', year_order=1, narrative='</script><script>alert(1)</script>')
        cls.event.persons.add(cls.person)
        cls.event.sources.add(cls.source)
        cls.demo = HistoricalEvent.objects.create(title='محطة تجريبية', slug='demo', era=cls.era, status='PUBLISHED', is_demo=True, year_order=2)
        HistoricalEvent.objects.create(title='محطة سرية', slug='private', era=cls.era, year_order=0)

    def test_public_journey_omits_unpublished_relations_and_unapproved_sources(self):
        response = self.client.get('/journey/')
        self.assertEqual(response.status_code, 200)
        first = response.context['stations'][0]
        self.assertEqual(first['id'], self.event.pk)
        self.assertEqual(first['era'], '')
        self.assertEqual(first['place'], '')
        self.assertEqual(first['people'], [])
        self.assertEqual(first['sources'], [])
        for private in ['حقبة سرية', 'مكان سري', 'شخصية سرية', 'مصدر غير معتمد', 'محطة سرية']:
            self.assertNotContains(response, private)
        self.assertNotContains(response, '</script><script>alert(1)</script>')
        self.assertContains(response, '\\u003C/script\\u003E')

    @override_settings(DEMO_MODE=False)
    def test_journey_respects_demo_mode(self):
        response = self.client.get('/journey/')
        self.assertEqual([s['id'] for s in response.context['stations']], [self.event.pk])

    def test_published_relation_is_included(self):
        self.person.status = 'PUBLISHED'; self.person.save()
        self.source.is_approved = True; self.source.save()
        station = self.client.get('/journey/').context['stations'][0]
        self.assertEqual(station['people'][0]['id'], self.person.pk)
        self.assertEqual(station['sources'][0]['id'], self.source.pk)
        self.source.is_demo = True; self.source.save()
        self.assertEqual(self.client.get('/journey/').context['stations'][0]['sources'], [])

    def test_empty_journey_has_usable_fallback(self):
        HistoricalEvent.objects.update(status='DRAFT')
        response = self.client.get('/journey/')
        self.assertContains(response, 'ستظهر هنا المحطات بعد نشر الأحداث.')


class ProviderTests(TestCase):
    def test_project_denial_retains_only_safe_diagnostic(self):
        payload = json.dumps({'error': {'message': 'Your project has been denied access. Please contact support.'}}).encode()
        error = HTTPError('https://provider.test', 403, 'Forbidden', {}, io.BytesIO(payload))
        with patch('apps.ai.providers.urlopen', side_effect=error):
            with self.assertRaisesMessage(ProviderUnavailable, 'project_access_denied'):
                post_json('https://provider.test', {}, {'x-goog-api-key': 'secret-value'})

    @patch.dict(os.environ, {'LLM_MODEL': 'test-model', 'GEMINI_API_KEY': 'test-key'})
    def test_gemini_does_not_return_thinking_or_incomplete_json(self):
        data = {'candidates':[{'finishReason':'STOP','content':{'parts':[{'thought':True,'text':'internal'}, {'text':'{"segments":[]}'}]}}]}
        with patch('apps.ai.providers.post_json', return_value=data):
            self.assertEqual(GeminiProvider().generate('system', {}), '{"segments":[]}')
        data['candidates'][0]['finishReason'] = 'MAX_TOKENS'
        with patch('apps.ai.providers.post_json', return_value=data):
            with self.assertRaisesMessage(ProviderUnavailable, 'generation_incomplete'):
                GeminiProvider().generate('system', {})

    def test_model_abstention_stays_insufficient_not_unavailable(self):
        self.assertEqual(parse_answer('{"segments":[]}', {1}), [])
        provider = Mock(name='gemini'); provider.name = 'gemini'; provider.generate.return_value = '{"segments":[]}'
        from apps.sources.models import SourceChunk
        source = HistoricalSource.objects.create(title='فحص', slug='abstention', status='PUBLISHED', is_approved=True)
        chunk = SourceChunk.objects.create(source=source, text='فحص', embedding_reference='test')
        with patch('apps.ai.services.retrieve', return_value=([chunk], [])), patch('apps.ai.services.get_provider', return_value=provider):
            result = ask('فحص الامتناع')
        self.assertEqual(result['answer'], NO_EVIDENCE)
        self.assertEqual(result['mode'], 'gemini')
        self.assertEqual(result['classification'], 'UNCERTAIN')
        self.assertEqual(result['sources'], [])

    @patch.dict(os.environ, {'LLM_PROVIDER': 'gemini', 'EMBEDDING_BACKEND': 'hash'})
    def test_live_check_rolls_back_its_fixture_and_logs(self):
        from apps.ai.models import AIQueryLog
        def response(_, payload):
            return json.dumps({'segments':[{'text':'ثلاث بطاقات اختبار.', 'chunk_ids':[payload['chunks'][0]['id']]}]})
        provider = Mock(); provider.name = 'gemini'; provider.generate.side_effect = response
        before = (HistoricalSource.objects.count(), AIQueryLog.objects.count())
        with patch('apps.ai.services.get_provider', return_value=provider):
            call_command('check_ai', stdout=io.StringIO())
        self.assertEqual((HistoricalSource.objects.count(), AIQueryLog.objects.count()), before)
