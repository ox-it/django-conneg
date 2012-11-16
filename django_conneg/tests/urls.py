from django.conf.urls.defaults import patterns, url
from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django_conneg.views import HTMLView, JSONView

class OptionalAuthView(HTMLView, JSONView):
    _force_fallback_format = ('html', 'json')
    def get(self, request):
        response = self.render()
        response.is_authenticated = request.user.is_authenticated()
        return response

class LoginRequiredView(HTMLView, JSONView):
    _force_fallback_format = ('html', 'json')
    @method_decorator(login_required)
    def get(self, request):
        response = self.render()
        response.is_authenticated = request.user.is_authenticated()
        return response

urlpatterns = patterns('',
    url(r'^optional-auth/$', OptionalAuthView.as_view()),
    url(r'^login-required/$', LoginRequiredView.as_view()),
)