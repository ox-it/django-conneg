import base64
import httplib
import urlparse

from django.conf import settings
from django.contrib.auth import authenticate
from django_conneg.http import MediaType
from django_conneg.views import HTMLView, JSONPView, TextView

class UnauthorizedView(HTMLView, JSONPView, TextView):
    _force_fallback_format = 'txt'
    template_name = 'conneg/unauthorized'

    def get(self, request):
        self.context.update({'status_code': httplib.UNAUTHORIZED,
                             'error': 'You need to be authenticated to perform this request.'})
        return self.render()
    post = put = delete = get

class InactiveUserView(HTMLView, JSONPView, TextView):
    _force_fallback_format = 'txt'
    template_name = 'conneg/inactive_user'

    def get(self, request):
        self.context.update({'status_code': httplib.FORBIDDEN,
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
            credentials = base64.b64decode(authorization[6:]).split(':', 1)
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

        if response.status_code == httplib.UNAUTHORIZED:
            process = True
        elif response.status_code == httplib.FOUND:
            # Two ways to check whether the request was AJAX or CORS
            if request.is_ajax() or request.META.get('HTTP_ORIGIN'):
                process = True
            else:
                # Don't return a 401 if the client preferred HTML
                accept = sorted(MediaType.parse_accept_header(request.META.get('HTTP_ACCEPT', '')), reverse=True)
                if not accept or accept[0].type not in (('text', 'html', None), ('application', 'xml', 'xhtml')):
                    location = urlparse.urlparse(response['Location'])
                    if location.path == settings.LOGIN_URL:
                        response = self.unauthorized_view(request)
                        process = True

        if not process:
            return response

        realm = getattr(settings, 'BASIC_AUTH_REALM', request.META.get('HTTP_HOST', 'restricted'))

        authenticate = response.get('WWW-Authenticate', None)
        if authenticate:
            authenticate = 'Basic realm="%s", %s' % (realm, authenticate)
        else:
            authenticate = 'Basic realm="%s"' % realm
        response['WWW-Authenticate'] = authenticate

        return response
