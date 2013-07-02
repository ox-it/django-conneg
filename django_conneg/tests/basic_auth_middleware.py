import base64
try:
    from http.client import OK, FORBIDDEN, FOUND, UNAUTHORIZED
except ImportError:
    from httplib import OK, FORBIDDEN, FOUND, UNAUTHORIZED

from django.contrib.auth.models import User
from django.test import TestCase
from django.test.utils import override_settings

import mock

test_username = 'username'
test_password = 'password'

def mocked_authenticate(username, password):
    if username == test_username and password == test_password:
        return User(username='active')

def mocked_authenticate_inactive(username, password):
    if username == test_username and password == test_password:
        return User(username='inactive', is_active=False)

def basic_auth(username, password):
    return {'HTTP_AUTHORIZATION': 'Basic ' + base64.b64encode(':'.join([username, password]).encode('utf-8')).decode('utf-8')}

@override_settings(LOGIN_URL='/login/',
                   MIDDLEWARE_CLASSES=('django.contrib.sessions.middleware.SessionMiddleware',
                                       'django.contrib.auth.middleware.AuthenticationMiddleware',
                                       'django_conneg.support.middleware.BasicAuthMiddleware'),
                   BASIC_AUTH_ALLOW_HTTP = True)
class BasicAuthTestCase(TestCase):
    urls = 'django_conneg.tests.urls'

    def testOptionalWithout(self):
        response = self.client.get('/optional-auth/')
        self.assertEqual(response.status_code, OK)
        self.assertFalse(response.is_authenticated)

    @mock.patch('django_conneg.support.middleware.authenticate', mocked_authenticate)
    def testOptionalWithCorrect(self):
        response = self.client.get('/optional-auth/',
                                   **basic_auth(test_username, test_password))
        self.assertEqual(response.status_code, OK)
        self.assertTrue(response.is_authenticated)

    @mock.patch('django_conneg.support.middleware.authenticate', mocked_authenticate)
    def testOptionalWithIncorrect(self):
        response = self.client.get('/optional-auth/',
                                   **basic_auth(test_username, 'not-the-password'))
        self.assertEqual(response.status_code, UNAUTHORIZED)
        self.assertEqual(response['WWW-Authenticate'], 'Basic realm="restricted"')

    def testRequiredWithoutHTML(self):
        response = self.client.get('/login-required/', HTTP_ACCEPT='text/html')
        self.assertEqual(response.status_code, FOUND)
        self.assertEqual(response['Location'],
                         'http://testserver/login/?next=/login-required/')

    def testRequiredWithoutJSON(self):
        response = self.client.get('/login-required/', HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, UNAUTHORIZED)
        self.assertEqual(response['WWW-Authenticate'], 'Basic realm="restricted"')

    @mock.patch('django_conneg.support.middleware.authenticate', mocked_authenticate)
    def testRequiredWithCorrect(self):
        response = self.client.get('/login-required/',
                                   **basic_auth(test_username, test_password))
        self.assertEqual(response.status_code, OK)
        self.assertTrue(response.is_authenticated)

    @mock.patch('django_conneg.support.middleware.authenticate', mocked_authenticate_inactive)
    def testRequiredWithCorrectInactive(self):
        response = self.client.get('/login-required/',
                                   **basic_auth(test_username, test_password))
        self.assertEqual(response.status_code, FORBIDDEN)
