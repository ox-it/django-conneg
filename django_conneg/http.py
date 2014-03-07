from __future__ import unicode_literals

import re

from django.http import HttpResponseRedirect

class HttpResponseSeeOther(HttpResponseRedirect):
    status_code = 303

class HttpResponseTemporaryRedirect(HttpResponseRedirect):
    status_code = 307

class HttpResponseCreated(HttpResponseRedirect):
    status_code = 201

class HttpError(Exception):
    def __init__(self, status_code=None, message=None):
        if status_code:
            self.status_code = status_code
        super(HttpError, self).__init__(message)

class HttpNotAcceptable(HttpError):
    status_code = 406
    def __init__(self, tried_mimetypes):
        self.tried_mimetypes = tried_mimetypes

class HttpBadRequest(HttpError):
    status_code = 400

class HttpConflict(HttpError):
    status_code = 409

class HttpGone(HttpError):
    status_code = 410

class MediaType(object):
    """
    Represents a parsed internet media type.
    """

    _MEDIA_TYPE_RE = re.compile(r'(\*/\*)|(?P<type>[^/]+)/(\*|((?P<subsubtype>[^+]+)\+)?(?P<subtype>.+))')
    def __init__(self, value, priority=0):
        value = str(value).strip()
        media_type = value.split(';')
        media_type, params = media_type[0].strip(), dict((i.strip() for i in p.split('=', 1)) for p in media_type[1:] if '=' in p)

        mt = self._MEDIA_TYPE_RE.match(media_type)
        if not mt:
            raise ValueError("Not a correctly formatted internet media type (%r)" % media_type)
        mt = mt.groupdict()

        try:
            self.quality = float(params.pop('q', 1))
        except ValueError:
            self.quality = 1

        self.type = mt.get('type'), mt.get('subtype'), mt.get('subsubtype')
        self.specifity = len([t for t in self.type if t])
        self.params = params
        self.value = value
        self.priority = priority

    def __str__(self):
        return self.value

    def __gt__(self, other):
        if self.quality != other.quality:
            return self.quality > other.quality

        if self.specifity != other.specifity:
            return self.specifity > other.specifity

        for key in other.params:
            if self.params.get(key) != other.params[key]:
                return False

        return len(self.params) > len(other.params)

    def __lt__(self, other):
        return other > self

    def __eq__(self, other):
        return self.quality == other.quality and self.type == other.type and self.params == other.params
    def __hash__(self):
        return hash(hash(self.quality) + hash(self.type) + hash(tuple(sorted(self.params.items()))))
    def __ne__(self, other):
        return not self.__eq__(other)
    def equivalent(self, other):
        """
        Returns whether two MediaTypes have the same overall specifity.
        """
        return not (self > other or self < other)

    def __cmp__(self, other):
        if self > other:
            return 1
        elif self < other:
            return -1
        else:
            return 0

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.value)

    def provides(self, imt):
        """
        Returns True iff the self is at least as specific as other.

        Examples:
        application/xhtml+xml provides application/xml, application/*, */*
        text/html provides text/*, but not application/xhtml+xml or application/html
        """
        return self.type[:imt.specifity] == imt.type[:imt.specifity]

    @classmethod
    def resolve(cls, accept, available_renderers):
        """
        Resolves a list of accepted MediaTypes and available renderers to the preferred renderer.

        Call as MediaType.resolve([MediaType], [renderer]).
        """
        assert isinstance(available_renderers, tuple)
        accept = sorted(accept)

        renderers, seen = [], set()

        accept_groups = [[accept.pop()]]
        for imt in accept:
            if imt.equivalent(accept_groups[-1][0]):
                accept_groups[-1].append(imt)
            else:
                accept_groups.append([imt])

        for accept_group in accept_groups:
            for renderer in available_renderers:
                if renderer in seen:
                    continue
                for mimetype in renderer.mimetypes:
                    for imt in accept_group:
                        if mimetype.provides(imt):
                            renderers.append(renderer)
                            seen.add(renderer)
                            break

        return renderers

    @classmethod
    def parse_accept_header(cls, accept):
        media_types = []
        for media_type in accept.split(','):
            try:
                media_types.append(MediaType(media_type))
            except ValueError:
                pass
        return media_types
