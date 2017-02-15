from __future__ import unicode_literals

import datetime
try: # Python < 3
    import httplib as http_client
    import urlparse as urllib_parse
    from urllib import urlencode
    str_types = (unicode, str)
except ImportError: # Python >= 3
    import http.client as http_client
    import urllib.parse as urllib_parse
    from urllib.parse import urlencode
    str_types = (str,)
    unicode = str
import inspect
import itertools
import logging
import sys
import time
import urllib
import warnings

from django.core import exceptions
from django.views.generic import View
from django.utils.decorators import classonlymethod
from django import http
from django.template import RequestContext, TemplateDoesNotExist
from django.shortcuts import render_to_response, render
from django.utils.cache import patch_vary_headers

from django_conneg.conneg import Conneg
from django_conneg.decorators import renderer
from django_conneg.http import MediaType, HttpError, HttpNotAcceptable
from django_conneg.utils import utc, content_type_arg

logger = logging.getLogger(__name__)

class BaseContentNegotiatedView(View):
    conneg = None
    context = None
    _default_format = None
    _force_fallback_format = None
    _format_override_parameter = 'format'
    _format_url_parameter = 'format'
    _include_renderer_details_in_context = True
    
    template_name = None

    @classonlymethod
    def as_view(cls, **initkwargs):
        view = super(BaseContentNegotiatedView, cls).as_view(**initkwargs)
        view.conneg = Conneg(obj=cls)
        return view

    def dispatch(self, request, *args, **kwargs):
        # This is handy for the view to work out what renderers will
        # be attempted, and to manipulate the list if necessary.
        # Also handy for middleware to check whether the view was a
        # BaseContentNegotiatedView, and which renderers were preferred.
        if self.context is None:
            self.context = {'additional_headers': {}}

        format_url_parameter = kwargs.pop(self._format_url_parameter, None)
        if format_url_parameter:
            self.format_override = [format_url_parameter]
        elif request.GET.get(self._format_override_parameter):
            self.format_override = request.GET[self._format_override_parameter].split(',')
        elif request.POST.get(self._format_override_parameter):
            self.format_override = request.POST[self._format_override_parameter].split(',')
        else:
            self.format_override = None

        self.request = request
        self.args = args
        self.kwargs = kwargs
        self.conneg = Conneg(obj=self)
        self.set_renderers(request)
        return super(BaseContentNegotiatedView, self).dispatch(request, *args, **kwargs)

    def set_renderers(self, request=None, context=None, template_name=None, early=False):
        """
        Makes sure that the renderers attribute on the request is up
        to date. renderers_for_view keeps track of the view that
        is attempting to render the request, so that if the request
        has been delegated to another view we know to recalculate
        the applicable renderers. When called multiple times on the
        same view this will be very low-cost for subsequent calls.
        """
        request, context, template_name = self.get_render_params(request, context, template_name)

        args = (self.conneg, context, template_name,
                self._default_format, self._force_fallback_format, self._format_override_parameter)
        if getattr(request, 'renderers_for_args', None) != args:
            fallback_formats = self._force_fallback_format or ()
            if not isinstance(fallback_formats, (list, tuple)):
                fallback_formats = (fallback_formats,)
            request.renderers = self.conneg.get_renderers(request=request,
                                                          context=context,
                                                          template_name=template_name,
                                                          accept_header=request.META.get('HTTP_ACCEPT'),
                                                          formats=self.format_override,
                                                          default_format=self._default_format,
                                                          fallback_formats=fallback_formats,
                                                          early=early)
            request.renderers_for_view = args
        if self._include_renderer_details_in_context:
            self.context['renderers'] = [self.renderer_for_context(request, r) for r in self.conneg.renderers]
        return request.renderers

    def get_render_params(self, request, context, template_name):
        if not template_name:
            template_name = self.template_name
            if isinstance(template_name, str_types) and template_name.endswith('.html'):
                template_name = template_name[:-5]
        return request or self.request, context or self.context, template_name

    def render(self, request=None, context=None, template_name=None):
        """
        Returns a HttpResponse of the right media type as specified by the
        request.
        
        context can contain status_code and additional_headers members, to set
        the HTTP status code and headers of the request, respectively.
        template_name should lack a file-type suffix (e.g. '.html', as
        renderers will append this as necessary.
        """
        request, context, template_name = self.get_render_params(request, context, template_name)

        self.set_renderers()

        status_code = context.pop('status_code', http_client.OK)
        additional_headers = context.pop('additional_headers', {})

        for renderer in request.renderers:
            response = renderer(request, context, template_name)
            if response is NotImplemented:
                continue
            response.status_code = status_code
            response.renderer = renderer
            break
        else:
            tried_mimetypes = list(itertools.chain(*[r.mimetypes for r in request.renderers]))
            response = self.http_not_acceptable(request, tried_mimetypes)
            response.renderer = None
        for key, value in additional_headers.items():
            response[key] = value

        # We're doing content-negotiation, so tell the user-agent that the
        # response will vary depending on the accept header.
        patch_vary_headers(response, ('Accept',))
        return response

    def http_not_acceptable(self, request, tried_mimetypes, *args, **kwargs):
        response = http.HttpResponse("""\
Your Accept header didn't contain any supported media ranges.

Supported ranges are:

 * %s\n""" % '\n * '.join(sorted('%s (%s; %s)' % (f.name, ", ".join(m.value for m in f.mimetypes), f.format) for f in request.renderers if not any(m in tried_mimetypes for m in f.mimetypes))), **{content_type_arg: "text/plain"})
        response.status_code = http_client.NOT_ACCEPTABLE
        return response

    def head(self, request, *args, **kwargs):
        handle_get = getattr(self, 'get', None)
        if handle_get:
            response = handle_get(request, *args, **kwargs)
            response.content = ''
            return response
        else:
            return self.http_method_not_allowed(request, *args, **kwargs)

    def options(self, request, *args, **kwargs):
        response = http.HttpResponse()
        response['Accept'] = ','.join(m.upper() for m in sorted(self.http_method_names) if hasattr(self, m))
        return response

    @classmethod
    def parse_accept_header(cls, accept):
        warnings.warn("The parse_accept_header method has moved to django_conneg.http.MediaType")
        return MediaType.parse_accept_header(accept)

    def render_to_format(self, request=None, context=None, template_name=None, format=None):
        request, context, template_name = self.get_render_params(request, context, template_name)
        self.set_renderers()

        status_code = context.pop('status_code', http_client.OK)
        additional_headers = context.pop('additional_headers', {})

        for renderer in self.conneg.renderers_by_format.get(format, ()):
            response = renderer(request, context, template_name)
            if response is not NotImplemented:
                break
        else:
            response = self.http_not_acceptable(request, ())
            renderer = None

        response.status_code = status_code
        response.renderer = renderer
        for key, value in additional_headers.items():
            response[key] = value
        return response

    def join_template_name(self, template_name, extension):
        """
        Appends an extension to a template_name or list of template_names.
        """
        if template_name is None:
            return None
        if isinstance(template_name, (list, tuple)):
            return tuple('.'.join([n, extension]) for n in template_name)
        if isinstance(template_name, str_types):
            return '.'.join([template_name, extension])
        raise AssertionError('template_name not of correct type: %r' % type(template_name))

    def renderer_for_context(self, request, renderer):
        return {'name': renderer.name,
                'priority': renderer.priority,
                'mimetypes': [m.value for m in renderer.mimetypes],
                'format': renderer.format,
                'url': self.url_for_format(request, renderer.format)}

    def url_for_format(self, request, format):
        qs = urllib_parse.parse_qs(request.META.get('QUERY_STRING', ''))
        qs['format'] = [format]
        return '?{0}'.format(urlencode(qs, True))



class ContentNegotiatedView(BaseContentNegotiatedView):
    @property
    def error_view(self):
        if not hasattr(self, '_error_view'):
            self._error_view = ErrorView.as_view()
        return self._error_view

    error_template_names = {http_client.NOT_FOUND: ('conneg/not_found', '404'),
                            http_client.FORBIDDEN: ('conneg/forbidden', '403'),
                            http_client.NOT_ACCEPTABLE: ('conneg/not_acceptable',),
                            http_client.BAD_REQUEST: ('conneg/bad_request', '400'),
                            http_client.SERVICE_UNAVAILABLE: ('conneg/service_unavailable', '503'),
                            'default': ('conneg/error',)}

    def dispatch(self, request, *args, **kwargs):
        try:
            return super(ContentNegotiatedView, self).dispatch(request, *args, **kwargs)
        except http.Http404 as e:
            return self.error(request, e, args, kwargs, http_client.NOT_FOUND)
        except exceptions.PermissionDenied as e:
            return self.error(request, e, args, kwargs, http_client.FORBIDDEN)
        except HttpError as e:
            return self.error(request, e, args, kwargs, e.status_code)

    def http_not_acceptable(self, request, tried_mimetypes, *args, **kwargs):
        raise HttpNotAcceptable(tried_mimetypes)

    def error(self, request, exception, args, kwargs, status_code):
        method_name = 'error_%d' % status_code
        method = getattr(self, method_name, None)

        # See if we've got a dedicated handler for this status code
        if callable(method):
            return method(request, exception, *args, **kwargs)

        # Otherwise, if it's an HttpError, try to render it to an
        # appropriate template
        context = {'error': {'status_code': status_code,
                             'status_message': http_client.responses.get(status_code)}}
        if isinstance(exception, HttpError) and exception.args:
            context['error']['message'] = exception.args[0]

        template_names = self.error_template_names.get(status_code,
                                                       self.error_template_names['default'])

        return self.error_view(request, context, template_names)

    def error_406(self, request, exception, *args, **kwargs):
        accept_header_parsed = MediaType.parse_accept_header(request.META.get('HTTP_ACCEPT', ''))
        accept_header_parsed.sort(reverse=True)
        accept_header_parsed = map(unicode, accept_header_parsed)
        context = {'error': {'status_code': http_client.NOT_ACCEPTABLE,
                             'tried_mimetypes': exception.tried_mimetypes,
                             'available_renderers': [self.renderer_for_context(request, r) for r in self.conneg.renderers],
                             'format_parameter_name': self._format_override_parameter,
                             'format_parameter': request.GET.get(self._format_override_parameter) or
                                                 request.POST.get(self._format_override_parameter),
                             'format_parameter_parsed': (request.GET.get(self._format_override_parameter, '') or
                                                         request.POST.get(self._format_override_parameter, '')).split(','),
                             'accept_header': request.META.get('HTTP_ACCEPT'),
                             'accept_header_parsed': accept_header_parsed}}
        return self.error_view(request, context,
                               self.error_template_names[http_client.NOT_ACCEPTABLE])

# For backwards compatibility
ErrorCatchingView = ContentNegotiatedView

class HTMLView(ContentNegotiatedView):
    _default_format = 'html'

    @renderer(format="html", mimetypes=('text/html', 'application/xhtml+xml'), priority=1, name='HTML')
    def render_html(self, request, context, template_name):
        template_name = self.join_template_name(template_name, 'html')
        if template_name is None:
            return NotImplemented
        try:
            return render(request, template_name, context,  content_type='text/html')
        except TemplateDoesNotExist:
            return NotImplemented

class TextView(ContentNegotiatedView):
    @renderer(format="txt", mimetypes=('text/plain',), priority=1, name='Plain text')
    def render_text(self, request, context, template_name):
        template_name = self.join_template_name(template_name, 'txt')
        if template_name is None:
            return NotImplemented
        try:
            return render(request, template_name, context,  content_type='text/plain')
        except TemplateDoesNotExist:
            return NotImplemented

try:
    import json
except ImportError:
    try:
        import simplejson as json
    except ImportError:
        pass

# Only define if json is available.
if 'json' in locals():
    class JSONView(ContentNegotiatedView):
        _json_indent = 2

        def preprocess_context_for_json(self, context):
            return context

        def simplify_for_json(self, value):
            if inspect.ismethod(getattr(value, 'simplify_for_json', None)):
                return value.simplify_for_json(self.simplify_for_json)
            if isinstance(value, datetime.datetime):
                if value.tzinfo:
                    value = value.astimezone(utc)
                return int(time.mktime(value.timetuple()) * 1000)
            if isinstance(value, (list, tuple)):
                items = []
                for item in value:
                    item = self.simplify_for_json(item)
                    if item is not NotImplemented:
                        items.append(item)
                return items
            if isinstance(value, dict):
                items = {}
                for key, item in value.items():
                    item = self.simplify_for_json(item)
                    if item is not NotImplemented:
                        items[unicode(key)] = item
                return items
            elif type(value) in (int, float, bool):
                return value
            elif type(value) in str_types:
                return unicode(value)
            elif value is None:
                return value
            else:
                logger.warning("Failed to simplify object of type %r", type(value))
                return NotImplemented

        def simplify(self, value):
            warnings.warn("JSONView.simplify() has been renamed to simplify_for_json")
            return self.simplify_for_json(value)

        @renderer(format='json', mimetypes=('application/json',), name='JSON')
        def render_json(self, request, context, template_name):
            context = self.preprocess_context_for_json(context)
            return http.HttpResponse(json.dumps(self.simplify_for_json(context), indent=self._json_indent),
                                     **{content_type_arg: "application/json"})

    class JSONPView(JSONView):
        # The query parameter to look for the callback name
        _default_jsonp_callback_parameter = 'callback'
        # The default callback name if none is provided
        _default_jsonp_callback = 'callback'

        # Overridden to return JSONP if there's a callback parameter
        @renderer(format='json', mimetypes=('application/json',), name='JSON')
        def render_json(self, request, context, template_name):
            if self._default_jsonp_callback_parameter in request.GET:
                return self.render_js(request, context, template_name)
            else:
                return super(JSONPView, self).render_json(request, context, template_name)

        @renderer(format='js', mimetypes=('text/javascript', 'application/javascript'), name='JavaScript (JSONP)')
        def render_js(self, request, context, template_name):
            context = self.preprocess_context_for_json(context)
            callback_name = request.GET.get(self._default_jsonp_callback_parameter,
                                            self._default_jsonp_callback)

            return http.HttpResponse('%s(%s);' % (callback_name, json.dumps(self.simplify_for_json(context), indent=self._json_indent)),
                                     **{content_type_arg: "application/javascript"})

class ErrorView(HTMLView, JSONPView, TextView):
    _force_fallback_format = ('html', 'json')
    def get(self, request, context, template_name):
        self.context.update(context)
        self.template_name = template_name
        self.context['error']['response'] = http_client.responses[context['error']['status_code']]
        self.context['status_code'] = context['error']['status_code']
        return self.render()
    post = delete = put = get
