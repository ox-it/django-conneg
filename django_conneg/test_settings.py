import imp

INSTALLED_APPS = (
    'django_conneg',
)

# Use django_jenkins if it's installed.
try:
    imp.find_module('django_jenkins')
except ImportError:
    pass
else:
    INSTALLED_APPS += ('django_jenkins',)

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3'}}
