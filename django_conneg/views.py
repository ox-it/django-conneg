import datetime
import httplib
import inspect
import itertools
import logging
import time
import warnings

from django.core import exceptions
from django.views.generic import View
from django.utils.decorators import classonlymethod
from django import http
from django.template import RequestContext, TemplateDoesNotExist
from django.shortcuts import render_to_response
from django.utils.cache import patch_vary_headers

from django_conneg.http import MediaType, HttpNotAcceptable
from django_conneg.decorators import renderer

logger = logging.getLogger(__name__)

class ContentNegotiatedView(View):
    _renderers = None
    _renderers_by_format = None
    _renderers_by_mimetype = None
    _default_format = None
    _force_fallback_format = None
    _format_override_parameter = 'format'

    @classonlymethod
    def as_view(cls, **initkwargs):

        renderers_by_format = {}
        renderers_by_mimetype = {}
        renderers = []

        for name in dir(cls):
            value = getattr(cls, name)

            if inspect.ismethod(value) and getattr(value, 'is_renderer', False):
                if value.mimetypes is not None:
                    mimetypes = value.mimetypes
                elif value.format in renderers_by_format:
                    mimetypes = renderers_by_format[value.format].mimetypes
                else:
                    mimetypes = ()
                for mimetype in mimetypes:
                    if mimetype not in renderers_by_mimetype:
                        renderers_by_mimetype[mimetype] = []
                    renderers_by_mimetype[mimetype].append(value)
                if value.format not in renderers_by_format:
                    renderers_by_format[value.format] = []
                renderers_by_format[value.format].append(value)
                renderers.append(value)

        # Order all the renderers by priority
        renderers.sort(key=lambda renderer:-renderer.priority)
        renderers = tuple(renderers)

        initkwargs.update({
            '_renderers': renderers,
            '_renderers_by_format': renderers_by_format,
            '_renderers_by_mimetype': renderers_by_mimetype,
        })

        view = super(ContentNegotiatedView, cls).as_view(**initkwargs)

        view._renderers = renderers
        view._renderers_by_format = renderers_by_format
        view._renderers_by_mimetype = renderers_by_mimetype

        return view

    def dispatch(self, request, *args, **kwargs):
        # This is handy for the view to work out what renderers will
        # be attempted, and to manipulate the list if necessary.
        # Also handy for middleware to check whether the view was a
        # ContentNegotiatedView, and which renderers were preferred.
        self.set_renderers(request)
        return super(ContentNegotiatedView, self).dispatch(request, *args, **kwargs)

    def set_renderers(self, request):
        """
        Makes sure that the renderers attribute on the request is up
        to date. renderers_for_view keeps track of the view that
        is attempting to render the request, so that if the request
        has been delegated to another view we know to recalculate
        the applicable renderers. When called multiple times on the
        same view this will be very low-cost for subsequent calls.
        """
        if getattr(request, 'renderers_for_view', None) != self:
            request.renderers = self.get_renderers(request)
            request.renderers_for_view = self

    def get_renderers(self, request):
        """
        Returns a list of renderer functions in the order they should be tried.
        
        Tries the format override parameter first, then the Accept header. If
        neither is present, attempt to fall back to self._default_format. If
        a fallback format has been specified, we try that last.
        """
        if self._format_override_parameter in request.REQUEST:
            formats = request.REQUEST[self._format_override_parameter].split(',')
            renderers, seen_formats = [], set()
            for format in formats:
                if format in self._renderers_by_format and format not in seen_formats:
                    renderers.extend(self._renderers_by_format[format])
        elif request.META.get('HTTP_ACCEPT'):
            accepts = self.parse_accept_header(request.META['HTTP_ACCEPT'])
            renderers = MediaType.resolve(accepts, self._renderers)
        elif self._default_format:
            renderers = self._renderers_by_format[self._default_format]
        else:
            renderers = []

        fallback_formats = self._force_fallback_format or ()
        fallback_formats = fallback_formats if isinstance(fallback_formats, (list, tuple)) else (fallback_formats,)
        for format in fallback_formats:
            renderers.extend(self._renderers_by_format[format])
        return renderers

    def render(self, request, context, template_name):
        """
        Returns a HttpResponse of the right media type as specified by the
        request.
        
        context can contain status_code and additional_headers members, to set
        the HTTP status code and headers of the request, respectively.
        template_name should lack a file-type suffix (e.g. '.html', as
        renderers will append this as necessary.
        """
        status_code = context.pop('status_code', httplib.OK)
        additional_headers = context.pop('additional_headers', {})

        self.set_renderers(request)

        for renderer in request.renderers:
            response = renderer(self, request, context, template_name)
            if response is NotImplemented:
                continue
            response.status_code = status_code
            response.renderer = renderer
            break
        else:
            tried_mimetypes = list(itertools.chain(*[r.mimetypes for r in request.renderers]))
            response = self.http_not_acceptable(request, tried_mimetypes)
            response.renderer = None
        for key, value in additional_headers.iteritems():
            response[key] = value

        # We're doing content-negotiation, so tell the user-agent that the
        # response will vary depending on the accept header.
        patch_vary_headers(response, ('Accept',))
        return response

    def http_not_acceptable(self, request, tried_mimetypes, *args, **kwargs):
        response = http.HttpResponse("""\
Your Accept header didn't contain any supported media ranges.

Supported ranges are:

 * %s\n""" % '\n * '.join(sorted('%s (%s; %s)' % (f.name, ", ".join(m.value for m in f.mimetypes), f.format) for f in self._renderers if not any(m in tried_mimetypes for m in f.mimetypes))), mimetype="text/plain")
        response.status_code = httplib.NOT_ACCEPTABLE
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

    def render_to_format(self, request, context, template_name, format):
        status_code = context.pop('status_code', httplib.OK)
        additional_headers = context.pop('additional_headers', {})

        for renderer in self._renderers_by_format.get(format, ()):
            response = renderer(self, request, context, template_name)
            if response is not NotImplemented:
                break
        else:
            response = self.http_not_acceptable(request, ())
            renderer = None

        response.status_code = status_code
        response.renderer = renderer
        for key, value in additional_headers.iteritems():
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
        if isinstance(template_name, basestring):
            return '.'.join([template_name, extension])
        raise AssertionError('template_name not of correct type: %r' % type(template_name))

class HTMLView(ContentNegotiatedView):
    _default_format = 'html'

    @renderer(format="html", mimetypes=('text/html', 'application/xhtml+xml'), priority=1, name='HTML')
    def render_html(self, request, context, template_name):
        template_name = self.join_template_name(template_name, 'html')
        if template_name is None:
            return NotImplemented
        try:
            return render_to_response(template_name,
                                      context, context_instance=RequestContext(request),
                                      mimetype='text/html')
        except TemplateDoesNotExist:
            return NotImplemented

class TextView(ContentNegotiatedView):
    @renderer(format="txt", mimetypes=('text/plain',), priority=1, name='Plain text')
    def render_text(self, request, context, template_name):
        template_name = self.join_template_name(template_name, 'txt')
        if template_name is None:
            return NotImplemented
        try:
            return render_to_response(template_name,
                                      context, context_instance=RequestContext(request),
                                      mimetype='text/plain')
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

        def simplify(self, value):
            if isinstance(value, datetime.datetime):
                return time.mktime(value.timetuple()) * 1000
            if isinstance(value, (list, tuple)):
                items = []
                for item in value:
                    item = self.simplify(item)
                    if item is not NotImplemented:
                        items.append(item)
                return items
            if isinstance(value, dict):
                items = {}
                for key, item in value.iteritems():
                    item = self.simplify(item)
                    if item is not NotImplemented:
                        items[key] = item
                return items
            elif type(value) in (str, unicode, int, float, long, bool):
                return value
            elif value is None:
                return value
            else:
                logger.warning("Failed to simplify object of type %r", type(value))
                return NotImplemented

        @renderer(format='json', mimetypes=('application/json',), name='JSON')
        def render_json(self, request, context, template_name):
            context = self.preprocess_context_for_json(context)
            return http.HttpResponse(json.dumps(self.simplify(context), indent=self._json_indent),
                                     mimetype="application/json")

    class JSONPView(JSONView):
        # The query parameter to look for the callback name
        _default_jsonp_callback_parameter = 'callback'
        # The default callback name if none is provided
        _default_jsonp_callback = 'callback'

        @renderer(format='js', mimetypes=('text/javascript', 'application/javascript'), name='JavaScript (JSONP)')
        def render_js(self, request, context, template_name):
            context = self.preprocess_context_for_json(context)
            callback_name = request.GET.get(self._default_jsonp_callback_parameter,
                                            self._default_jsonp_callback)

            return http.HttpResponse('%s(%s);' % (callback_name, json.dumps(self.simplify(context), indent=self._json_indent)),
                                     mimetype="application/javascript")

class ErrorView(HTMLView, JSONPView, TextView):
    _force_fallback_format = ('html', 'json')
    def dispatch(self, request, context, template_name):
        context['status_code'] = context['error']['status_code']
        return self.render(request, context, template_name)

class ErrorCatchingView(ContentNegotiatedView):
    error_view = staticmethod(ErrorView.as_view())
    error_template_names = {httplib.NOT_FOUND: ('conneg/not_found', '404'),
                            httplib.FORBIDDEN: ('conneg/forbidden', '403'),
                            httplib.NOT_ACCEPTABLE: ('conneg/not_acceptable',)}

    def dispatch(self, request, *args, **kwargs):
        try:
            return super(ErrorCatchingView, self).dispatch(request, *args, **kwargs)
        except http.Http404, e:
            return self.error(request, e, args, kwargs, httplib.NOT_FOUND)
        except exceptions.PermissionDenied, e:
            return self.error(request, e, args, kwargs, httplib.FORBIDDEN)
        except HttpNotAcceptable, e:
            return self.error(request, e, args, kwargs, httplib.NOT_ACCEPTABLE)
        except Exception, e:
            return self.error(request, e, args, kwargs, httplib.INTERNAL_SERVER_ERROR)

    def http_not_acceptable(self, request, tried_mimetypes, *args, **kwargs):
        raise HttpNotAcceptable(tried_mimetypes)

    def error(self, request, exception, args, kwargs, status_code):
        method_name = 'error_%d' % status_code
        method = getattr(self, method_name, None)
        if callable(method):
            return method(request, exception, *args, **kwargs)
        else:
            raise exception

    def error_403(self, request, exception, *args, **kwargs):
        context = {'error': {'status_code': httplib.FORBIDDEN,
                             'message': exception.message or None}}
        return self.error_view(request, context,
                               self.error_template_names[httplib.FORBIDDEN])

    def error_404(self, request, exception, *args, **kwargs):
        context = {'error': {'status_code': httplib.NOT_FOUND,
                             'message': exception.message or None}}
        return self.error_view(request, context,
                               self.error_template_names[httplib.NOT_FOUND])

    def error_406(self, request, exception, *args, **kwargs):
        accept_header_parsed = self.parse_accept_header(request.META.get('HTTP_ACCEPT', ''))
        accept_header_parsed.sort(reverse=True)
        accept_header_parsed = map(unicode, accept_header_parsed)
        context = {'error': {'status_code': httplib.NOT_ACCEPTABLE,
                             'tried_mimetypes': exception.tried_mimetypes,
                             'available_renderers': [{'format': renderer.format,
                                                      'mimetypes': map(unicode, renderer.mimetypes),
                                                      'name': renderer.name} for renderer in self._renderers],
                             'format_parameter_name': self._format_override_parameter,
                             'format_parameter': request.REQUEST.get(self._format_override_parameter),
                             'format_parameter_parsed': request.REQUEST.get(self._format_override_parameter, '').split(','),
                             'accept_header': request.META.get('HTTP_ACCEPT'),
                             'accept_header_parsed': accept_header_parsed}}
        return self.error_view(request, context,
                               self.error_template_names[httplib.NOT_ACCEPTABLE])

    def error_500(self, request, exception, *args, **kwargs):
        # Be careful overriding this; you could well lose error-reporting.
        # Much better to set handler500 in your urlconf.
        raise
