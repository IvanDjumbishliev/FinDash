from api.views.stocks import StockSearchView, WatchlistView
from django.urls import path

from .views.deals import (
    FantasticoDealsView,
    KauflandDealsView,
    LidlDealsView,
)

from .views.spending_heatmap import ProfileTimezoneView, SpendingHeatmapDayView, SpendingHeatmapView
from .views.portfolio_analytics import PortfolioAnalyticsExportView, PortfolioAnalyticsView
from .views.portfolios import (
    PortfolioHoldingsView, PortfolioListView, PortfolioPerformanceView, PortfolioTradeView,
)
from .views.reports import FinancialReportPDFView, FinancialReportView
from .views.assistant import AssistantView, CopilotHistoryView, CopilotSettingsView
from .views.budget_recommendations import BudgetRecommendationApplyView, BudgetRecommendationView
from .views.forecast import CashFlowForecastView
from .views.forecast_scenarios import (
    CashFlowScenarioDetailView, CashFlowScenarioListView, CashFlowScenarioPreviewView,
)
from .views.budgets import BudgetDetailView, BudgetHistoryView, BudgetListView, BudgetOverviewView
from .views.grocery import (GroceryCatalogView, GroceryOptimizeView, GroceryShoppingListView, GroceryShoppingListDetailView)
from .views.leaflet_billa import BillaLeafletView
from .views.leaflet_kaufland import LeafletKauflandView
from .views.leaflet_lidl import LidlLeafletView
from .views.leaflet_user import LeafletUserView
from .views.news import NewsView
from .views.notifications import (
    NotificationDetailView, NotificationListView, NotificationMarkAllReadView, NotificationPreferencesView,
)
from .views.pdf_import import (
    StatementConfirmView,
    StatementHistoryView,
    StatementImportDetailView,
    StatementImportedTransactionsView,
    StatementUploadView,
    UploadBankStatementView,
)
from .views.statement_review import MerchantRuleDetailView, MerchantRuleListView
from .views.subscriptions import (
    SubscriptionDetailView,
    SubscriptionDetectView,
    SubscriptionListView,
    SubscriptionPlanningView,
    SubscriptionPreferencesView,
)
from .views.user_summary import UserSummaryView
from .views.views import (
    GetProfileView,
    TransactionDeleteView,
    TransactionListView,
    TransactionStatsView,
)

urlpatterns = [
    path("deals/lidl/", LidlDealsView.as_view()),
    path("deals/kaufland/", KauflandDealsView.as_view()),
    path("deals/fantastico/", FantasticoDealsView.as_view()),
    path("grocery/optimize/", GroceryOptimizeView.as_view(), name="grocery-optimize"),
    path("grocery/catalog/", GroceryCatalogView.as_view(), name="grocery-catalog"),
    path("grocery/lists/", GroceryShoppingListView.as_view(), name="grocery-lists"),
    path("grocery/lists/<int:pk>/", GroceryShoppingListDetailView.as_view(), name="grocery-list-detail"),
    path("transactions/", TransactionListView.as_view()),
    path(
        "transaction/<int:pk>/",
        TransactionDeleteView.as_view(),
        name="transaction-delete",
    ),
    path("bank-statement/", UploadBankStatementView.as_view()),
    path("bank-statement/preview/", StatementUploadView.as_view(), name="statement-preview"),
    path("bank-statement/imports/", StatementHistoryView.as_view(), name="statement-history"),
    path("bank-statement/rules/", MerchantRuleListView.as_view(), name="merchant-rules"),
    path("bank-statement/rules/<int:pk>/", MerchantRuleDetailView.as_view(), name="merchant-rule-detail"),
    path("bank-statement/imports/<uuid:pk>/", StatementImportDetailView.as_view(), name="statement-import"),
    path("bank-statement/imports/<uuid:pk>/transactions/", StatementImportedTransactionsView.as_view(), name="statement-imported-transactions"),
    path("bank-statement/imports/<uuid:pk>/confirm/", StatementConfirmView.as_view(), name="statement-confirm"),
    path("summary/", UserSummaryView.as_view()),
    path(
        "transaction-stats/", TransactionStatsView.as_view(), name="transaction-stats"
    ),
    path("leaflet/lidl/", LidlLeafletView.as_view()),
    path("leaflet/kaufland/", LeafletKauflandView.as_view()),
    path("leaflet/billa/", BillaLeafletView.as_view()),
    path("leaflet/user/", LeafletUserView.as_view()),
    path("user/profile/", GetProfileView.as_view()),
    path("user/profile/timezone/", ProfileTimezoneView.as_view(), name="profile-timezone"),
    path("analytics/spending-heatmap/", SpendingHeatmapView.as_view(), name="spending-heatmap"),
    path("analytics/spending-heatmap/day/", SpendingHeatmapDayView.as_view(), name="spending-heatmap-day"),
    path("chat/", AssistantView.as_view()),
    path("reports/", FinancialReportView.as_view(), name="financial-report"),
    path("forecast/cash-flow/", CashFlowForecastView.as_view(), name="cash-flow-forecast"),
    path("forecast/cash-flow/scenarios/", CashFlowScenarioListView.as_view(), name="cash-flow-scenarios"),
    path("forecast/cash-flow/scenarios/preview/", CashFlowScenarioPreviewView.as_view(), name="cash-flow-scenario-preview"),
    path("forecast/cash-flow/scenarios/<int:pk>/", CashFlowScenarioDetailView.as_view(), name="cash-flow-scenario-detail"),
    path("reports/pdf/", FinancialReportPDFView.as_view(), name="financial-report-pdf"),
    path("chat/settings/", CopilotSettingsView.as_view()),
    path("chat/history/", CopilotHistoryView.as_view()),
    path("news/", NewsView.as_view(), name="news"),
    path("notifications/", NotificationListView.as_view(), name="notifications"),
    path("notifications/<int:pk>/", NotificationDetailView.as_view(), name="notification-detail"),
    path("notifications/mark-all-read/", NotificationMarkAllReadView.as_view(), name="notification-mark-all-read"),
    path("notifications/preferences/", NotificationPreferencesView.as_view(), name="notification-preferences"),
    path("budgets/", BudgetListView.as_view(), name="budget-list"),
    path("budgets/overview/", BudgetOverviewView.as_view(), name="budget-overview"),
    path("budgets/history/", BudgetHistoryView.as_view(), name="budget-history"),
    path("budgets/recommendations/", BudgetRecommendationView.as_view(), name="budget-recommendations"),
    path("budgets/recommendations/apply/", BudgetRecommendationApplyView.as_view(), name="budget-recommendations-apply"),
    path("budgets/<int:pk>/", BudgetDetailView.as_view(), name="budget-detail"),
    path("subscriptions/", SubscriptionListView.as_view(), name="subscription-list"),
    path("subscriptions/detect/", SubscriptionDetectView.as_view(), name="subscription-detect"),
    path("subscriptions/planning/", SubscriptionPlanningView.as_view(), name="subscription-planning"),
    path("subscriptions/preferences/", SubscriptionPreferencesView.as_view(), name="subscription-preferences"),
    path("subscriptions/<int:pk>/", SubscriptionDetailView.as_view(), name="subscription-detail"),
    path("stocks/watchlist/", WatchlistView.as_view(), name="watchlist"),
    path("portfolios/", PortfolioListView.as_view(), name="portfolio-list"),
    path("portfolios/<int:pk>/holdings/", PortfolioHoldingsView.as_view(), name="portfolio-holdings"),
    path("portfolios/<int:pk>/trades/", PortfolioTradeView.as_view(), name="portfolio-trades"),
    path("portfolios/<int:pk>/performance/", PortfolioPerformanceView.as_view(), name="portfolio-performance"),
    path("portfolios/<int:pk>/analytics/", PortfolioAnalyticsView.as_view(), name="portfolio-analytics"),
    path("portfolios/<int:pk>/analytics/export/", PortfolioAnalyticsExportView.as_view(), name="portfolio-analytics-export"),
    path("stocks/search/", StockSearchView.as_view(), name="search_stocks"),
]
