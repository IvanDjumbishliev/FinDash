from unittest import TextTestResult

from django.conf import settings
from django.core.cache import caches
from django.test import override_settings
from django.test.runner import DiscoverRunner


class IsolatedThrottleTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self.throttle_settings = override_settings(CACHES={
            **settings.CACHES,
            "throttles": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "findash-test-throttles",
            },
        })
        self.throttle_settings.enable()

    def teardown_test_environment(self, **kwargs):
        self.throttle_settings.disable()
        super().teardown_test_environment(**kwargs)

    def get_resultclass(self):
        base = super().get_resultclass() or TextTestResult

        class IsolatedResult(base):
            def startTest(self, test):
                caches["throttles"].clear()
                super().startTest(test)

        return IsolatedResult
