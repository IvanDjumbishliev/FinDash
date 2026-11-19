from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class BillaLeafletView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        return Response(
            {
                "response": [],
                "available": False,
                "notice": "Billa deals are not yet available.",
            }
        )
