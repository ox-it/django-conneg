try:
    from pytz import utc
except ImportError:
    import datetime

    class _UTC(datetime.tzinfo):
        def utcoffset(self, dt):
            return datetime.timedelta(0)
        def dst(self, dt):
            return datetime.timedelta(0)
        def tzname(self, dt):
            return "UTC"
    
    utc = _UTC()

from django.http import HttpResponse
import inspect
content_type_arg = 'mimetype' if 'mimetype' in inspect.getargspec(HttpResponse.__init__).args else 'content_type'
