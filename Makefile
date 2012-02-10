all:

test:
	django-admin test --settings=django_conneg.test_settings --pythonpath=.

