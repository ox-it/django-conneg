Content-negotiation framework for Django
========================================

This project provides a simple and extensible framework for producing views
that content-negotiate in Django.

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

