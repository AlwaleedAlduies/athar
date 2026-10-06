"""Development-only settings for the Replit preview, not for publishing."""
import os

if os.environ.get('SESSION_SECRET'):
    os.environ.setdefault('SECRET_KEY', os.environ['SESSION_SECRET'])

from .settings import *  # noqa: F403, E402

DEBUG = True
ALLOWED_HOSTS = ['*']
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_TRUSTED_ORIGINS = [
    f'https://{host.strip()}'
    for host in (
        os.environ.get('REPLIT_DOMAINS', '').split(',')
        + [os.environ.get('REPLIT_DEV_DOMAIN', '')]
    )
    if host.strip()
]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False