"""Local, opt-in product signals and advertised offer matching."""
from datetime import timedelta

from django.db.models import Count, Max
from django.db.models.functions import TruncDate
from django.utils import timezone

from api.models import GroceryOffer, Receipt, ReceiptItem
from api.services.grocery_catalog import normalized
from api.services.grocery_matching import ALIASES
from api.services.receipts import SOFIA

LOOKBACK_DAYS = 180
MIN_PURCHASE_DAYS = 3
LIBRARY_LIMIT = 200
SUGGESTION_LIMIT = 30
CATEGORY_LABELS = {
    "milk": "Milk", "plant_drink": "Plant drinks", "yogurt": "Yogurt", "eggs": "Eggs", "rice": "Rice",
    "coffee": "Coffee", "butter": "Butter", "cheese": "Cheese", "bread": "Bread", "pasta": "Pasta",
    "cooking_oil": "Cooking oil", "flour": "Flour",
}
# Only exact names in these staple groups become receipt-derived interests.
# No broad fuzzy inference, sensitive labels or account attributes.
SAFE_PRODUCTS = {normalized(alias): category for category in CATEGORY_LABELS for alias in ALIASES[category]}


def purchase_signals(owner):
    today = timezone.localdate(timezone=SOFIA)
    recent = ReceiptItem.objects.filter(
        receipt__owner=owner, receipt__status=Receipt.Status.CONFIRMED, receipt__total__gt=0,
        receipt__purchased_at__gte=timezone.now() - timedelta(days=LOOKBACK_DAYS + 1),
        normalized_name__in=SAFE_PRODUCTS, line_total__gt=0,
    ).order_by().annotate(day=TruncDate("receipt__purchased_at", tzinfo=SOFIA)).filter(
        day__gte=today - timedelta(days=LOOKBACK_DAYS - 1), day__lte=today,
    )
    return recent.values("normalized_name").annotate(
        purchase_frequency=Count("day", distinct=True), last_purchase_date=Max("day"),
    ).order_by("-purchase_frequency", "-last_purchase_date", "normalized_name")


def suggested_products(signals, library_names):
    return [{
        **row, "name": row["normalized_name"], "category": SAFE_PRODUCTS[row["normalized_name"]],
    } for row in signals if row["purchase_frequency"] >= MIN_PURCHASE_DAYS and row["normalized_name"] not in library_names
    ][:SUGGESTION_LIMIT]


def matches_preference(offer, preference):
    return (
        (not preference.preferred_brand or normalized(preference.preferred_brand) == normalized(offer.brand))
        and (preference.preferred_quantity is None or (
            preference.preferred_quantity == offer.quantity and preference.preferred_unit == offer.measurement_unit
        ))
        and (preference.minimum_discount is None or (
            offer.discount_percent is not None and offer.discount_percent >= preference.minimum_discount
        ))
    )


def available_offers(preferences, settings):
    library = {row.normalized_name: row for row in preferences}
    category_names = {name for name, family in SAFE_PRODUCTS.items() if family in settings.category_interests}
    eligible = {name for name, row in library.items() if not row.excluded and not row.muted}
    excluded = {name for name, row in library.items() if row.excluded or row.muted}
    names = (eligible | category_names) - excluded
    if not names:
        return []
    offers = GroceryOffer.objects.current().filter(
        normalized_name__in=names, availability_status="advertised",
    ).order_by("-last_successful_update", "pk")
    if settings.preferred_retailers:
        offers = offers.filter(retailer__in=settings.preferred_retailers)
    return [offer for offer in offers[:1000] if offer.normalized_name not in library
            or matches_preference(offer, library[offer.normalized_name])][:30]


def notify_product_offers(retailer):
    """Check only the updated, current catalog and create private in-app alerts."""
    from django.db import transaction

    from api.models import NotificationCategory, ProductPreference, ShoppingPersonalization
    from api.services.notifications import notify

    current = GroceryOffer.objects.current().filter(retailer=retailer, availability_status="advertised")
    eligible = ProductPreference.objects.filter(notifications_enabled=True, excluded=False, muted=False,
                                                normalized_name__in=current.values("normalized_name"))
    for preference_id in eligible.values_list("pk", flat=True).iterator():
        with transaction.atomic():
            preference = eligible.select_for_update().filter(pk=preference_id).first()
            if preference is None:
                continue
            stores = ShoppingPersonalization.objects.filter(owner_id=preference.owner_id).values_list(
                "preferred_retailers", flat=True,
            ).first()
            if stores and retailer not in stores:
                continue
            offer = next((offer for offer in current.filter(normalized_name=preference.normalized_name)
                          .order_by("-starts_on", "-last_successful_update", "-pk")[:100]
                          if matches_preference(offer, preference)), None)
            if offer and offer.pk != preference.last_notified_offer_id:
                notice = notify(preference.owner_id, NotificationCategory.GROCERY_DEAL, f"offer:{offer.pk}")
                if notice:
                    preference.last_notified_offer = offer
                    preference.save(update_fields=["last_notified_offer"])
