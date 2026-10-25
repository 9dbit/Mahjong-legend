"""Studio + game server. PostgreSQL is mandatory in production."""
import os
from pathlib import Path
from urllib.parse import urlsplit, unquote, parse_qs

BASE_DIR = Path(__file__).resolve().parent.parent
PRODUCTION = os.environ.get('STUDIO_PRODUCTION') == '1'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if PRODUCTION:
        raise RuntimeError('DJANGO_SECRET_KEY must be configured')
    SECRET_KEY = 'local-development-only-never-use-on-public-host'
DEBUG = False
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',') + ['healthcheck.railway.app']
CSRF_TRUSTED_ORIGINS = [v for v in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',') if v]
ROOT_URLCONF = 'studio_server.urls'
WSGI_APPLICATION = 'studio_server.wsgi.application'
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'game_studio']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware',
              'django.contrib.sessions.middleware.SessionMiddleware',
              'django.middleware.csrf.CsrfViewMiddleware',
              'django.contrib.auth.middleware.AuthenticationMiddleware',
              'game_studio.security.ResponseHeaders']
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3',
                         'NAME': os.environ.get('STUDIO_SQLITE_PATH', str(BASE_DIR / '.studio-local.sqlite3')),
                         'OPTIONS': {'timeout': 30, 'transaction_mode': 'IMMEDIATE'}}}
if os.environ.get('DATABASE_URL'):
    url = urlsplit(os.environ['DATABASE_URL'])
    if url.scheme not in ('postgres', 'postgresql'):
        raise RuntimeError('DATABASE_URL must be PostgreSQL')
    DATABASES['default'] = {'ENGINE': 'django.db.backends.postgresql',
        'NAME': unquote(url.path.lstrip('/')), 'USER': unquote(url.username or ''),
        'PASSWORD': unquote(url.password or ''), 'HOST': url.hostname, 'PORT': url.port or 5432,
        'CONN_MAX_AGE': 60, 'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {'connect_timeout': 10, **{k:v[0] for k,v in parse_qs(url.query).items() if k in ('sslmode',)}}}
elif PRODUCTION:
    raise RuntimeError('Persistent PostgreSQL DATABASE_URL is required in production')
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_TZ = True
TIME_ZONE = 'Asia/Jakarta'
SESSION_COOKIE_NAME = 'MLSTUDIO'
SESSION_COOKIE_SECURE = PRODUCTION
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_AGE = 8 * 3600
CSRF_COOKIE_SECURE = PRODUCTION
CSRF_COOKIE_SAMESITE = 'Strict'
CSRF_FAILURE_VIEW = 'game_studio.views.csrf_failure'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = PRODUCTION
SECURE_REDIRECT_EXEMPT = [r'^health$']
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
DATA_UPLOAD_MAX_MEMORY_SIZE = 36 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 30
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
STUDIO_SETUP_TOKEN = os.environ.get('STUDIO_SETUP_TOKEN', '')
STUDIO_TICKET_TTL_SECONDS = 24 * 3600
STUDIO_MAX_SESSIONS = int(os.environ.get('STUDIO_MAX_SESSIONS', '100000'))
STUDIO_LEASE_SECONDS = 120
STUDIO_MATH_MIN_ROUNDS = int(os.environ.get('STUDIO_MATH_MIN_ROUNDS', '100000'))
STUDIO_MATH_MAX_ROUNDS = int(os.environ.get('STUDIO_MATH_MAX_ROUNDS', '1000000'))
STUDIO_JOB_LEASE_SECONDS = 300
STUDIO_MEDIA_ROOT = os.environ.get('STUDIO_MEDIA_ROOT', str(BASE_DIR / '.studio-media'))
if PRODUCTION and not os.environ.get('STUDIO_S3_BUCKET'):
    raise RuntimeError('Private persistent STUDIO_S3_BUCKET is required in production')
