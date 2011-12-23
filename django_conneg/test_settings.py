DATAASES = type('FakeDatabaseConfig',
                 (dict,),
                 {'__nonzero__': lambda self: True,
                  '__contains__': lambda self, key: True})()

INSTALLED_APPS = (
    'django_conneg',
)

TEST_RUNNER = 'django_conneg.tests.DatabaselessTestSuiteRunner'
