import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from apps.ai.providers import ProviderUnavailable
from apps.simulations.services import parse_simulation, run_simulation, SIMULATION_SCHEMA


class SimulationGenerationTests(SimpleTestCase):
    def setUp(self):
        self.event = SimpleNamespace(get_absolute_url=lambda: '/explore/10/')
        self.scenario = SimpleNamespace(
            pk=2, event=self.event, decision_point='قرار تعليمي',
            alternative='بديل معد مسبقًا', possible_consequences='نتائج معدة مسبقًا',
            influencing_factors='عوامل معدة مسبقًا',
        )
        self.prose = {'alternative': 'بديل محتمل', 'possible_consequences': 'قد يتغير التوقيت',
                      'influencing_factors': 'المعلومات المتاحة'}

    def run_with(self, provider):
        with patch('apps.simulations.services.retrieve', return_value=([SimpleNamespace(text='سياق موثق')], [])), \
             patch('apps.simulations.services.get_provider', return_value=provider):
            return run_simulation(self.scenario, 'تغيير التوقيت')

    def test_live_provider_list_shape_is_rendered_as_generated_text(self):
        payload = {**self.prose, 'possible_consequences': ['قد يتأخر الوصول', 'قد تتغير الخطة'],
                   'influencing_factors': ['الوقت', 'الإمداد']}
        provider = Mock(generate=Mock(return_value=json.dumps(payload)))
        result = self.run_with(provider)
        self.assertEqual(result['mode'], 'محاكاة مولدة بالذكاء الاصطناعي')
        self.assertEqual(result['possible_consequences'], '• قد يتأخر الوصول\n• قد تتغير الخطة')
        self.assertEqual(result['influencing_factors'], '• الوقت\n• الإمداد')
        self.assertEqual(result['historical_context'], 'سياق موثق')
        self.assertEqual(result['classification'], 'SIMULATION')
        self.assertIn('ليس حدثًا تاريخيًا', result['warning'])
        self.assertEqual(provider.generate.call_args.kwargs['schema'], SIMULATION_SCHEMA)

    def test_existing_string_shape_remains_supported(self):
        result = self.run_with(Mock(generate=Mock(return_value=json.dumps(self.prose))))
        for field, value in self.prose.items():
            self.assertEqual(result[field], value)
        self.assertEqual(result['mode'], 'محاكاة مولدة بالذكاء الاصطناعي')

    def test_rejects_empty_nested_nontext_and_oversized_fields(self):
        invalid = [None, 42, True, '', '   ', [], [''], ['ok', None],
                   [['nested']], {'text': 'nested'}, 'x' * 4001,
                   ['x'] * 21, ['x' * 2000, 'y' * 2000]]
        for value in invalid:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ValueError):
                    parse_simulation(json.dumps({**self.prose, 'possible_consequences': value}))
        for raw in ['not JSON', '[]', 'null', '{}']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_simulation(raw)

    def test_invalid_result_preserves_all_prepared_fields_and_logs_safely(self):
        payload = {**self.prose, 'influencing_factors': {'private-response': 'secret'}}
        with self.assertLogs('apps.simulations.services', level='WARNING') as logs:
            result = self.run_with(Mock(generate=Mock(return_value=json.dumps(payload))))
        self.assertEqual(result['possible_consequences'], self.scenario.possible_consequences)
        self.assertEqual(result['influencing_factors'], self.scenario.influencing_factors)
        self.assertIn(self.scenario.alternative, result['alternative'])
        self.assertIn('تعذر التوليد', result['mode'])
        self.assertIn('reason=ValueError', logs.output[0])
        self.assertNotIn('secret', ''.join(logs.output) + json.dumps(result))

    def test_provider_failure_keeps_prepared_activity_without_leaking_error(self):
        for message in ['connection_failed', 'private-api-key-and-response']:
            with self.subTest(message=message), self.assertLogs('apps.simulations.services', level='WARNING') as logs:
                result = self.run_with(Mock(generate=Mock(side_effect=ProviderUnavailable(message))))
            self.assertIn('تعذر التوليد', result['mode'])
            self.assertNotIn('private-api-key-and-response', ''.join(logs.output) + json.dumps(result))

    def test_extractive_mode_uses_prepared_activity(self):
        result = self.run_with(None)
        self.assertEqual(result['mode'], 'نشاط تعليمي مُعد مسبقًا')
        self.assertEqual(result['possible_consequences'], self.scenario.possible_consequences)
