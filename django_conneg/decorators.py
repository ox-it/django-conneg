from django_conneg.conneg import Renderer

def renderer(format, mimetypes=(), priority=0, name=None, test=None):
    """
    Decorates a view method to say that it renders a particular format and mimetypes.

    Use as:
        @renderer(format="foo")
        def render_foo(self, request, context, template_name): ...
    or
        @renderer(format="foo", mimetypes=("application/x-foo",))
        def render_foo(self, request, context, template_name): ...
    
    The former case will inherit mimetypes from the previous renderer for that
    format in the MRO. Where there isn't one, it will default to the empty
    tuple.

    Takes an optional priority argument to resolve ties between renderers.
    """

    def g(f):
        return Renderer(f, format, mimetypes, priority, name, test)
    return g
