Content-negotiation framework for Django
========================================

This project provides a simple and extensible framework for producing views
that content-negotiate in Django.

Prerequisites
-------------

This library depends on Django 1.3, which you can install using your package
manager on recent distributions, or using pip::

    pip install -r requirements.txt

``pip`` is called ``pip-python`` on Fedora. It is generally provided by a
``python-pip`` package.

Using
-----

To define a view, do something like this::

    from django_conneg.views import ContentNegotiatedView

    class IndexView(ContentNegotiatedView):
        def get(self, request):
            context = {
                # Build context here
            }

            # Call render, passing a template name (without file extension)
            return self.render(request, context, 'index')

This will then look for a renderer that can provide a representation that
matches what was asked for in the Accept header.

By default ContentNegotiatedView provides no renderers, so the above snippet
would always return a 405 Not Acceptable to tell the user-agent that it
couldn't provide a response in a suggested format.

To define a renderer on a view, do something like this::

    import json

    from django.http import HttpResponse

    from django_conneg.decorators import renderer

    class JSONView(ContentNegotiatedView):
        @renderer(format='json', mimetypes=('application/json',), name='JSON')
        def render_json(self, request, context, template_name):
            # Very simplistic, and will fail when it encounters 'non-primitives'
            # like Django Model objects, Forms, etc.
            return HttpResponse(json.dumps(context), mimetype='application/json')

.. note::
   ``django-conneg`` already provides a slightly more sophisticated JSONView;
   see below for more information.

You can render to a particular format by calling ``render_to_format()`` on the
view::

    class IndexView(ContentNegotiatedView):
        def get(self, request):
            # ...

            if some_condition:
                return self.render_to_format(request, context, 'index', 'html')
            else:
                return self.render(request, context, 'index')
    

Forcing a particular renderer from the client
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default, a client can request a particular set of renderers be tried by
using the ``format`` query or POST parameter::

    GET /some-view/?format=json,yaml

The formats correspond to the ``format`` argument to the ``@renderer``
decorator.

To change the name of the parameter used, override
``_format_override_parameter`` on the view class::

    class MyView(ContentNegotiatedView):
        _format_override_parameter = 'output'


Providing fallback renderers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sometimes you might want to provide a response in some format even if the
those in the Accept header can't be honoured. This is useful when providing
error responses in a different format to the client's expected format. To do
this, set the ``_force_fallback_format`` attribute to the name of the format::

    class MyView(ContentNegotiatedView):
        _force_fallback_format = 'html'

If a client doesn't provide an Accept header, then you can specify a default
format with ``_default_format``::

    class MyView(ContentNegotiatedView):
        _default_format = 'html'

Built-in renderer views
~~~~~~~~~~~~~~~~~~~~~~~

``django_conneg`` includes the following built-in renderers in the
``django_conneg.views`` module:

* ``HTMLView`` (renders a ``.html`` template with media type ``text/html``)
* ``TextView`` (renders a ``.txt`` template with media type ``text/plain``)
* ``JSONView`` (coerces the context to JavaScript primitives and returns as ``application/json``)
* ``JSONPView`` (as ``JSONView``, but wraps in a callback and returns as ``application/javascript``)

Using these, you could define a view that renders to both HTML and JSON like this::

    from django_conneg.views import HTMLView

    class IndexView(JSONView, HTMLView):
        def get(self, request):
            # ...
            return self.render(request, context, 'index')

Accessing renderer details
--------------------------

The renderer used to construct a response is exposed as a ``renderer``
attribute on the response object::

    class IndexView(JSONView, HTMLView):
        def get(self, request):
            # ...
            response = self.render(request, context, 'index')
            response['X-Renderer-Format'] = response.renderer.format
            return response 


Renderer priorities
-------------------

Some user-agents might specify various media types with equal levels of
desirability. For example, previous versions of Safari and Chrome `used to send
<http://www.gethifi.com/blog/browser-rest-http-accept-headers#highlighter_222123>`_
an ``Accept`` header like this::

     application/xml,application/xhtml+xml,text/html;q=0.9,
     text/plain;q=0.8,image/png,*/*;q=0.5

Without any additional hints it would be non-deterministic as to whether XML or
XHTML is served.

By passing a ``priority`` argument to the ``@renderer`` decorator you can
specify an ordering of renderers for such ambiguous situations::

     class IndexView(ContentNegotiatedView):
         @renderer(format='xml', mimetypes=('application/xml',), name='XML', priority=0)
         def render_xml(request, context, template_name):
             # ...

         @renderer(format='html', mimetypes=('application/xhtml+xml','text/html), name='HTML', priority=1)
         def render_html(request, context, template_name):
             # ...

As higher-numbered priorities are preferred, this will result in HTML always
being prefered over XML in ambiguous situations.

By default, ``django-conneg``'s built-in renderers have a priority of 0, except
for ``HTMLView`` and ``TextView``, which each have a priority of 1 for the
reason given above.


Improved 40x response handling
------------------------------

Django provides a couple of useful exceptions, ``Http404`` and
``PermissionDenied``, which you may want to use in your application. However,
it's only possible to customise the 404 site-wide (either by providing a
``404.html`` template, or by setting ``handler404`` in your urlconf), and
until Django 1.4 comes out, PermissionDenied will always result in a very
spartan error page.

``django-conneg`` provides an ``ErrorCatchingView`` which you can use as a
mixin to customise the rendering of responses for these error situations::

    from django_conneg.views import HTMLView, ErrorCatchingView

    class IndexView(HTMLView, ErrorCatchingView):
        # ...

You can then customise error responses in one of the following ways:

* overriding the ``conneg/(forbidden|not_found|not_acceptable).(html|txt) templates
* overriding ``error_403``, ``error_404`` or ``error_406`` methods on the view
* overriding the ``error_template_names`` attribute to specify a non-standard template name:

In the latter case, you can do something like::

    import httplib
    from django.util.datastructures import MergeDict
    from django_conneg.views import HTMLView, ErrorCatchingView

    class IndexView(HTMLView, ErrorCatchingView):
        # Provide a view-specific 404 page. Use MergeDict to use django_conneg's
        # defaults for other types of errors.
        error_template_names = MergeDict({httplib.NOT_FOUND: 'foo/404'},
                                         ErrorCatchingView.error_template_names)
        # ...


Running the tests
-----------------

``django-conneg`` has a modest test suite. To run it, head to the root of the
repository and run::

    django-admin test --settings=django_conneg.test_settings --pythonpath=.

If you don't have Django, you'll need to install it as detailed in the
Prerequisites section above.
