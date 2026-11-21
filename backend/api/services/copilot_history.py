from django.core import signing
from django.db import transaction

from api.models import CopilotPreferences

CONTEXT_TURNS = 4
SAVED_TURNS = 24
TOKEN_AGE = 3600
TOKEN_SALT = "findash.copilot.context.v1"


class StaleConversation(Exception):
    pass


def preferences_for(owner):
    return CopilotPreferences.objects.filter(owner=owner).first() or CopilotPreferences(owner=owner)


def public_preferences(preferences):
    return {
        "sharing_enabled": preferences.sharing_enabled,
        "history_enabled": preferences.history_enabled,
    }


def update_preferences(owner, changes, *, clear=False):
    with transaction.atomic():
        preferences, _ = CopilotPreferences.objects.select_for_update().get_or_create(owner=owner)
        changed = any(getattr(preferences, key) != value for key, value in changes.items())
        if clear or changed:
            for key, value in changes.items():
                setattr(preferences, key, value)
            if clear or not preferences.history_enabled:
                preferences.history = []
            preferences.revision += 1
            preferences.save(update_fields=("sharing_enabled", "history_enabled", "history", "revision"))
        return preferences


def context_from(owner, preferences, token):
    if preferences.history_enabled:
        if token:
            raise StaleConversation
        return [
            context_turn(turn["prompt"], turn["response"])
            for turn in preferences.history[-CONTEXT_TURNS:]
        ]
    if not token:
        return []
    try:
        context = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_AGE)
    except signing.BadSignature as error:
        raise StaleConversation from error
    if context["owner"] != owner.pk or context["revision"] != preferences.revision:
        raise StaleConversation
    return context["turns"]


def context_turn(prompt, result):
    # Reuse the user's question and inferred dates. Keep financial results local.
    return {"prompt": prompt[:500], "date_ranges": result["date_ranges"]}


def complete_turn(owner, preferences, prior, prompt, result):
    if preferences.history_enabled:
        history = [*preferences.history, {"prompt": prompt, "response": result}][-SAVED_TURNS:]
        updated = CopilotPreferences.objects.filter(
            owner=owner, revision=preferences.revision, history_enabled=True, sharing_enabled=True,
        ).update(history=history, revision=preferences.revision + 1)
        if not updated:
            raise StaleConversation
        return None
    if preferences_for(owner).revision != preferences.revision:
        raise StaleConversation
    turns = [*prior, context_turn(prompt, result)][-CONTEXT_TURNS:]
    return signing.dumps(
        {"owner": owner.pk, "revision": preferences.revision, "turns": turns},
        salt=TOKEN_SALT, compress=True,
    )
