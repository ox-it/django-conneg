from collections import defaultdict
import inspect
import weakref

from django_conneg.http import MediaType

class Conneg(object):
    _memo_by_class = weakref.WeakKeyDictionary()

    def __init__(self, renderers=None, obj=None):
        self.renderers_by_format = defaultdict(list)
        self.renderers_by_mimetype = defaultdict(list)

        if renderers:
            renderers = list(renderers)
        elif obj:
            cls = type(obj)
            renderers = self._memo_by_class.get(cls)
            if renderers is None:
                # This is about as much memoization as we can do. We keep
                # unbound 
                renderers = []
                for name in dir(cls):
                    try:
                        value = getattr(obj, name)
                    except AttributeError:
                        continue
                    if inspect.ismethod(value) and getattr(value, 'is_renderer', False):
                        renderers.append(value)
                self._memo_by_class[cls] = renderers

            # Bind the renderers to this instance. See
            # http://stackoverflow.com/a/1015405/613023 for an explanation.
            renderers = [r.__get__(obj) for r in renderers]

        for renderer in renderers:
            if renderer.mimetypes is not None:
                for mimetype in renderer.mimetypes:
                    self.renderers_by_mimetype[mimetype].append(renderer)
                self.renderers_by_format[renderer.format].append(renderer)

        # Order all the renderers by priority
        renderers.sort(key=lambda renderer:-renderer.priority)
        self.renderers = tuple(renderers)

    def get_renderers(self, request, context=None, template_name=None,
                      accept_header=None, formats=None, default_format=None, fallback_formats=None):
        """
        Returns a list of renderer functions in the order they should be tried.
        
        Tries the format override parameter first, then the Accept header. If
        neither is present, attempt to fall back to self._default_format. If
        a fallback format has been specified, we try that last.
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
            renderers.extend(self.renderers_by_format[format])

        if context is not None and template_name:
            renderers = [r for r in renderers if not hasattr(r, 'test')
                                              or r.test(r.__self__, request, context, template_name)]

        return renderers

    def __add__(self, other):
        if not isinstance(other, Conneg):
            other = Conneg(obj=other)
        return Conneg(self.renderers + other.renderers)