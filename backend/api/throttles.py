from django.core.cache import caches
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle


class ThrottleCache:
    @property
    def cache(self):
        return caches["throttles"]


class SensitiveEndpointThrottle(ThrottleCache, ScopedRateThrottle):
    pass


class AuthenticationThrottle(ThrottleCache, AnonRateThrottle):
    # Authentication views ignore bearer tokens, so all calls are counted by IP.
    scope = "authentication"


class CopilotThrottle(ThrottleCache, UserRateThrottle):
    scope = "copilot"
    rate = "12/min"
