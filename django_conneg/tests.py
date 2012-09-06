import itertools
import unittest

from django.http import HttpResponse
from django.test.simple import DjangoTestSuiteRunner

from . import http, views, decorators

class DatabaselessTestSuiteRunner(DjangoTestSuiteRunner):
    def setup_databases(self, *args, **kwargs): pass
    def teardown_databases(self, *args, **kwargs): pass

class PriorityTestCase(unittest.TestCase):
    mimetypes = ('text/plain', 'application/xml', 'text/html', 'application/json')

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
            members['render_%d' % i] = self.getRenderer(str(i), mimetype, str(i), priority)
        TestView = type('TestView',
                        (views.ContentNegotiatedView,),
                        members)
        return TestView

    def testEqualQuality(self):
        accept_header = ', '.join(self.mimetypes)
        accept = http.MediaType.parse_accept_header(accept_header)

        for mimetypes in itertools.permutations(self.mimetypes):
            renderers = tuple(self.getRenderer(str(i), mimetype, str(i), -i) for i, mimetype in enumerate(mimetypes))

            renderers = http.MediaType.resolve(accept, renderers)

            for renderer, mimetype in zip(renderers, mimetypes):
                self.assertEqual(iter(renderer.mimetypes).next(), http.MediaType(mimetype))

    def testEqualQualityView(self):
        accept_header = ', '.join(self.mimetypes)
        accept = http.MediaType.parse_accept_header(accept_header)

        for mimetypes in itertools.permutations(self.mimetypes):
            priorities = dict((mimetype, -i) for i, mimetype in enumerate(mimetypes))
            test_view = self.getTestView(priorities).as_view()
            renderers = http.MediaType.resolve(accept, test_view.conneg.renderers)

            for renderer, mimetype in zip(renderers, mimetypes):
                self.assertEqual(iter(renderer.mimetypes).next(), http.MediaType(mimetype))

    def testPrioritySorting(self):
        for mimetypes in itertools.permutations(self.mimetypes):
            priorities = dict((mimetype, -i) for i, mimetype in enumerate(mimetypes))
            test_view = self.getTestView(priorities).as_view()

            renderer_priorities = [renderer.priority for renderer in test_view.conneg.renderers]
            self.assertEqual(renderer_priorities, sorted(renderer_priorities, reverse=True))



if __name__ == '__main__':
    unittest.main()
