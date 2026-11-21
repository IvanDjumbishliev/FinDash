"""Compatibility responses for the older leaflet routes, using public retailer data."""
import re
import unicodedata

from rest_framework import serializers
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from api.throttles import SensitiveEndpointThrottle

from .deals import scrape_kaufland, scrape_lidl

RETAILERS = {"lidl": scrape_lidl, "kaufland": scrape_kaufland}


def search_words(value):
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold())


def legacy_offers(retailer, terms=()):
    for offer in RETAILERS[retailer]():
        name = offer.get("name")
        if not name or not all(term in " ".join(search_words(name)) for term in terms):
            continue
        info = " - ".join(part for part in (name, offer.get("price")) if part)
        yield {"info": info, "discount": offer.get("discount_percent") or 0, "supermarket": retailer}


class LegacyLeafletView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [SensitiveEndpointThrottle]
    throttle_scope = "retailer"
    retailer = None

    def get(self, request):
        response = list(legacy_offers(self.retailer))
        data = {"response": response}
        if not response:
            data["notice"] = "Current retailer offers are unavailable."
        return Response(data)


class LeafletSearchInput(serializers.Serializer):
    prompt = serializers.CharField(min_length=2, max_length=50)


class LegacyLeafletSearchView(LegacyLeafletView):
    http_method_names = ["post", "options"]
    parser_classes = [JSONParser]

    def post(self, request):
        serializer = LeafletSearchInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        terms = search_words(serializer.validated_data["prompt"])
        if not terms:
            raise serializers.ValidationError({"prompt": "Enter a product name."})
        offers = [offer for retailer in RETAILERS for offer in legacy_offers(retailer, terms)]
        return Response({"response": offers[:10]}, status=201)
