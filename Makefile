all:

debian-package:
	pwd
	dpkg-buildpackage
	mkdir debian-package
	mv ../python-django-conneg_* debian-package

clean-debian-package:
	rm -rf debian-package

test:
	django-admin.py test --settings=django_conneg.test_settings --pythonpath=.

tox:
	tox

clean-tox:
	rm -rf .tox

clean: clean-debian-package clean-tox
