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
