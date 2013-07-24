from collections import defaultdict
import inspect
import weakref

from django_conneg.http import MediaType

class Renderer(object):
    def __init__(self, func, format, mimetypes=(), priority=0, name=None, test=None, instance=None, owner=None):
        self.func = func
        self.test = test or (lambda s,r,c,t: True)
        if instance:
            self.func = func.__get__(instance, owner)
            self.test = test.__get__(instance, owner)

        self.is_renderer = True
        self.format = format
        self.mimetypes = set(MediaType(mimetype, priority) for mimetype in mimetypes)
        self.name = name
        self.priority = priority

        self.is_bound = instance is not None

    def __get__(self, instance, owner=None):
        return Renderer(self.func, self.format, self.mimetypes, self.priority, self.name, self.test, instance, owner)
    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)

    @property
    def __name__(self):
        return self.func.__name__
    @__name__.setter
    def __name__(self, name):
        self.func.__name__ = name

    def __repr__(self):
        if self.is_bound:
            return "<bound renderer {0}.{1} of {2}>".format(self.func.im_class.__name__ or '?',
                                                            self.func.__name__,
                                                            self.func.__self__)
        else:
            return "<unbound renderer {0}>".format(self.func.__name__)

class Conneg(object):
    _memo_by_class = weakref.WeakKeyDictionary()

    def __init__(self, renderers=None, obj=None):
        self.renderers_by_format = defaultdict(list)
        self.renderers_by_mimetype = defaultdict(list)

        if renderers is not None:
            renderers = list(renderers)
        elif obj:
            cls = type(obj) if not isinstance(obj, type) else obj
            renderers = self._memo_by_class.get(cls)
            if renderers is None:
                # This is about as much memoization as we can do. We keep
                # the renderers unbound for now
                renderers = []
                for name in dir(cls):
                    try:
                        value = getattr(obj, name)
                    except AttributeError:
                        continue
                    if isinstance(value, Renderer):
                        renderers.append(value)
                self._memo_by_class[cls] = renderers

            # Bind the renderers to this instance. See
            # http://stackoverflow.com/a/1015405/613023 for an explanation.
            renderers = [r.__get__(obj, cls) for r in renderers]

        for renderer in renderers:
            if renderer.mimetypes is not None:
                for mimetype in renderer.mimetypes:
                    self.renderers_by_mimetype[mimetype].append(renderer)
                self.renderers_by_format[renderer.format].append(renderer)

        # Order all the renderers by priority
        renderers.sort(key=lambda renderer:-renderer.priority)
        self.renderers = tuple(renderers)

    def get_renderers(self, request, context=None, template_name=None,
                      accept_header=None, formats=None, default_format=None, fallback_formats=None,
                      early=False):
        """
        Returns a list of renderer functions in the order they should be tried.
        
        Tries the format override parameter first, then the Accept header. If
        neither is present, attempt to fall back to self._default_format. If
        a fallback format has been specified, we try that last.
        
        If early is true, don't test renderers to see whether they can handle
        a serialization. This is useful if we're trying to find all relevant
        serializers before we've built a context which they will accept. 
        """
        if formats:
            renderers, seen_formats = [], set()
            for format in formats:
                if format in self.renderers_by_format and format not in seen_formats:
                    renderers.extend(self.renderers_by_format[format])
                    seen_formats.add(format)
        elif accept_header:
            accepts = MediaType.parse_accept_header(accept_header)
            renderers = MediaType.resolve(accepts, self.renderers)
        elif default_format:
            renderers = self.renderers_by_format[default_format]
        else:
            renderers = []

        fallback_formats = fallback_formats if isinstance(fallback_formats, (list, tuple)) else (fallback_formats,)
        for format in fallback_formats:
            for renderer in self.renderers_by_format[format]:
                if renderer not in renderers:
                    renderers.append(renderer)

        if not early and context is not None and template_name:
            renderers = [r for r in renderers if r.test(request, context, template_name)]

        return renderers

    def __add__(self, other):
        if not isinstance(other, Conneg):
            other = Conneg(obj=other)
        return Conneg(self.renderers + other.renderers)