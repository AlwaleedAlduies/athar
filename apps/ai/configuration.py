import base64
import hashlib
import ipaddress
import os
import re
import socket
from urllib.parse import urlsplit
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ValidationError


def cipher():
    # A distinct, stable server-side key; database copies alone cannot reveal credentials.
    secret = os.getenv('AI_CREDENTIAL_KEY', settings.SECRET_KEY)
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('athar-ai:' + secret).encode()).digest()))


def validate_endpoint(url, kind):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or re.search(r'[\s\\]', url):
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        ips = [ipaddress.ip_address(row[4][0]) for row in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)]
        if not ips or any(ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved for ip in ips):
            raise ValueError()
        if kind in {'gemini', 'openai'} and (parsed.scheme != 'https' or not all(ip.is_global for ip in ips)):
            raise ValueError()
        if parsed.scheme == 'http' and not all(ip.is_loopback for ip in ips):
            raise ValueError()
    except (ValueError, OSError):
        raise ValidationError('استخدم HTTPS لمزوّد بعيد، أو HTTP على localhost للخدمة المحلية. لا تُقبل بيانات دخول داخل الرابط أو عناوين metadata.') from None
    return url.rstrip('/')


def active_configuration():
    from .models import ProviderConfiguration
    return ProviderConfiguration.objects.filter(is_active=True).first()


def active_identity():
    config = active_configuration()
    return {'provider': config.kind, 'model': config.model} if config else {'provider': os.getenv('LLM_PROVIDER','extractive'), 'model':os.getenv('LLM_MODEL','')}


def safe_error(exc):
    if isinstance(exc, ValidationError):
        return ' '.join(exc.messages)[:500]
    return {'project_access_denied':'يرفض Gemini الوصول إلى المشروع (403). راجع Google أو اختر مزوّدًا آخر.',
        'access_denied':'رفض المزوّد صلاحية الوصول.', 'credentials_rejected':'رفض المزوّد مفتاح API.',
        'credentials_missing':'أضف مفتاح API لهذا الإعداد.', 'model_not_configured':'حدد اسم النموذج.',
        'quota_exceeded':'بلغ المزوّد حد الاستخدام.', 'not_configured':'فعّل مزوّدًا في إعدادات الذكاء الاصطناعي.',
        'generation_incomplete':'توقف التوليد قبل اكتمال النتيجة. جرّب مقاطع أقل أو نموذجًا آخر.',
        'connection_failed':'تعذر الاتصال أو انتهت المهلة. تحقق من تشغيل الخدمة والرابط والمهلة.',
        'provider_http_error':'أعاد المزوّد خطأ. تحقق من رابط API واسم النموذج.',
        'invalid_response':'أعاد المزوّد استجابة غير صالحة.',
    }.get(str(exc), 'تعذر إكمال الطلب. بقي النص محفوظًا؛ راجع إعدادات المزوّد ثم أعد المحاولة.')
