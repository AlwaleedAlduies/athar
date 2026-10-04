import json
from apps.ai.providers import get_provider
from apps.ai.prompts import SIMULATION_PROMPT
from apps.ai.services import retrieve

WARNING = 'أنت الآن تغادر السجل التاريخي الموثق وتدخل محاكاة تعليمية. ما يلي ليس حدثًا تاريخيًا.'

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
            data = json.loads(provider.generate(SIMULATION_PROMPT, {'context': result['historical_context'], 'decision': scenario.decision_point, 'choice': choice}))
            for field in ['alternative', 'possible_consequences', 'influencing_factors']:
                if not isinstance(data.get(field), str) or not 1 <= len(data[field]) <= 4000:
                    raise ValueError('Invalid simulation response')
            result.update({key: data[key] for key in ['alternative', 'possible_consequences', 'influencing_factors']})
            result['mode'] = 'محاكاة مولدة بالذكاء الاصطناعي'
    except Exception:
        result['mode'] = 'تعذر التوليد الآلي — يعرض النشاط التعليمي المُعد مسبقًا'
    return result
