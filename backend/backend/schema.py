from drf_spectacular.openapi import AutoSchema
from drf_spectacular.types import OpenApiTypes


class FinDashSchema(AutoSchema):
    """Use the documented contract for endpoints that build their responses manually."""

    @property
    def contract(self):
        from api.openapi_contracts import OPERATIONS

        return OPERATIONS.get(type(self.view).__name__, {}).get(self.method, {})

    def _get_serializer(self):
        # Hand-written APIViews may have no serializer for their computed response.
        if not any(hasattr(self.view, name) for name in ("serializer_class", "get_serializer", "get_serializer_class")):
            return None
        return super()._get_serializer()

    def get_request_serializer(self):
        if "request" in self.contract:
            return self.contract["request"]
        return super().get_request_serializer() or OpenApiTypes.OBJECT

    def get_response_serializers(self):
        if "response" in self.contract:
            return self.contract["response"]
        return super().get_response_serializers() or (None if self.method == "DELETE" else OpenApiTypes.OBJECT)

    def get_override_parameters(self):
        return self.contract.get("parameters", [])

    def get_operation_id(self):
        return self.contract.get("operation_id") or super().get_operation_id()

    def _get_paginator(self):
        # This view deliberately returns all matching budgets.
        if type(self.view).__name__ == "BudgetListView":
            return None
        return super()._get_paginator()
