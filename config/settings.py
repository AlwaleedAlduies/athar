import os
import secrets
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
DEBUG = os.getenv('DEBUG', 'true').lower() == 'true'
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError('SECRET_KEY is required when DEBUG=false')
    secret_file = BASE_DIR / '.local-secret'
    if not secret_file.exists():
        secret_file.write_text(secrets.token_urlsafe(64), encoding='utf-8')
    SECRET_KEY = secret_file.read_text(encoding='utf-8')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost,testserver').split(',')
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'rest_framework', 'apps.accounts', 'apps.history', 'apps.sources',
    'apps.knowledge', 'apps.ai', 'apps.simulations', 'apps.dashboard',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'],
              'APP_DIRS': True, 'OPTIONS': {'context_processors': [
                  'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth',
                  'django.contrib.messages.context_processors.messages', 'apps.history.context.site_context']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': dj_database_url.config(default='sqlite:///' + (BASE_DIR / 'db.sqlite3').as_posix(), conn_max_age=60)}
AUTH_USER_MODEL = 'accounts.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'ar'
LANGUAGES = [('ar', 'العربية')]
TIME_ZONE = 'Asia/Riyadh'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/discover/'
LOGOUT_REDIRECT_URL = '/'
DEMO_MODE = os.getenv('DEMO_MODE', 'true').lower() == 'true'
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['apps.accounts.authentication.CSRFSafeSessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['apps.accounts.permissions.AdminOrReadOnly'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 24,
    'DEFAULT_THROTTLE_RATES': {'ai': os.getenv('AI_RATE', '20/hour'), 'auth': '30/hour'},
    'EXCEPTION_HANDLER': 'apps.accounts.permissions.api_exception_handler',
}
