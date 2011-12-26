import itertools
import unittest

from django.conf import settings
from django.http import HttpResponse
from django.test.simple import DjangoTestSuiteRunner

from . import http, views, decorators

class DatabaselessTestSuiteRunner(DjangoTestSuiteRunner):
    def setup_databases(self, *args, **kwargs): pass
    def teardown_databases(self, *args, **kwargs): pass

#http://djangosnippets.org/snippets/1011/
NO_SETTING = ('!', None)

class TestSettingsManager(object):
    """
    A class which can modify some Django settings temporarily for a
    test and then revert them to their original values later.
    Automatically handles resyncing the DB if INSTALLED_APPS is
    modified.
    """
    def __init__(self):
        self._original_settings = {}

    def set(self, **kwargs):
        for k,v in kwargs.iteritems():
            self._original_settings.setdefault(k, getattr(settings, k,
                                                          NO_SETTING))
            setattr(settings, k, v)
        if 'INSTALLED_APPS' in kwargs:
            self.syncdb()

    def syncdb(self):
        loading.cache.loaded = False
        call_command('syncdb', verbosity=0)

    def revert(self):
        for k,v in self._original_settings.iteritems():
            if v == NO_SETTING:
                delattr(settings, k)
            else:
                setattr(settings, k, v)
        if 'INSTALLED_APPS' in self._original_settings:
            self.syncdb()
        self._original_settings = {}


class PriorityTestCase(unittest.TestCase):
    mimetypes = ('text/plain', 'application/xml', 'text/html', 'application/json')

    CONNEG_OVERRIDE_PRIORITY = (
            ('html', 1),
            ('json', 2),
            ('xml', 3),
            ('plain', 4)
            )

    CLS_OVERRIDE_PRIORITY = (
            ('html', 1),
            ('json', 4),
            ('xml', 3),
            ('plain', 2)
            )

    def __init__(self, *args, **kwargs):
        super(PriorityTestCase, self).__init__(*args, **kwargs)
        self.settings_manager = TestSettingsManager()

    def tearDown(self):
        self.settings_manager.revert()

    def getRenderer(self, format, mimetypes, name, priority):
        if not isinstance(mimetypes, tuple):
            mimetypes = (mimetypes,)
        def renderer(request, context, template_name):
            return HttpResponse('', mimetype=mimetypes[0])
        renderer.__name__ = 'render_%s' % mimetypes[0].replace('/', '_')
        renderer = decorators.renderer(format=format,
                                       mimetypes=mimetypes,
                                       priority=priority)(renderer)
        return renderer

    def getTestView(self, priorities):
        members = {}
        for i, (mimetype, priority) in enumerate(priorities.items()):
            _fmt = mimetype.split('/')[1]
            members['render_%d' % i] = self.getRenderer(_fmt, mimetype, str(i), priority)
        TestView = type('TestView',
                        (views.ContentNegotiatedView,),
                        members)
        return TestView

    def testEqualQuality(self):
        accept_header = ', '.join(self.mimetypes)
        accept = views.ContentNegotiatedView.parse_accept_header(accept_header)

        for mimetypes in itertools.permutations(self.mimetypes):
            renderers = tuple(self.getRenderer(str(i), mimetype, str(i), -i) for i, mimetype in enumerate(mimetypes))

            renderers = http.MediaType.resolve(accept, renderers)

            for renderer, mimetype in zip(renderers, mimetypes):
                self.assertEqual(iter(renderer.mimetypes).next(), http.MediaType(mimetype))

    def testEqualQualityView(self):
        accept_header = ', '.join(self.mimetypes)
        accept = views.ContentNegotiatedView.parse_accept_header(accept_header)

        for mimetypes in itertools.permutations(self.mimetypes):
            priorities = dict((mimetype, -i) for i, mimetype in enumerate(mimetypes))
            test_view = self.getTestView(priorities).as_view()
            renderers = http.MediaType.resolve(accept, test_view._renderers)

            for renderer, mimetype in zip(renderers, mimetypes):
                self.assertEqual(iter(renderer.mimetypes).next(), http.MediaType(mimetype))

    def testPrioritySorting(self):
        for mimetypes in itertools.permutations(self.mimetypes):
            priorities = dict((mimetype, -i) for i, mimetype in enumerate(mimetypes))
            test_view = self.getTestView(priorities).as_view()

            renderer_priorities = [renderer.priority for renderer in test_view._renderers]
            self.assertSequenceEqual(renderer_priorities, sorted(renderer_priorities, reverse=True))

    def testPrioritySettingsOverride(self):
        """
        Checks for settings Priority Overrides using CONNEG_OVERRIDE_PRIORITY
        """
        settings_prio = self.CONNEG_OVERRIDE_PRIORITY
        settings_prio_rank = tuple(sorted(dict(settings_prio), key=lambda k:
                        -dict(settings_prio)[k]))
        self.settings_manager.set(
            CONNEG_OVERRIDE_PRIORITY=settings_prio)

        for mimetypes in itertools.permutations(self.mimetypes):
            priorities = dict((mimetype, -i) for i, mimetype in enumerate(mimetypes))
            test_view = self.getTestView(priorities).as_view()
            final_prio = tuple([(r.format, r.priority) for r in
                test_view._renderers])
            final_prio_rank = tuple(sorted(dict(final_prio), key=lambda k:
                -dict(final_prio)[k]))
            self.assertSequenceEqual(final_prio_rank,
                settings_prio_rank)

    def testPriorityClsOverride(self):
        """
        Checks for class Priority Overrides using _override_priority
        which takes precedence over settings parameter.
        """
        settings_prio = self.CONNEG_OVERRIDE_PRIORITY
        settings_prio_rank = tuple(sorted(dict(settings_prio), key=lambda k:
                        -dict(settings_prio)[k]))
        self.settings_manager.set(
            CONNEG_OVERRIDE_PRIORITY=settings_prio)

        cls_prio = self.CLS_OVERRIDE_PRIORITY
        cls_prio_rank = tuple(sorted(dict(cls_prio), key=lambda k:
                        -dict(cls_prio)[k]))

        for mimetypes in itertools.permutations(self.mimetypes):
            priorities = dict((mimetype, -i) for i, mimetype in enumerate(mimetypes))

            viewCls = self.getTestView(priorities)
            viewCls._override_priority = cls_prio
            test_view = viewCls.as_view()

            final_prio = tuple([(r.format, r.priority) for r in
                test_view._renderers])
            final_prio_rank = tuple(sorted(dict(final_prio), key=lambda k:
                -dict(final_prio)[k]))
            self.assertSequenceEqual(final_prio_rank,
                cls_prio_rank)

if __name__ == '__main__':
    unittest.main()
