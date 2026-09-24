"""Direct HTTP first, with configured proxy fallback on transport failures."""
import copy
import urllib.error
import urllib.parse
import urllib.request


class DirectFirst:
    def __init__(self, *handlers):
        self.direct = urllib.request.build_opener(urllib.request.ProxyHandler({}), *(copy.copy(h) for h in handlers))
        self.handlers = handlers

    def open(self, request, timeout=20):
        url = request.full_url if isinstance(request, urllib.request.Request) else request
        try:
            return self.direct.open(request, timeout=timeout)
        except (OSError, urllib.error.URLError) as error:
            if isinstance(error, urllib.error.HTTPError) and error.code < 500:
                raise
            parsed = urllib.parse.urlsplit(url)
            if not urllib.request.getproxies().get(parsed.scheme) or urllib.request.proxy_bypass(parsed.hostname):
                raise
        return urllib.request.build_opener(urllib.request.ProxyHandler(), *(copy.copy(h) for h in self.handlers)).open(request, timeout=timeout)


def urlopen(request, timeout=20):
    return DirectFirst().open(request, timeout=timeout)
