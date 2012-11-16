import base64
import httplib

from django.contrib.auth.models import User
from django.test import TestCase

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
    return {'HTTP_AUTHORIZATION': 'Basic ' + base64.b64encode(':'.join([username, password]))}

class BasicAuthTestCase(TestCase):
    def testOptionalWithout(self):
        response = self.client.get('/optional-auth/')
        self.assertEqual(response.status_code, httplib.OK)
        self.assertFalse(response.is_authenticated)

    @mock.patch('django_conneg.support.middleware.authenticate', mocked_authenticate)
    def testOptionalWithCorrect(self):
        response = self.client.get('/optional-auth/',
                                   **basic_auth(test_username, test_password))
        self.assertEqual(response.status_code, httplib.OK)
        self.assertTrue(response.is_authenticated)

    @mock.patch('django_conneg.support.middleware.authenticate', mocked_authenticate)
    def testOptionalWithIncorrect(self):
        response = self.client.get('/optional-auth/',
                                   **basic_auth(test_username, 'not-the-password'))
        self.assertEqual(response.status_code, httplib.UNAUTHORIZED)
        self.assertEqual(response['WWW-Authenticate'], 'Basic realm="restricted"')

    def testRequiredWithoutHTML(self):
        response = self.client.get('/login-required/', HTTP_ACCEPT='text/html')
        self.assertEqual(response.status_code, httplib.FOUND)
        self.assertEqual(response['Location'],
                         'http://testserver/login/?next=/login-required/')

    def testRequiredWithoutJSON(self):
        response = self.client.get('/login-required/', HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, httplib.UNAUTHORIZED)
        self.assertEqual(response['WWW-Authenticate'], 'Basic realm="restricted"')

    @mock.patch('django_conneg.support.middleware.authenticate', mocked_authenticate)
    def testRequiredWithCorrect(self):
        response = self.client.get('/login-required/',
                                   **basic_auth(test_username, test_password))
        self.assertEqual(response.status_code, httplib.OK)
        self.assertTrue(response.is_authenticated)

    @mock.patch('django_conneg.support.middleware.authenticate', mocked_authenticate_inactive)
    def testRequiredWithCorrectInactive(self):
        response = self.client.get('/login-required/',
                                   **basic_auth(test_username, test_password))
        self.assertEqual(response.status_code, httplib.FORBIDDEN)
