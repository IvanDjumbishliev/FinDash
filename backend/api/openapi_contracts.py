"""OpenAPI metadata for custom APIViews and nonstandard request or response shapes."""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, inline_serializer
from rest_framework import serializers

from api.serializers import BudgetSerializer
from api.views.assistant import CopilotRequestSerializer, CopilotSettingsSerializer
from api.views.budget_recommendations import ApprovalRequest, RecommendationRequest
from api.views.forecast import ForecastQuery
from api.views.forecast_scenarios import SavedScenarioInput, SavedScenarioOutput, ScenarioPreviewInput
from api.views.goal_scenarios import PreviewInput, SavedGoalScenarioInput, SavedGoalScenarioOutput
from api.views.goals import ContributionInput, ContributionOutput, GoalSerializer, ProjectionOutput, ProjectionQuery
from api.views.grocery import GroceryBasketInput, GroceryCatalogQuery, ShoppingListInput, ShoppingListOutput
from api.views.legacy_deals import LeafletSearchInput
from api.views.notifications import NotificationFilters, NotificationOutput, NotificationPatch, PreferencesPatch
from api.views.portfolio_analytics import AnalyticsQuery
from api.views.portfolios import PortfolioSerializer, VirtualTradeSerializer
from api.views.reports import ReportExportInput, ReportInput
from api.views.spending_heatmap import HeatmapDaySerializer, HeatmapQuerySerializer, ProfileTimezoneSerializer
from api.views.statement_review import ConfirmationSerializer, ReviewRequestSerializer

OBJECT = OpenApiTypes.OBJECT
PERIOD = OpenApiParameter("period", str, description="Calendar month in YYYY-MM format.")
PAGING = [
    OpenApiParameter("limit", int, description="Maximum records in the page."),
    OpenApiParameter("offset", int, description="Number of records to skip."),
]


def document(component_name, *, many=False, **fields):
    return inline_serializer(component_name, fields, many=many)


def page(name, row, **fields):
    return document(
        name, count=serializers.IntegerField(),
        next=serializers.URLField(allow_null=True), previous=serializers.URLField(allow_null=True),
        results=row, **fields,
    )


STATEMENT_UPLOAD = document(
    "StatementUpload",
    file=serializers.FileField(), mapping=serializers.CharField(required=False, help_text="JSON object with CSV column mappings."),
    default_currency=serializers.CharField(required=False), date_order=serializers.ChoiceField(["DMY", "MDY"], required=False),
    allow_external_processing=serializers.BooleanField(required=False), allow_ai_categorization=serializers.BooleanField(required=False),
)
STATEMENT = document(
    "StatementImportResponse",
    id=serializers.UUIDField(), file_format=serializers.CharField(), status=serializers.CharField(),
    row_count=serializers.IntegerField(), imported_count=serializers.IntegerField(),
    revision=serializers.IntegerField(), created_at=serializers.DateTimeField(),
    updated_at=serializers.DateTimeField(), expires_at=serializers.DateTimeField(),
    errors=serializers.ListField(child=serializers.DictField()),
    transactions=serializers.ListField(child=serializers.DictField(), required=False),
    columns=serializers.ListField(child=serializers.CharField(), required=False),
    mapping=serializers.DictField(required=False), ai_status=serializers.CharField(required=False),
)
BUDGET_PERIODS = document("BudgetPeriod", many=True, period=serializers.DateField(), budgets=BudgetSerializer(many=True))
AUTH_PAIR = document("AuthPair", access=serializers.CharField(), refresh=serializers.CharField())

OPERATIONS = {
    "CreateUserView": {"POST": {"response": {201: document(
        "RegistrationResponse", id=serializers.IntegerField(), username=serializers.CharField(),
        access=serializers.CharField(), refresh=serializers.CharField(),
    )}}},
    "LoginView": {"POST": {"response": AUTH_PAIR}},
    "RefreshView": {"POST": {"response": AUTH_PAIR}},
    "LogoutView": {"POST": {"response": {200: None}}},
    "BudgetListView": {"GET": {"parameters": [PERIOD]}},
    "BudgetOverviewView": {"GET": {"parameters": [PERIOD], "response": document(
        "BudgetOverview", period=serializers.DateField(), overall=BudgetSerializer(allow_null=True),
        budgets=BudgetSerializer(many=True),
    )}},
    "BudgetHistoryView": {"GET": {"response": document("BudgetHistory", periods=BUDGET_PERIODS)}},
    "BudgetRecommendationView": {"POST": {"request": RecommendationRequest, "response": OBJECT}},
    "BudgetRecommendationApplyView": {"POST": {"request": ApprovalRequest, "response": OBJECT}},
    "StatementUploadView": {"POST": {"request": {"multipart/form-data": STATEMENT_UPLOAD},
                                    "response": {200: STATEMENT, 201: STATEMENT, 422: STATEMENT}}},
    "UploadBankStatementView": {"POST": {"request": {"multipart/form-data": STATEMENT_UPLOAD}, "response": {201: OBJECT}}},
    "StatementHistoryView": {"GET": {
        "operation_id": "statement_import_history", "parameters": PAGING,
        "response": page("StatementHistoryPage", STATEMENT.__class__(many=True)),
    }},
    "StatementImportDetailView": {
        "GET": {"response": STATEMENT}, "PATCH": {"request": ReviewRequestSerializer, "response": STATEMENT},
        "DELETE": {"response": {200: STATEMENT}},
    },
    "StatementConfirmView": {"POST": {"request": ConfirmationSerializer, "response": {200: STATEMENT, 409: STATEMENT}}},
    "StatementImportedTransactionsView": {"GET": {
        "parameters": PAGING,
        "response": page("ImportedTransactionsPage", serializers.ListField(child=serializers.DictField())),
    }},
    "GroceryOptimizeView": {"POST": {"request": GroceryBasketInput, "response": {200: OBJECT}}},
    "GroceryCatalogView": {"GET": {
        "parameters": [GroceryCatalogQuery],
        "response": document("GroceryCatalogOffer", many=True,
                             id=serializers.IntegerField(), name=serializers.CharField(), brand=serializers.CharField(),
                             retailer=serializers.CharField(), quantity=serializers.CharField(), unit=serializers.CharField(),
                             image_url=serializers.CharField(), price=serializers.CharField(), currency=serializers.CharField(),
                             expires_on=serializers.DateField(allow_null=True),
                             last_successful_update=serializers.DateTimeField()),
    }},
    "GroceryShoppingListView": {
        "GET": {"response": ShoppingListOutput(many=True)},
        "POST": {"request": ShoppingListInput, "response": {201: ShoppingListOutput}},
    },
    "GoalListView": {"GET": {"operation_id": "goals_list", "response": GoalSerializer(many=True)},
                     "POST": {"request": GoalSerializer, "response": {201: GoalSerializer}}},
    "GoalDetailView": {"GET": {"response": GoalSerializer}, "PATCH": {"request": GoalSerializer, "response": GoalSerializer}},
    "GoalContributionView": {
        "GET": {"parameters": PAGING, "response": page("ContributionPage", ContributionOutput(many=True))},
        "POST": {"request": ContributionInput, "response": {200: OBJECT, 201: OBJECT}},
    },
    "GoalProjectionView": {"GET": {"parameters": [ProjectionQuery], "response": ProjectionOutput}},
    "GoalScenarioListView": {
        "GET": {"response": SavedGoalScenarioOutput(many=True)},
        "POST": {"request": SavedGoalScenarioInput, "response": {201: SavedGoalScenarioOutput}},
    },
    "GoalScenarioPreviewView": {"POST": {"request": PreviewInput, "response": {200: OBJECT}}},
    "NotificationListView": {"GET": {
        "parameters": [NotificationFilters, *PAGING],
        "response": page("NotificationPage", NotificationOutput(many=True), unread_count=serializers.IntegerField()),
    }},
    "NotificationDetailView": {"PATCH": {"request": NotificationPatch, "response": NotificationOutput}},
    "NotificationPreferencesView": {"GET": {"response": PreferencesPatch},
                                    "PATCH": {"request": PreferencesPatch, "response": PreferencesPatch}},
    "NotificationMarkAllReadView": {"POST": {"request": None, "response": {200: document("NotificationUpdateCount", updated=serializers.IntegerField())}}},
    "AssistantView": {"POST": {"request": CopilotRequestSerializer, "response": {201: OBJECT}}},
    "CopilotSettingsView": {"GET": {"response": CopilotSettingsSerializer},
                            "PATCH": {"request": CopilotSettingsSerializer, "response": CopilotSettingsSerializer}},
    "FinancialReportView": {"POST": {"request": ReportInput, "response": {200: document(
        "FinancialReportPreview", report=serializers.DictField(), export_token=serializers.CharField(),
    )}}},
    "FinancialReportPDFView": {"POST": {"request": ReportExportInput, "response": {(200, "application/pdf"): OpenApiTypes.BINARY}}},
    "CashFlowForecastView": {"GET": {"parameters": [ForecastQuery, OpenApiParameter("X-Starting-Balance", str, location="header")]}},
    "CashFlowScenarioPreviewView": {"POST": {"request": ScenarioPreviewInput, "response": {200: OBJECT}}},
    "CashFlowScenarioListView": {"GET": {"response": SavedScenarioOutput(many=True)},
                                "POST": {"request": SavedScenarioInput, "response": {201: SavedScenarioOutput}}},
    "PortfolioListView": {"GET": {"response": PortfolioSerializer(many=True)},
                          "POST": {"request": PortfolioSerializer, "response": {201: PortfolioSerializer}}},
    "PortfolioTradeView": {"GET": {"parameters": PAGING, "response": page("VirtualTradePage", VirtualTradeSerializer(many=True))},
                           "POST": {"request": VirtualTradeSerializer, "response": {200: OBJECT, 201: OBJECT}}},
    "PortfolioAnalyticsView": {"GET": {"parameters": [AnalyticsQuery]}},
    "PortfolioAnalyticsExportView": {"GET": {"parameters": [AnalyticsQuery], "response": {(200, "text/csv"): str}}},
    "SpendingHeatmapView": {"GET": {"parameters": [HeatmapQuerySerializer]}},
    "SpendingHeatmapDayView": {"GET": {"parameters": [HeatmapDaySerializer]}},
    "ProfileTimezoneView": {"GET": {"response": ProfileTimezoneSerializer},
                            "PATCH": {"request": ProfileTimezoneSerializer, "response": ProfileTimezoneSerializer}},
    "GetProfileView": {"GET": {"response": str}},
    "StockSearchView": {"GET": {
        "parameters": [OpenApiParameter("query", str, required=True)],
        "response": document("StockSearchResult", many=True, symbol=serializers.CharField(), name=serializers.CharField()),
    }},
    "WatchlistView": {"GET": {"parameters": [OpenApiParameter("include_history", bool)]},
                      "POST": {"request": document("WatchlistAddition", symbol=serializers.CharField(max_length=10)),
                               "response": {200: OBJECT}}},
    "LegacyLeafletSearchView": {"POST": {"request": LeafletSearchInput, "response": {201: OBJECT}}},
    "SubscriptionDetectView": {"POST": {"request": None, "response": {200: OBJECT}}},
    "SubscriptionPlanningView": {"GET": {"response": OBJECT}},
}

OPERATIONS["TransactionStatsView"] = {"GET": {
    "response": document("ExpenseCategoryTotal", many=True, category=serializers.CharField(), amount=serializers.FloatField()),
}}
OPERATIONS["UserSummaryView"] = {"GET": {
    "parameters": [OpenApiParameter("from-date", OpenApiTypes.DATE)],
    "response": document("SummaryInsight", many=True, title=serializers.CharField(), description=serializers.CharField()),
}}
ADVERTISED_DEALS = document(
    "AdvertisedDeal", many=True, name=serializers.CharField(), price=serializers.CharField(),
    image_url=serializers.CharField(required=False, allow_null=True),
    price_note=serializers.CharField(required=False),
    discount_percent=serializers.IntegerField(required=False, allow_null=True),
    store=serializers.CharField(required=False),
)
for name in ("LidlDealsView", "KauflandDealsView", "FantasticoDealsView"):
    OPERATIONS[name] = {"GET": {"response": ADVERTISED_DEALS}}
