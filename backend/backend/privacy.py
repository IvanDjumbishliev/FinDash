import json
import logging


class PrivateAPIResponses:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path_info.startswith("/api/"):
            response["Cache-Control"] = "no-store"
        return response


class RedactRequestLog(logging.Filter):
    """Keep production request errors useful without logging query or exception data."""

    def filter(self, record):
        record.msg = "HTTP request failed (status %s)"
        record.args = (getattr(record, "status_code", "unknown"),)
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        record.__dict__.pop("request", None)
        return True


class ThrottleRedisSerializer:
    """The shared cache stores only bounded rate-limit histories."""

    @staticmethod
    def dumps(history):
        return json.dumps(history, allow_nan=False)

    @staticmethod
    def loads(data):
        if len(data) > 16_384:
            return []
        try:
            history = json.loads(data)
        except (ValueError, RecursionError):
            return []
        if not isinstance(history, list) or not all(type(item) in (int, float) and 0 <= item < 10**12 for item in history):
            return []
        return history
