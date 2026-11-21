from django.conf import settings
from django.db import DatabaseError
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from api.services.copilot import CopilotUnavailable, answer_question
from api.services.copilot_history import (
    StaleConversation, complete_turn, context_from, preferences_for, public_preferences, update_preferences,
)
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


    context_token = serializers.CharField(required=False, max_length=20000)


class StrictBooleanField(serializers.BooleanField):
    def to_internal_value(self, data):
        if type(data) is not bool:
            self.fail("invalid", input=data)
        return data


class CopilotSettingsSerializer(serializers.Serializer):
    sharing_enabled = StrictBooleanField(required=False)
    history_enabled = StrictBooleanField(required=False)


class PrivateCopilotView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class CopilotSettingsView(PrivateCopilotView):
    def get(self, request):
        return Response(public_preferences(preferences_for(request.user)))

    def patch(self, request):
        serializer = CopilotSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        preferences = update_preferences(request.user, serializer.validated_data)
        return Response(public_preferences(preferences))


class CopilotHistoryView(PrivateCopilotView):
    def get(self, request):
        preferences = preferences_for(request.user)
        return Response({"turns": preferences.history if preferences.history_enabled else []})

    def delete(self, request):
        update_preferences(request.user, {}, clear=True)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SharingDisabled(Exception):
    pass


def sharing_disabled():
    return Response({"code": "sharing_disabled", "error": "AI data sharing is off in Copilot settings."}, status=403)


PROVIDER_ERRORS = {
    "rate_limited": (429, "Gemini is rate limited. Wait a moment and try again."),
    "timeout": (504, "Gemini timed out. Try again."),
    "invalid_response": (502, "Gemini returned an unusable response. Try rephrasing your question."),
    "unavailable": (503, "The assistant is temporarily unavailable. Please try again."),
}


class AssistantView(PrivateCopilotView):
    throttle_classes = [CopilotThrottle]

    def post(self, request):
        if not settings.API_KEY:
            return Response(
                {"code": "not_configured", "error": "AI features are not configured. Add API_KEY to backend/.env"},
                status=503,
            )

        serializer = CopilotRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("consent") is not True:
            return Response(
                {"code": "consent_required", "error": "Consent is required to send your question and conversation context to Gemini."},
                status=403,
            )

        try:
            preferences = preferences_for(request.user)
            if not preferences.sharing_enabled:
                return sharing_disabled()
            context = context_from(request.user, preferences, data.get("context_token"))

            def authorize():
                current = preferences_for(request.user)
                if not current.sharing_enabled:
                    raise SharingDisabled
                if current.revision != preferences.revision:
                    raise StaleConversation

            result = answer_question(
                client, settings.COPILOT_GEMINI_MODEL, request.user, data["prompt"], context, authorize,
            )
            token = complete_turn(request.user, preferences, context, data["prompt"], result)
        except SharingDisabled:
            return sharing_disabled()
        except StaleConversation:
            return Response(
                {"code": "stale_context", "error": "The conversation changed or expired. Refresh it and try again."},
                status=409,
            )
        except InvalidToolCall:
            return Response(
                {"code": "invalid_tool", "error": "The assistant requested an invalid tool or arguments. Please rephrase and retry."},
                status=502,
            )
        except CopilotUnavailable as error:
            status_code, message = PROVIDER_ERRORS[error.code]
            return Response({"code": error.code, "error": message}, status=status_code)
        except DatabaseError:
            return Response(
                {"code": "records_unavailable", "error": "Financial records are temporarily unavailable. Please try again."},
                status=503,
            )

        return Response({**result, "context_token": token}, status=status.HTTP_201_CREATED)
