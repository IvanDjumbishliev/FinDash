from django.db import models
from django.contrib.auth.models import User
import datetime
from uuid import uuid4


def get_current_time():
    return datetime.datetime.now()


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    timezone = models.CharField(max_length=255, default="UTC")
    budget = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="USD")

    def __str__(self):
        return f"{self.user.username}'s profile"


class Transaction(models.Model):
    class Category(models.TextChoices):
        BUSINESS_SERVICES = "business services"
        SHOPPING = "shopping"
        ENTERTAINMENT = "entertainment"
        GROCERIES = "groceries"
        EATING_OUT = "eating out"
        BILLS = "bills"
        TRANSPORT = "transport"
        HEALTH = "health"
        TRAVEL = "travel"
        FINANCE = "finance"
        GENERAL = "general"

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    timestamp = models.DateTimeField(default=get_current_time)
    category = models.CharField(choices=Category, max_length=50)
    particulars = models.TextField(
        help_text="Description of the transaction, either the sender or collector"
    )
    currency = models.CharField(
        max_length=3, default="USD", help_text="Currency of the transaction"
    )

    merchant = models.CharField(max_length=255, blank=True)
    normalized_merchant = models.CharField(max_length=255, blank=True)
    source_normalized_merchant = models.CharField(max_length=255, blank=True)
    statement_reference = models.CharField(max_length=128, blank=True)
    statement_import = models.ForeignKey(
        "StatementImport", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="imported_transactions",
    )

    class Meta:
        indexes = [models.Index(fields=["user", "timestamp"], name="txn_user_timestamp_idx")]

    def __str__(self):
        return (
            f"{self.user.username} - {self.amount} - {self.category} - {self.timestamp}"
        )


class Stock(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    ticker = models.CharField(max_length=10)
    quantity = models.IntegerField()
    price_per_share = models.DecimalField(max_digits=10, decimal_places=2)
    purchase_date = models.DateTimeField(default=get_current_time)

    def __str__(self):
        return f"{self.user.username} - {self.ticker} - {self.quantity} shares at {self.price_per_share} each"


class Subscription(models.Model):
    class Frequency(models.TextChoices):
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        YEARLY = "yearly", "Yearly"

    class Status(models.TextChoices):
        CANDIDATE = "candidate", "Candidate"
        CONFIRMED = "confirmed", "Confirmed"

    class TrackingStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        CANCELED = "canceled", "Canceled"

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="subscriptions")
    merchant = models.CharField(max_length=255)
    normalized_merchant = models.CharField(max_length=255)
    estimated_amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    billing_frequency = models.CharField(max_length=9, choices=Frequency.choices)
    next_expected_payment = models.DateField()
    detection_confidence = models.DecimalField(max_digits=3, decimal_places=2)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.CANDIDATE)
    # Null preserves device-only tracking choices from Stage 2 until the user saves them.
    tracking_status = models.CharField(max_length=8, choices=TrackingStatus.choices, null=True, blank=True)
    billing_anchor_day = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["next_expected_payment", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "normalized_merchant", "currency", "billing_frequency"],
                name="unique_subscription_schedule",
            ),
        ]


class SubscriptionPreferences(models.Model):
    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name="subscription_preferences")
    renewal_reminders = models.BooleanField(default=False)
    reminder_lead_days = models.PositiveSmallIntegerField(default=3)
    monthly_summary = models.BooleanField(default=False)


def default_budget_thresholds():
    return [50, 80, 100]


class Budget(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="budgets")
    category = models.CharField(max_length=50, choices=Transaction.Category.choices, null=True, blank=True)
    period = models.DateField(help_text="First day of the calendar month")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    alert_thresholds = models.JSONField(default=default_budget_thresholds, blank=True)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period", "category", "pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="budget_amount_positive"),
            models.CheckConstraint(condition=models.Q(period__day=1), name="budget_period_month_start"),
            models.UniqueConstraint(
                fields=["owner", "category", "period"],
                condition=models.Q(archived=False, category__isnull=False),
                name="unique_active_category_budget",
            ),
            models.UniqueConstraint(
                fields=["owner", "period"],
                condition=models.Q(archived=False, category__isnull=True),
                name="unique_active_overall_budget",
            ),
        ]

class BudgetSuggestionReview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="budget_suggestion_reviews")
    period = models.DateField()
    selections = models.JSONField()
    expires_at = models.DateTimeField()


class StatementImport(models.Model):
    class Status(models.TextChoices):
        NEEDS_MAPPING = "needs_mapping", "Needs mapping"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        IMPORTED = "imported", "Imported"
        EXPIRED = "expired", "Expired"
        DISCARDED = "discarded", "Discarded"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="statement_imports")
    file_format = models.CharField(max_length=3, blank=True)
    status = models.CharField(max_length=13, choices=Status.choices)
    parsed_rows = models.JSONField(default=list, blank=True)
    errors = models.JSONField(default=list, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    imported_count = models.PositiveIntegerField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class MerchantCategoryRule(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="merchant_category_rules")
    merchant = models.CharField(max_length=255)
    normalized_merchant = models.CharField(max_length=255)
    category = models.CharField(max_length=50, choices=Transaction.Category.choices)

    class Meta:
        ordering = ["merchant", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "normalized_merchant"], name="unique_merchant_category_rule"
            ),
        ]


class CopilotPreferences(models.Model):
    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name="copilot_preferences")
    sharing_enabled = models.BooleanField(default=True)
    history_enabled = models.BooleanField(default=False)
    history = models.JSONField(default=list, blank=True)
    revision = models.PositiveBigIntegerField(default=0)


class CashFlowScenario(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="cash_flow_scenarios")
    name = models.CharField(max_length=80)
    horizon = models.PositiveSmallIntegerField()
    currency = models.CharField(max_length=3)
    changes = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="cash_flow_scenario_owner_name"),
        ]


class GroceryRetailer(models.TextChoices):
    LIDL = "lidl", "Lidl"
    KAUFLAND = "kaufland", "Kaufland"
    FANTASTICO = "fantastico", "Fantastico"


class GroceryCatalogRefresh(models.Model):
    retailer = models.CharField(max_length=10, choices=GroceryRetailer.choices, primary_key=True)
    last_attempt_at = models.DateTimeField()
    last_success_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=12)
    offer_count = models.PositiveIntegerField(default=0)


class GroceryOfferQuerySet(models.QuerySet):
    def current(self, *, now=None):
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        from django.utils import timezone

        now = now or timezone.now()
        today = now.astimezone(ZoneInfo("Europe/Sofia")).date()
        return self.filter(
            starts_on__lte=today, expires_on__gte=today,
            last_successful_update__gte=now - timedelta(hours=48),
            last_successful_update=models.Subquery(
                GroceryCatalogRefresh.objects.filter(retailer=models.OuterRef("retailer")).values("last_success_at")[:1],
            ),
            price__isnull=False, currency__isnull=False,
        ).filter(
            models.Q(starts_at__isnull=True) | models.Q(starts_at__lte=now),
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gte=now),
        )

    def comparable(self, *, now=None):
        return self.current(now=now).filter(
            unit_price__isnull=False, requires_membership=False,
        )


class GroceryOffer(models.Model):
    class Unit(models.TextChoices):
        KILOGRAM = "kg", "Kilogram"
        LITER = "l", "Liter"
        ITEM = "item", "Item"

    retailer = models.CharField(max_length=10, choices=GroceryRetailer.choices)
    retailer_product_id = models.CharField(max_length=255, blank=True)
    retailer_offer_id = models.CharField(max_length=255, blank=True)
    fingerprint = models.CharField(max_length=64)
    product_name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255, db_index=True)
    brand = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=120, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    currency = models.CharField(max_length=3, null=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=6, null=True)
    measurement_unit = models.CharField(max_length=4, choices=Unit.choices, blank=True)
    pack_count = models.PositiveIntegerField(null=True)
    unit_price = models.DecimalField(max_digits=24, decimal_places=6, null=True)
    discount_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    starts_on = models.DateField(null=True)
    expires_on = models.DateField(null=True)
    starts_at = models.DateTimeField(null=True)
    expires_at = models.DateTimeField(null=True)
    image_url = models.URLField(max_length=2048, blank=True)
    source_url = models.URLField(max_length=2048)
    last_successful_update = models.DateTimeField()
    availability_status = models.CharField(max_length=16, default="unverified")
    requires_membership = models.BooleanField(default=False)

    objects = GroceryOfferQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["retailer", "fingerprint"], name="grocery_offer_retailer_fingerprint"),
        ]
        indexes = [
            models.Index(fields=["retailer", "expires_on", "last_successful_update"], name="grocery_offer_activity_idx"),
        ]


class GroceryMatchReview(models.Model):
    class Decision(models.TextChoices):
        APPROVE = "approve", "Comparable"
        REJECT = "reject", "Incompatible"

    left = models.ForeignKey(GroceryOffer, on_delete=models.CASCADE, related_name="match_reviews_as_left")
    right = models.ForeignKey(GroceryOffer, on_delete=models.CASCADE, related_name="match_reviews_as_right")
    signature = models.CharField(max_length=64)
    decision = models.CharField(max_length=7, choices=Decision.choices)
    reviewer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    reviewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["left", "right"], name="grocery_review_unique_pair"),
            models.CheckConstraint(condition=models.Q(left_id__lt=models.F("right_id")), name="grocery_review_ordered_pair"),
        ]


class GroceryShoppingList(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="grocery_shopping_lists")
    name = models.CharField(max_length=80)
    settings = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="grocery_shopping_list_owner_name"),
        ]


class Portfolio(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="virtual_portfolios")
    name = models.CharField(max_length=100)
    currency = models.CharField(max_length=3, default="USD")
    created_at = models.DateTimeField(auto_now_add=True)
    ledger_version = models.PositiveBigIntegerField(default=0)
    is_virtual = True

    class Meta:
        ordering = ["-created_at", "-pk"]


class VirtualTrade(models.Model):
    class Side(models.TextChoices):
        BUY = "buy", "Buy"
        SELL = "sell", "Sell"

    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="trades")
    timestamp = models.DateTimeField(auto_now_add=True)
    ticker = models.CharField(max_length=10)
    side = models.CharField(max_length=4, choices=Side.choices)
    quantity = models.DecimalField(max_digits=18, decimal_places=8)
    price = models.DecimalField(max_digits=18, decimal_places=8)
    fees = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    currency = models.CharField(max_length=3)
    client_order_id = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["pk"]
        indexes = [models.Index(fields=["portfolio", "ticker", "id"], name="virtual_trade_ticker_idx")]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="virtual_trade_positive_qty"),
            models.CheckConstraint(condition=models.Q(price__gt=0), name="virtual_trade_positive_price"),
            models.CheckConstraint(condition=models.Q(fees__gte=0), name="virtual_trade_nonnegative_fees"),
            models.CheckConstraint(condition=models.Q(side__in=["buy", "sell"]), name="virtual_trade_valid_side"),
            models.UniqueConstraint(
                fields=["portfolio", "client_order_id"],
                condition=models.Q(client_order_id__isnull=False),
                name="virtual_trade_unique_order",
            ),
        ]


class NotificationCategory(models.TextChoices):
    BUDGET_THRESHOLD = "budget_threshold", "Budget threshold"
    SUBSCRIPTION_RENEWAL = "subscription_renewal", "Subscription renewal"
    UNUSUAL_SPENDING = "unusual_spending", "Unusual spending"
    STATEMENT_IMPORT = "statement_import", "Statement import"
    FINANCIAL_REPORT = "financial_report", "Financial report"
    STOCK_THRESHOLD = "stock_threshold", "Stock threshold"
    GROCERY_DEAL = "grocery_deal", "Grocery deal"


def default_notification_categories():
    return {value: True for value in NotificationCategory.values}


class NotificationPreference(models.Model):
    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name="notification_preference")
    categories = models.JSONField(default=default_notification_categories)


class NotificationEvent(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    category = models.CharField(max_length=24, choices=NotificationCategory.choices)
    digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "category", "digest"], name="notification_event_once"),
        ]


class Notification(models.Model):
    event = models.OneToOneField(NotificationEvent, on_delete=models.CASCADE, related_name="notification")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    category = models.CharField(max_length=24, choices=NotificationCategory.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    payload = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True)
    dismissed_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="notification_owner_created"),
            models.Index(fields=["created_at"], name="notification_retention_idx"),
        ]


class NotificationStockAlert(models.Model):
    class Direction(models.TextChoices):
        ABOVE = "above", "At or above"
        BELOW = "below", "At or below"

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notification_stock_alerts")
    ticker = models.CharField(max_length=10)
    currency = models.CharField(max_length=3)
    direction = models.CharField(max_length=5, choices=Direction.choices)
    target = models.DecimalField(max_digits=18, decimal_places=8)
    last_quote_at = models.DateTimeField(null=True)
    was_met = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "ticker", "currency", "direction", "target"], name="notification_stock_rule_once"),
            models.CheckConstraint(condition=models.Q(target__gt=0), name="notification_stock_positive_target"),
        ]


class FinancialGoal(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="financial_goals")
    name = models.CharField(max_length=120)
    target_amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    target_date = models.DateField(null=True, blank=True)
    monthly_contribution = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    current_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["archived", "-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(target_amount__gt=0), name="goal_positive_target"),
            models.CheckConstraint(condition=models.Q(current_amount__gte=0), name="goal_nonnegative_balance"),
            models.CheckConstraint(
                condition=models.Q(monthly_contribution__isnull=True) | models.Q(monthly_contribution__gte=0),
                name="goal_nonnegative_monthly_rate",
            ),
        ]


class GoalContribution(models.Model):
    class Kind(models.TextChoices):
        CONTRIBUTION = "contribution", "Contribution"
        WITHDRAWAL = "withdrawal", "Withdrawal"

    goal = models.ForeignKey(FinancialGoal, on_delete=models.CASCADE, related_name="contributions")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    note = models.CharField(max_length=255, blank=True)
    request_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=["contribution", "withdrawal"]), name="goal_entry_valid_kind",
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="goal_entry_positive_amount"),
            models.CheckConstraint(condition=models.Q(balance_after__gte=0), name="goal_entry_nonnegative_balance"),
            models.UniqueConstraint(fields=["goal", "request_id"], name="goal_entry_unique_request"),
        ]


class GoalScenario(models.Model):
    goal = models.ForeignKey(FinancialGoal, on_delete=models.CASCADE, related_name="scenarios")
    name = models.CharField(max_length=80)
    changes = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["goal", "name"], name="goal_scenario_unique_name"),
        ]


class Receipt(models.Model):
    class Source(models.TextChoices):
        CAMERA = "camera", "Camera"
        GALLERY = "gallery", "Gallery"
        UPLOAD = "upload", "Upload"

    class Currency(models.TextChoices):
        EUR = "EUR", "EUR"
        BGN = "BGN", "BGN"

    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="receipts")
    merchant = models.CharField(max_length=255)
    normalized_merchant = models.CharField(max_length=255)
    purchased_at = models.DateTimeField()
    currency = models.CharField(max_length=3, choices=Currency.choices)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    discounts = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CONFIRMED)
    source = models.CharField(max_length=7, choices=Source.choices)
    transaction = models.OneToOneField(
        Transaction, null=True, blank=True, on_delete=models.SET_NULL, related_name="receipt",
    )
    image_digest = models.CharField(max_length=64, editable=False)
    fingerprint = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-purchased_at", "-id"]
        indexes = [models.Index(fields=["owner", "-purchased_at"], name="receipt_owner_purchased_idx")]
        constraints = [
            models.UniqueConstraint(fields=["owner", "image_digest"], name="receipt_owner_image_unique"),
            models.UniqueConstraint(fields=["owner", "fingerprint"], name="receipt_owner_details_unique"),
        ]


class ReceiptItem(models.Model):
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name="items")
    original_description = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    unit = models.CharField(max_length=4, choices=GroceryOffer.Unit.choices, blank=True)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    discount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    category = models.CharField(max_length=120, blank=True)
    brand = models.CharField(max_length=120, blank=True)
    confidence = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    product = models.ForeignKey(GroceryOffer, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["pk"]


class ShoppingPersonalization(models.Model):
    class Delivery(models.TextChoices):
        INDIVIDUAL = "individual", "Individual alerts"
        DIGEST = "digest", "Daily digest"

    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name="shopping_personalization")
    automatic_enabled = models.BooleanField(default=False)
    deal_alerts_enabled = models.BooleanField(default=False)
    deal_delivery = models.CharField(max_length=10, choices=Delivery.choices, default=Delivery.INDIVIDUAL)
    quiet_start = models.TimeField(null=True, blank=True)
    quiet_end = models.TimeField(null=True, blank=True)
    digest_time = models.TimeField(default=datetime.time(9))
    preferred_retailers = models.JSONField(default=list, blank=True)
    category_interests = models.JSONField(default=list, blank=True)


class ProductPreference(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        INFERRED = "inferred", "Inferred"

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="product_preferences")
    product = models.ForeignKey(GroceryOffer, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL)
    favorite = models.BooleanField(default=True)
    preferred_brand = models.CharField(max_length=120, blank=True)
    preferred_quantity = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    preferred_unit = models.CharField(max_length=4, choices=GroceryOffer.Unit.choices, blank=True)
    minimum_discount = models.PositiveSmallIntegerField(null=True, blank=True)
    notifications_enabled = models.BooleanField(default=False)
    alert_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    alert_currency = models.CharField(max_length=3, blank=True)
    excluded = models.BooleanField(default=False)
    muted = models.BooleanField(default=False)
    last_purchase_date = models.DateField(null=True, blank=True)
    purchase_frequency = models.PositiveIntegerField(default=0)
    last_notified_offer = models.ForeignKey(
        GroceryOffer, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["-favorite", "normalized_name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "normalized_name"], name="user_product_identity_unique"),
            models.CheckConstraint(condition=models.Q(minimum_discount__lte=100), name="product_discount_at_most_100"),
        ]


class PersonalizedOfferReview(models.Model):
    class Decision(models.TextChoices):
        ACCEPT = "accept", "Accept as comparable"
        REJECT = "reject", "Reject"

    preference = models.ForeignKey(ProductPreference, on_delete=models.CASCADE, related_name="offer_reviews")
    offer = models.ForeignKey(GroceryOffer, on_delete=models.CASCADE)
    decision = models.CharField(max_length=6, choices=Decision.choices)
    signature = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["preference", "offer"], name="personal_offer_review_unique"),
        ]


class TrackedGroceryOffer(models.Model):
    preference = models.ForeignKey(ProductPreference, on_delete=models.CASCADE, related_name="tracked_offers")
    offer = models.ForeignKey(GroceryOffer, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["preference", "offer"], name="tracked_grocery_offer_once"),
        ]
