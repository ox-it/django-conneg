import imp

INSTALLED_APPS = (
    'django_conneg',
    'django_conneg.tests',
)

SECRET_KEY = 'test secret key'

# Use django_jenkins if it's installed.
try:
    imp.find_module('django_jenkins')
except ImportError:
    pass
else:
    INSTALLED_APPS += ('django_jenkins',)

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3'}}

LOGIN_URL = '/login/'

ROOT_URLCONF = 'django_conneg.tests.urls'

BASIC_AUTH_ALLOW_HTTP = True

MIDDLEWARE_CLASSES = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_conneg.support.middleware.BasicAuthMiddleware',
)
