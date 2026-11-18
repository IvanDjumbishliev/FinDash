from google import genai
from django.conf import settings


class LazyGenAIClient:
    def __init__(self):
        self._client = None

    def __getattr__(self, name):
        if self._client is None:
            if not settings.API_KEY:
                raise RuntimeError(
                    "API_KEY is not configured. Set it in backend/.env to use AI features."
                )
            self._client = genai.Client(api_key=settings.API_KEY)
        return getattr(self._client, name)


client = LazyGenAIClient()
