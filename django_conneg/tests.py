import itertools
import sys
import unittest

from django.conf import settings
from django.conf.urls.defaults import patterns, url
from django.http import HttpResponse
from django.shortcuts import render_to_response
from django.template import Context, Template, RequestContext, TemplateDoesNotExist
from django.test.simple import DjangoTestSuiteRunner
from django.test.client import Client

from . import http, views, decorators

class DatabaselessTestSuiteRunner(DjangoTestSuiteRunner):
    def setup_databases(self, *args, **kwargs): pass
    def teardown_databases(self, *args, **kwargs): pass

class TestURLConf(object):
    def __init__(self, testurl=None, testview=None):
        urlpatterns = patterns('',
                url(r'^%s$' % (testurl), testview, name="testview"),
                )
        TestURLConf.urlpatterns = urlpatterns

class TestTemplate(object):
    class FakeTemplate(object):
        pass
    template = FakeTemplate()
    template.html = "test html {{var}}"
    template.plain = "test plain {{var}}"
    template.xml = "test xml {{var}}"
    template.json = "test json {{var}}"

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
        sys.modules['testtemplates'] = TestTemplate()

    def tearDown(self):
        self.settings_manager.revert()

    def getRenderer(self, _format, mimetypes, name, priority):
        if not isinstance(mimetypes, tuple):
            mimetypes = (mimetypes,)
        def renderer(request, context, template_name):
            return HttpResponse('', mimetype=mimetypes[0])
        renderer.__name__ = 'render_%s' % mimetypes[0].replace('/', '_')
        renderer = decorators.renderer(format=_format,
                                       mimetypes=mimetypes,
                                       priority=priority)(renderer)
        return renderer

    def getTemplateRenderer(self, _format, mimetypes, name, priority):
        if not isinstance(mimetypes, tuple):
            mimetypes = (mimetypes,)
        def renderer(self, request, context, template_name):
            if template_name is None:
                return NotImplemented
            template_name = "%s.%s" % (template_name, _format)
            tmod, tclass, tformat = template_name.split('.')
            testtemplates = __import__(tmod)
            tcls = getattr(testtemplates, tclass, None)
            tfmt = getattr(tcls, tformat, None)
            t = Template(tfmt)
            return HttpResponse(t.render(Context(context)),
                    mimetype=mimetypes[0])
        renderer.__name__ = 'render_%s' % mimetypes[0].replace('/', '_')
        renderer = decorators.renderer(format=_format,
                                       mimetypes=mimetypes,
                                       priority=priority)(renderer)
        return renderer

    def getTestView(self, priorities, templaterender = False):
        members = {}
        for i, (mimetype, priority) in enumerate(priorities.items()):
            _fmt = mimetype.split('/')[1]
            if templaterender:
                rendererfactory = self.getTemplateRenderer
            else:
                rendererfactory = self.getRenderer
            members['render_%d' % i] = rendererfactory(_fmt, mimetype, str(i), priority)
        TestView = type('TestView',
                        (views.ContentNegotiatedView,),
                        members)
        return TestView

    def getTestTemplateView(self, priorities, extra_attr=None):
        testView = self.getTestView(priorities, templaterender = True)
        def get(self, request):
            context = {'var':'ok'}
            return self.render(request, context,
                    'testtemplates.template')
        setattr(testView, 'get', get)
        if extra_attr and isinstance(extra_attr, dict):
            for k,v in extra_attr.items():
                setattr(testView, k, v)
        testView = testView.as_view()
        return testView

    def setURLConf(self, testView, testurl):
        """
        Fakes a URLConf vith the given view,
        and adds it to the faked settings
        """
        testUrlConf = TestURLConf(
                        testview=testView,
                        testurl=testurl)
        sys.modules['testurlconfmodule'] = testUrlConf
        testurlconfmodule = __import__('testurlconfmodule')
        self.settings_manager.set(ROOT_URLCONF=testurlconfmodule)

    ###########################
    # Tests Begin

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


    ###############
    # Client Tests

    def testViewURLNoAcceptHeaderNoDefaultFormat(self):
        """
        Checks for No Accept header response (no default format)
        """
        testurl = "testurl"
        priorities = dict((mimetype, -i) for i, mimetype in enumerate(self.mimetypes))
        testView = self.getTestTemplateView(priorities)
        self.setURLConf(testView, testurl)

        cc = Client()
        res = cc.get("/%s" % testurl)
        self.assertEqual(res.status_code, 406)

    def testViewURLNoAcceptHeaderWithDefault(self):
        """
        Checks for No Accept header response (with default format)
        """
        testurl = "testurl"
        priorities = dict((mimetype, -i) for i, mimetype in enumerate(self.mimetypes))
        testView = self.getTestTemplateView(priorities,
                extra_attr={'_default_format':'html'})
        self.setURLConf(testView, testurl)

        cc = Client()
        res = cc.get("/%s" % testurl)
        self.assertEqual(res.status_code, 200)

    def testViewURLAcceptAllHeaders(self):
        """
        """
        testurl = "testurl"
        priorities = dict((mimetype, -i) for i, mimetype in enumerate(self.mimetypes))
        testView = self.getTestTemplateView(priorities)
        self.setURLConf(testView, testurl)

        cc = Client(HTTP_ACCEPT="*/*")
        res = cc.get("/%s" % testurl)
        self.assertEqual(res.status_code, 200)

    def testViewURLAcceptJSONContent(self):
        """
        Checks for a sample content-type (status code, content and headers)
        """
        testurl = "testurl"
        priorities = dict((mimetype, -i) for i, mimetype in enumerate(self.mimetypes))
        testView = self.getTestTemplateView(priorities)
        self.setURLConf(testView, testurl)

        cc = Client(HTTP_ACCEPT="application/json")
        res = cc.get("/%s" % testurl)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, 'test json ok')
        self.assertEqual(res._headers,
                {'vary': ('Vary', 'Accept'),
                 'content-type': ('Content-Type', 'application/json')})


if __name__ == '__main__':
    unittest.main()
