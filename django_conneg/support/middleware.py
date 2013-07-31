import base64
try: # Python 3
    from http.client import UNAUTHORIZED, FORBIDDEN, FOUND
    import urllib.parse as urllib_parse
except ImportError: # Python 2.x
    from httplib import UNAUTHORIZED, FORBIDDEN, FOUND
    import urlparse as urllib_parse

from django.conf import settings
from django.contrib.auth import authenticate
from django_conneg.http import MediaType
from django_conneg.views import HTMLView, JSONPView, TextView

class UnauthorizedView(HTMLView, JSONPView, TextView):
    _force_fallback_format = 'txt'
    template_name = 'conneg/unauthorized'

    def get(self, request):
        self.context.update({'status_code': UNAUTHORIZED,
                             'error': 'You need to be authenticated to perform this request.'})
        return self.render()
    post = put = delete = get

class InactiveUserView(HTMLView, JSONPView, TextView):
    _force_fallback_format = 'txt'
    template_name = 'conneg/inactive_user'

    def get(self, request):
        self.context.update({'status_code': FORBIDDEN,
                             'error': 'Your account is inactive.'})
        return self.render()
    post = put = delete = get

class BasicAuthMiddleware(object):
    """
    Sets request.user if there are valid basic auth credentials on the
    request, and turns @login_required redirects into 401 responses for
    non-HTML responses.
    """

    allow_http = getattr(settings, 'BASIC_AUTH_ALLOW_HTTP', False) or settings.DEBUG

    unauthorized_view = staticmethod(UnauthorizedView.as_view())
    inactive_user_view = staticmethod(InactiveUserView.as_view())

    def process_request(self, request):
        # Ignore if user already authenticated
        if request.user.is_authenticated():
            return

        # Don't do anything for unsecure requests, unless DEBUG is on
        if not self.allow_http and not request.is_secure():
            return

        # Parse the username and password out of the Authorization
        # HTTP header and set request.user if we find an active user.
        # We don't use auth.login, as the authorization is only valid
        # for this one request.
        authorization = request.META.get('HTTP_AUTHORIZATION')
        if not authorization or not authorization.startswith('Basic '):
            return
        try:
            credentials = base64.b64decode(authorization[6:].encode('utf-8')).decode('utf-8').split(':', 1)
        except TypeError:
            return
        if len(credentials) != 2:
            return
        user = authenticate(username=credentials[0], password=credentials[1])
        if user and user.is_active:
            request.user = user
        elif user and not user.is_active:
            return self.inactive_user_view(request)
        else:
            return self.unauthorized_view(request)

    def process_response(self, request, response):
        """
        Adds WWW-Authenticate: Basic headers to 401 responses, and rewrites
        redirects the login page to be 401 responses if it's a non-browser
        agent.
        """
        process = False

        # Don't do anything for unsecure requests, unless DEBUG is on
        if not self.allow_http and not request.is_secure():
            return response

        if response.status_code == UNAUTHORIZED:
            pass
        elif response.status_code == FOUND:
            location = urllib_parse.urlparse(response['Location'])
            if location.path != settings.LOGIN_URL:
                # If it wasn't a redirect to the login page, we don't touch it.
                return response
            elif not self.is_agent_a_robot(request):
                # We don't touch requests made in order to be shown to humans.
                return response

        realm = getattr(settings, 'BASIC_AUTH_REALM', request.META.get('HTTP_HOST', 'restricted'))
        
        if response.status_code == FOUND:
            response = self.unauthorized_view(request)

        authenticate = response.get('WWW-Authenticate', None)
        if authenticate:
            authenticate = 'Basic realm="%s", %s' % (realm, authenticate)
        else:
            authenticate = 'Basic realm="%s"' % realm
        response['WWW-Authenticate'] = authenticate

        return response

    def is_agent_a_robot(self, request):
        if request.META.get('HTTP_ORIGIN'):
            # A CORS request (from JavaScript)
            return True
        if request.META.get('HTTP_X_REQUESTED_WITH'):
            # An AJAX request (from JavaScript)
            return True
        accept = sorted(MediaType.parse_accept_header(request.META.get('HTTP_ACCEPT', '')), reverse=True)
        if accept and accept[0].type in (('text', 'html', None), ('application', 'xml', 'xhtml')):
            # Agents whose first preference is for HTML are presumably trying
            # to show it to a human.
            return False
        if 'MSIE' in request.META.get('HTTP_USER_AGENT', ''):
            # We'll assume that IE (which doesn't set a proper Accept header)
            # is making a request on behalf of a human. It does seem to set an
            # Origin header when using XDomainRequest, and can set
            # X-Requested-With if the request is being made from JavaScript.
            return False
        return True
