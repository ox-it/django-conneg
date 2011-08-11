import datetime
import httplib
import inspect
import itertools
import time

from django.views.generic import View
from django.utils.decorators import classonlymethod
from django import http
from django.template import RequestContext, TemplateDoesNotExist
from django.shortcuts import render_to_response
from django.utils.cache import patch_vary_headers

from django_conneg.http import MediaType
from django_conneg.decorators import renderer

class ContentNegotiatedView(View):
    _renderers_by_format = None
    _renderers_by_mimetype = None
    _default_format = None
    _force_fallback_format = None
    _format_override_parameter = 'format'

    @classonlymethod
    def as_view(cls, **initkwargs):

        renderers_by_format = {}
        renderers_by_mimetype = {}

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
                    renderers_by_mimetype[mimetype] = value
                renderers_by_format[value.format] = value

        initkwargs.update({
            '_renderers_by_format': renderers_by_format,
            '_renderers_by_mimetype': renderers_by_mimetype,
        })

        view = super(ContentNegotiatedView, cls).as_view(**initkwargs)

        return view

    def get_renderers(self, request):
        if 'format' in request.REQUEST:
            formats = request.REQUEST[self._format_override_parameter].split(',')
            renderers, seen_formats = [], set()
            for format in formats:
                if format in self._renderers_by_format and format not in seen_formats:
                    renderers.append(self._renderers_by_format[format])
        elif request.META.get('HTTP_ACCEPT'):
            accepts = self.parse_accept_header(request.META['HTTP_ACCEPT'])
            renderers = MediaType.resolve(accepts, tuple(self._renderers_by_mimetype.items()))
        elif self._default_format:
            renderers = [self._renderers_by_format[self._default_format]]
        if self._force_fallback_format:
            renderers.append(self._renderers_by_format[self._force_fallback_format])
        return renderers

    def render(self, request, context, template_name):
        status_code = context.pop('status_code', httplib.OK)

        if not hasattr(request, 'renderers'):
            request.renderers = self.get_renderers(request)

        for renderer in request.renderers:
            response = renderer(self, request, context, template_name)
            if response is NotImplemented:
                continue
            response.status_code = status_code
            break
        else:
            tried_mimetypes = list(itertools.chain(*[r.mimetypes for r in request.renderers]))
            response = self.http_not_acceptable(request, tried_mimetypes)

        # We're doing content-negotiation, so tell the user-agent that the
        # response will vary depending on the accept header.
        patch_vary_headers(response, ('Accept',))
        return response

    def http_not_acceptable(self, request, tried_mimetypes, *args, **kwargs):
        tried_mimetypes = ()
        response = http.HttpResponse("""\
Your Accept header didn't contain any supported media ranges.

Supported ranges are:

 * %s\n""" % '\n * '.join(sorted('%s (%s; %s)' % (f[1].name, f[0].value, f[1].format) for f in self._renderers_by_mimetype.items() if not f[0] in tried_mimetypes)), mimetype="text/plain")
        response.status_code = httplib.NOT_ACCEPTABLE
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
        render_method = self.FORMATS[format]
        status_code = context.pop('status_code', httplib.OK)
        response = render_method(self, request, context, template_name)
        response.status_code = status_code
        return response

class HTMLView(ContentNegotiatedView):
    _default_format = 'html'

    @renderer(format="html", mimetypes=('text/html', 'application/xhtml+xml'), priority=1, name='HTML')
    def render_html(self, request, context, template_name):
        if template_name is None:
            return NotImplemented
        try:
            return render_to_response(template_name+'.html',
                                      context, context_instance=RequestContext(request),
                                      mimetype='text/html')
        except TemplateDoesNotExist:
            return NotImplemented

class TextView(ContentNegotiatedView):
    @renderer(format="txt", mimetypes=('text/plain',), priority=1, name='Plain text')
    def render_text(self, request, context, template_name):
        if template_name is None:
            return NotImplemented
        try:
            return render_to_response(template_name+'.txt',
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
        def simplify(self, value):
            if isinstance(value, datetime.datetime):
                return time.mktime(value.timetuple()) * 1000
            if isinstance(value, (list, tuple)):
                return [self.simplify(item) for item in value]
            if isinstance(value, dict):
                return dict([(key, self.simplify(value[key])) for key in value])
            else:
                return value

        @renderer(format='json', mimetypes=('application/json',), name='JSON')
        def render_json(self, request, context, template_name):
            return http.HttpResponse(json.dumps(self.simplify(context)),
                                     mimetype="application/json")

    class JSONPView(JSONView):
        _default_jsonp_callback_parameter = 'callback'
        _default_jsonp_callback = 'callback'

        @renderer(format='js', mimetypes=('text/javascript', 'application/javascript'), name='JavaScript (JSONP)')
        def render_js(self, request, context, template_name):
            callback_name = request.GET.get(self._default_jsonp_callback_parameter,
                                            self._default_jsonp_callback)

            return http.HttpResponse('%s(%s);' % (callback_name, json.dumps(self.simplify(context))),
                                     mimetype="application/javascript")
