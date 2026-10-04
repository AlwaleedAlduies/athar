"""Production settings for the private app network behind our HTTPS proxy."""
import os

os.environ.setdefault('DEBUG', 'false')
os.environ.setdefault('DEMO_MODE', 'false')

from .settings import *  # noqa: F403,E402

if DEBUG:
    raise RuntimeError('Production requires DEBUG=false')
if DEMO_MODE:
    raise RuntimeError('Production requires DEMO_MODE=false')
if len(SECRET_KEY) < 50:
    raise RuntimeError('Production SECRET_KEY must contain at least 50 characters')
if not os.getenv('DATABASE_URL', '').startswith(('postgres://', 'postgresql://')):
    raise RuntimeError('Production requires a PostgreSQL DATABASE_URL')

railway_domain = os.getenv('RAILWAY_PUBLIC_DOMAIN', '').strip()
default_hosts = f'{railway_domain},healthcheck.railway.app,localhost' if railway_domain else ''
ALLOWED_HOSTS = [host.strip() for host in (os.getenv('ALLOWED_HOSTS') or default_hosts).split(',') if host.strip()]
if not ALLOWED_HOSTS or any(host == '*' or '://' in host or '/' in host for host in ALLOWED_HOSTS):
    raise RuntimeError('Set explicit ALLOWED_HOSTS for the production domain')
default_origin = f'https://{railway_domain}' if railway_domain else ''
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in (os.getenv('CSRF_TRUSTED_ORIGINS') or default_origin).split(',') if origin.strip()]
if not CSRF_TRUSTED_ORIGINS or any(not origin.startswith('https://') or '*' in origin for origin in CSRF_TRUSTED_ORIGINS):
    raise RuntimeError('Set explicit HTTPS CSRF_TRUSTED_ORIGINS')

# Only Caddy or Railway's HTTPS edge should reach the application port.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_REDIRECT_EXEMPT = [r'^healthz/$']
MEDIA_ROOT = Path(os.environ.get('MEDIA_ROOT', '/app/media'))
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
DATABASES['default']['CONN_HEALTH_CHECKS'] = True
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {'django': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False}},
}
