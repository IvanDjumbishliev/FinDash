from django.conf import settings
from django.db import DatabaseError
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from api.services.copilot import CopilotUnavailable, answer_question
from api.services.copilot_tools import InvalidToolCall

from .client import client


class CopilotThrottle(UserRateThrottle):
    scope = "copilot"
    rate = "12/min"


class PromptField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class CopilotRequestSerializer(serializers.Serializer):
    prompt = PromptField(max_length=2000)
    consent = serializers.JSONField(required=False, allow_null=True)


class AssistantView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [CopilotThrottle]
    parser_classes = [JSONParser]

    def post(self, request):
        if not settings.API_KEY:
            return Response(
                {"error": "AI features are not configured. Add API_KEY to backend/.env"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = CopilotRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("consent") is not True:
            return Response(
                {"error": "Consent is required to send your prompt and relevant financial data to Gemini."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            answer = answer_question(client, settings.COPILOT_GEMINI_MODEL, request.user, data["prompt"])
        except InvalidToolCall:
            return Response(
                {"error": "The assistant requested an invalid tool or arguments. Please rephrase and retry."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except CopilotUnavailable as error:
            return Response(
                {"error": "The assistant is temporarily unavailable. Please try again."},
                status=status.HTTP_429_TOO_MANY_REQUESTS if error.rate_limited else status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except DatabaseError:
            return Response(
                {"error": "Financial records are temporarily unavailable. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(answer, status=status.HTTP_201_CREATED, headers={"Cache-Control": "no-store"})
