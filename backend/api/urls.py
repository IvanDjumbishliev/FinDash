from api.views.stocks import StockSearchView, WatchlistView
from django.urls import path

from .views.deals import (
    FantasticoDealsView,
    KauflandDealsView,
    LidlDealsView,
)

from .views.spending_heatmap import ProfileTimezoneView, SpendingHeatmapView
from .views.assistant import AssistantView
from .views.budget_recommendations import BudgetRecommendationApplyView, BudgetRecommendationView
from .views.budgets import BudgetDetailView, BudgetHistoryView, BudgetListView, BudgetOverviewView
from .views.leaflet_billa import BillaLeafletView
from .views.leaflet_kaufland import LeafletKauflandView
from .views.leaflet_lidl import LidlLeafletView
from .views.leaflet_user import LeafletUserView
from .views.news import NewsView
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
    path("chat/", AssistantView.as_view()),
    path("news/", NewsView.as_view(), name="news"),
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
    path("stocks/search/", StockSearchView.as_view(), name="search_stocks"),
]
