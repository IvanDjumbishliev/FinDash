import io
import json
from django.conf import settings
from rest_framework import status
from .client import client
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.request import Request
from ..models import Transaction


transactions_schema = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "The transaction amount"},
            "timestamp": {
                "type": "string",
                # RFC 3339 - standart format for date string
                "description": "The transaction date and time RFC: 3339",
            },
            "category": {
                "type": "string",
                "enum": [
                    "business services",
                    "shopping",
                    "entertainment",
                    "groceries",
                    "eating out",
                    "bills",
                    "transport",
                    "health",
                    "travel",
                    "finance",
                    "general",
                ],
                "description": "The transaction category",
            },
            "particulars": {
                "type": "string",
                "description": "Additional details about the transaction",
            },
            "currency": {
                "type": "string",
                "description": "Currency of the transaction (3-letter code)",
            },
        },
        "required": ["amount", "timestamp", "category", "particulars", "currency"],
        # "additionalProperties": False,
    },
}


class UploadBankStatementView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, *args, **kwargs):
        if not settings.API_KEY:
            return Response(
                {
                    "error": (
                        "AI features are not configured. Add API_KEY to backend/.env"
                    )
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if "file" not in request.FILES:
            return Response({"error": "No file uploaded"}, status=400)

        uploaded_file = request.FILES["file"]

        if not uploaded_file.name.lower().endswith(".pdf"):
            return Response({"error": "Uploaded file is not a PDF"}, status=400)

        file_bytes = uploaded_file.read()

        try:
            ai_uploaded_file = client.files.upload(
                file=(io.BytesIO(file_bytes)),
                config={"mime_type": "application/pdf"},
            )

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    ai_uploaded_file,
                    "In the PDF is a bank statement. Extract the transactions exactly as described.",
                    "For debit transactions use negative amounts and for credit transactions use positive amounts.",
                ],
                config={
                    "response_mime_type": "application/json",
                    "response_schema": transactions_schema,
                },
            )
            parsed_transactions = json.loads(response.text)
            if not isinstance(parsed_transactions, list):
                raise ValueError("The AI response was not a transaction array.")

            Transaction.objects.bulk_create(
                [
                    Transaction(
                        amount=transaction["amount"],
                        timestamp=transaction["timestamp"],
                        category=transaction["category"],
                        particulars=transaction["particulars"],
                        currency=transaction.get("currency", "USD"),
                        user=request.user,
                    )
                    for transaction in parsed_transactions
                ]
            )
        except Exception:
            return Response(
                {
                    "error": (
                        "The bank statement could not be parsed. "
                        "Check the PDF or try again later."
                    )
                },
                status=502,
            )

        return Response({"response": parsed_transactions}, status=201)
