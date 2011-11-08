import datetime
import httplib
import inspect
import itertools
import logging
import time

from django.views.generic import View
from django.utils.decorators import classonlymethod
from django import http
from django.template import RequestContext, TemplateDoesNotExist
from django.shortcuts import render_to_response
from django.utils.cache import patch_vary_headers

from django_conneg.http import MediaType
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
        renderer_groups = renderers_by_format.values() \
                        + renderers_by_mimetype.values() \
                        + [renderers]
        for renderers in renderer_groups:
            renderers.sort(key=lambda renderer:-renderer.priority)

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

    def get_renderers(self, request):
        if 'format' in request.REQUEST:
            formats = request.REQUEST[self._format_override_parameter].split(',')
            renderers, seen_formats = [], set()
            for format in formats:
                if format in self._renderers_by_format and format not in seen_formats:
                    renderers.extend(self._renderers_by_format[format])
        elif request.META.get('HTTP_ACCEPT'):
            accepts = self.parse_accept_header(request.META['HTTP_ACCEPT'])
            renderers = MediaType.resolve(accepts, tuple(self._renderers_by_mimetype.items()))
        elif self._default_format:
            renderers = self._renderers_by_format[self._default_format]
        if self._force_fallback_format:
            renderers.extend(self._renderers_by_format[self._force_fallback_format])
        return renderers

    def render(self, request, context, template_name):
        status_code = context.pop('status_code', httplib.OK)
        additional_headers = context.pop('additional_headers', {})

        if not hasattr(request, 'renderers'):
            request.renderers = self.get_renderers(request)

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

    def options(self, request, *args, **kwargs):
        response = http.HttpResponse()
        response['Accept'] = ','.join(m.upper() for m in sorted(self.http_method_names) if hasattr(self, m))
        return response

    @classmethod
    def parse_accept_header(cls, accept):
        media_types = []
        for media_type in accept.split(','):
            try:
                media_types.append(MediaType(media_type))
            except ValueError:
                pass
        return media_types

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
        _json_indent = 0

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
            elif type(value) in (str, unicode, int, float, long):
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
