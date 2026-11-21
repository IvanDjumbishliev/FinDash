import json
from decimal import Decimal

from django.conf import settings

from api.services.copilot_history import preferences_for
from api.views.client import client

AI_NOTE = "AI-generated interpretation for information only. It is not professional financial advice."


def trend(value):
    if value is None:
        return "unavailable"
    amount = Decimal(value)
    return "positive" if amount > 0 else "negative" if amount < 0 else "flat"


def explain_report(owner, report, *, consent):
    status = "not_requested"
    if consent is True:
        if not preferences_for(owner).sharing_enabled:
            status = "sharing_disabled"
        elif not report["activity"]["transaction_count"]:
            status = "insufficient_data"
        elif not settings.API_KEY:
            status = "not_configured"
        else:
            return request_explanation(report)
    return {"status": status, "text": None}


def request_explanation(report):
    # Do not send amounts, merchants, dates, transaction details, or identifiers.
    signals = {
        "cash_flow_sign": trend(report["activity"]["net_cash_flow"]),
        "net_expense_change_sign": trend(report["comparison"]["change"]),
        "leading_expense_categories": [
            row["category"] for row in report["categories"]
            if Decimal(row["net_expenses"]) > 0
        ][:3],
        "any_budget_over_limit": any(Decimal(row["remaining"]) < 0 for row in report["budgets"]),
    }
    try:
        response = client.models.generate_content(
            model=settings.COPILOT_GEMINI_MODEL,
            contents=json.dumps(signals),
            config={
                "system_instruction": (
                    "Explain the supplied qualitative financial signals in at most two short sentences. "
                    "Discuss only the supplied directions and categories. Do not add numbers, infer causes, "
                    "make predictions, or present professional financial advice. Return only a JSON object "
                    'with a string property named "explanation".'
                ),
                "response_mime_type": "application/json",
                "max_output_tokens": 300,
                "http_options": {"timeout": 5000},
            },
        )
        entry = json.loads(response.text)
        text = entry.get("explanation") if isinstance(entry, dict) else None
        if not isinstance(text, str):
            raise ValueError("Invalid report commentary type")
        text = " ".join(text.split())
        if not 1 <= len(text) <= 400 or not text.isprintable() or any(char.isnumeric() for char in text):
            raise ValueError("Invalid report commentary")
    except Exception:
        # Reporting always succeeds independently of third-party availability and output.
        return {"status": "unavailable", "text": None}
    return {"status": "used", "text": text, "notice": AI_NOTE}
