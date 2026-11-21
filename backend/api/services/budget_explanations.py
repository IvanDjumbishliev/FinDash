import json
import logging

from django.conf import settings

from api.views.client import client

logger = logging.getLogger(__name__)


def explain_recommendations(recommendations, *, consent):
    if consent is not True or not recommendations:
        return "not_requested"
    if not settings.API_KEY:
        return "not_configured"

    # Send allowlisted aggregate data. Raw transactions, dates, budget IDs, and
    # account information are never included in this request.
    aggregates = [
        {
            "index": index,
            "category": item["category"],
            "currency": item["currency"],
            "suggested_amount": item["suggested_amount"],
            "statistics": {
                key: item["statistics"][key]
                for key in ("months_analyzed", "average", "standard_deviation", "baseline", "variability_buffer", "trend")
            },
        }
        for index, item in enumerate(recommendations)
    ]
    try:
        response = client.models.generate_content(
            model=settings.BUDGET_GEMINI_MODEL,
            contents=[
                'Explain each supplied budget estimate in one or two short sentences. Use only these statistics. '
                'Do not change the estimates, invent reasons or values, or give investment advice. '
                'Return a JSON array with one {"index": integer, "explanation": string} per input.',
                json.dumps(aggregates),
            ],
            config={"response_mime_type": "application/json", "http_options": {"timeout": 12000}},
        )
        entries = json.loads(response.text)
        if not isinstance(entries, list) or len(entries) != len(recommendations):
            raise ValueError("Incomplete AI explanation")
        mapped = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Invalid AI explanation")
            index, explanation = entry.get("index"), entry.get("explanation")
            if (
                type(index) is not int or not 0 <= index < len(recommendations) or index in mapped
                or not isinstance(explanation, str) or not 1 <= len(explanation.strip()) <= 350
            ):
                raise ValueError("Invalid AI explanation")
            mapped[index] = explanation.strip()
    except Exception:
        # Provider failures must never prevent the deterministic recommendations.
        logger.warning("Gemini budget explanations were unavailable")
        return "unavailable"

    for index, recommendation in enumerate(recommendations):
        recommendation["ai_explanation"] = mapped[index]
    return "used"
