import json
import os
from abc import ABC, abstractmethod
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError, URLError

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

urlopen = build_opener(ProxyHandler({}), NoRedirect()).open

class ProviderUnavailable(Exception):
    pass

def post_json(url, payload, headers=None, timeout=35):
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ProviderUnavailable('invalid_response')
            return json.loads(raw)
    except HTTPError as exc:
        # Retain an actionable code, never the response body or credentials.
        reason = {401: 'credentials_rejected', 403: 'access_denied', 429: 'quota_exceeded'}.get(exc.code, 'provider_http_error')
        if exc.code == 403:
            try:
                message = json.loads(exc.read(16384)).get('error', {}).get('message', '')
                if 'project has been denied access' in message.lower():
                    reason = 'project_access_denied'
            except (ValueError, AttributeError):
                pass
        raise ProviderUnavailable(reason) from None
    except (URLError, TimeoutError, OSError):
        raise ProviderUnavailable('connection_failed') from None
    except (ValueError, TypeError):
        raise ProviderUnavailable('invalid_response') from None

class BaseLLMProvider(ABC):
    name = ''
    def __init__(self, configuration=None):
        self.configuration = configuration
        self.model = configuration.model if configuration else os.getenv('LLM_MODEL', '')
        self.timeout = configuration.timeout_seconds if configuration else (300 if self.name == 'local' else 35)
        if not self.model:
            raise ProviderUnavailable('model_not_configured')
    @abstractmethod
    def generate(self, system, payload, *, max_tokens=1800, schema=None):
        raise NotImplementedError

    def base(self, default):
        return self.configuration.base_url.rstrip('/') if self.configuration else default.rstrip('/')

    def key(self, env_name, official_base):
        if not self.configuration:
            return os.getenv(env_name, '')
        value = self.configuration.get_key()
        if not value and self.configuration.base_url.rstrip('/') == official_base.rstrip('/'):
            value = os.getenv(env_name, '')
        return value

class OpenAIProvider(BaseLLMProvider):
    name = 'openai'
    def generate(self, system, payload, *, max_tokens=1800, schema=None):
        key = self.key('OPENAI_API_KEY', 'https://api.openai.com/v1')
        if not key and (not self.configuration or self.configuration.kind != 'compatible'):
            raise ProviderUnavailable('credentials_missing')
        options = {'max_tokens': max_tokens} if self.configuration and self.configuration.kind == 'compatible' else {'max_completion_tokens': max_tokens}
        data = post_json(self.base('https://api.openai.com/v1') + '/chat/completions', {
            'model': self.model, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
            'response_format': {'type': 'json_object'}, **options,
        }, {'Authorization': f'Bearer {key}'} if key else {}, timeout=self.timeout)
        if data['choices'][0].get('finish_reason') == 'length':
            raise ProviderUnavailable('generation_incomplete')
        return data['choices'][0]['message']['content']

class GeminiProvider(BaseLLMProvider):
    name = 'gemini'
    def generate(self, system, payload, *, max_tokens=1800, schema=None):
        key = self.key('GEMINI_API_KEY', 'https://generativelanguage.googleapis.com/v1beta')
        if not key:
            raise ProviderUnavailable('credentials_missing')
        from urllib.parse import quote
        data = post_json(self.base('https://generativelanguage.googleapis.com/v1beta') + f'/models/{quote(self.model, safe="")}:generateContent', {
            'system_instruction': {'parts': [{'text': system}]},
            'contents': [{'role': 'user', 'parts': [{'text': json.dumps(payload, ensure_ascii=False)}]}],
            'generationConfig': {'responseMimeType': 'application/json', 'maxOutputTokens': max_tokens},
        }, {'x-goog-api-key': key}, timeout=self.timeout)
        candidates = data.get('candidates', [])
        if not candidates or candidates[0].get('finishReason') != 'STOP':
            raise ProviderUnavailable('generation_incomplete')
        text = ''.join(p.get('text', '') for p in candidates[0].get('content', {}).get('parts', []) if not p.get('thought'))
        if not text.strip():
            raise ProviderUnavailable('generation_empty')
        return text

class LocalProvider(BaseLLMProvider):
    name = 'local'
    def generate(self, system, payload, *, max_tokens=1800, schema=None):
        key = self.configuration.get_key() if self.configuration else ''
        data = post_json(self.base(os.getenv('LOCAL_LLM_URL', 'http://127.0.0.1:11434')) + '/api/chat', {
            'model': self.model, 'stream': False, 'format': schema or 'json',
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
            'options': {'num_predict': max_tokens, 'temperature': 0, 'num_ctx': 8192},
        }, {'Authorization': f'Bearer {key}'} if key else {}, timeout=self.timeout)
        if data.get('done_reason') == 'length':
            raise ProviderUnavailable('generation_incomplete')
        return data['message']['content']

def get_provider(configuration=None):
    from .configuration import active_configuration
    configuration = configuration or active_configuration()
    name = configuration.kind if configuration else os.getenv('LLM_PROVIDER', 'extractive')
    if name == 'extractive':
        return None
    providers = {'openai': OpenAIProvider, 'compatible': OpenAIProvider, 'gemini': GeminiProvider, 'local': LocalProvider}
    if name not in providers:
        raise ProviderUnavailable('unknown_provider')
    return providers[name](configuration)
