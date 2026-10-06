import json
import logging
from apps.ai.providers import get_provider, ProviderUnavailable
from apps.ai.prompts import SIMULATION_PROMPT
from apps.ai.services import retrieve

WARNING = 'أنت الآن تغادر السجل التاريخي الموثق وتدخل محاكاة تعليمية. ما يلي ليس حدثًا تاريخيًا.'
logger = logging.getLogger(__name__)
SIMULATION_FIELDS = ('alternative', 'possible_consequences', 'influencing_factors')
SIMULATION_SCHEMA = {
    'type': 'object',
    'properties': {field: {'type': 'string'} for field in SIMULATION_FIELDS},
    'required': list(SIMULATION_FIELDS),
    'additionalProperties': False,
}


def parse_simulation(raw):
    """Accept prose or flat text lists without coercing malformed model output."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Invalid simulation response')
    normalized = {}
    for field in SIMULATION_FIELDS:
        value = data.get(field)
        if isinstance(value, list):
            if not 1 <= len(value) <= 20 or any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError('Invalid simulation list')
            value = '\n'.join('• ' + item.strip() for item in value)
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 4000:
            raise ValueError('Invalid simulation field')
        normalized[field] = value.strip()
    return normalized

def run_simulation(scenario, choice):
    result = {'classification': 'SIMULATION', 'label': 'محاكاة تعليمية', 'warning': WARNING,
              'decision_point': scenario.decision_point, 'alternative': scenario.alternative,
              'possible_consequences': scenario.possible_consequences, 'influencing_factors': scenario.influencing_factors,
              'mode': 'نشاط تعليمي مُعد مسبقًا', 'historical_context': 'لم يُضف سياق موثق لهذا النشاط بعد.',
              'return_url': scenario.event.get_absolute_url(), 'choice': choice}
    if choice.strip():
        result['alternative'] = 'البديل الذي اخترته للتأمل: ' + choice.strip() + '\n\n' + scenario.alternative
    try:
        chunks, _ = retrieve(scenario.decision_point, scenario.event)
        result['historical_context'] = '\n'.join(c.text for c in chunks) or result['historical_context']
        provider = get_provider()
        if provider:
            data = parse_simulation(provider.generate(
                SIMULATION_PROMPT,
                {'context': result['historical_context'], 'decision': scenario.decision_point, 'choice': choice},
                schema=SIMULATION_SCHEMA,
            ))
            result.update(data)
            result['mode'] = 'محاكاة مولدة بالذكاء الاصطناعي'
    except Exception as exc:
        # Log a bounded code only; provider bodies, source text and keys stay private.
        safe_codes = {'connection_failed', 'credentials_missing', 'credentials_rejected',
                      'access_denied', 'project_access_denied', 'quota_exceeded',
                      'provider_http_error', 'generation_incomplete', 'generation_empty',
                      'invalid_response', 'model_not_configured', 'unknown_provider'}
        reason = str(exc) if isinstance(exc, ProviderUnavailable) and str(exc) in safe_codes else type(exc).__name__
        logger.warning('Simulation generation failed: scenario=%s reason=%s', scenario.pk, reason)
        result['mode'] = 'تعذر التوليد الآلي — يعرض النشاط التعليمي المُعد مسبقًا'
    return result
