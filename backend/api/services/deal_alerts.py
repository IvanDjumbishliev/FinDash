"""Generate private deal alert events from current catalog data."""
from collections import defaultdict
from datetime import datetime, time, timedelta
from hashlib import sha256
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from api.models import GroceryOffer, GroceryRetailer, NotificationCategory, NotificationEvent, ProductPreference, ShoppingPersonalization
from api.services.copilot_tools import account_timezone
from api.services.notifications import categories_for, notify, reserve_event
from api.services.personalized_deals import assess, discount_met, interest_product, personalize
from api.services.grocery_matching import describe
from api.services.receipts import SOFIA

DEAL = NotificationCategory.GROCERY_DEAL
DIGEST_LIMIT = 10
RUN_LIMIT = 20
HISTORICAL_RATIO = Decimal("0.90")


def in_quiet_hours(moment, start, end):
    if start is None or end is None:
        return False
    if start < end:
        return start <= moment < end
    return moment >= start or moment < end


def expiry(offer):
    return offer.expires_at or datetime.combine(offer.expires_on + timedelta(days=1), time.min, SOFIA)


def alert_details(offer, reasons):
    return {
        "offer_id": offer.pk,
        "product": offer.product_name,
        "retailer": GroceryRetailer(offer.retailer).label,
        "price": format(offer.price, ".2f"),
        "currency": offer.currency,
        "expires_on": offer.expires_on.isoformat(),
        "expires_at": offer.expires_at.isoformat() if offer.expires_at else None,
        "reasons": reasons,
    }


def event_key(offer, phase):
    # A refresh alone must not resend a promotion. An expiry reminder is separate
    # from an earlier discovery alert, and material price/expiry changes can alert.
    return f"deal-v2:{offer.retailer}:{offer.pk}:{offer.currency}:{offer.price:.2f}:{expiry(offer).isoformat()}:{phase}"



def matching_reasons(preference, entry):
    if preference.preferred_brand and not entry["brand_match"]:
        return []
    if preference.preferred_quantity is not None and not entry["quantity_match"]:
        return []
    reasons = []
    if preference.favorite:
        reasons.append("A favorited product has a current offer.")
    price, currency = entry["price"], entry["currency"]
    if preference.alert_price is not None and preference.alert_currency == currency and price <= preference.alert_price:
        reasons.append(f"At or below your {preference.alert_price:.2f} {currency} price threshold.")
    previous = entry["historical"]
    if previous and previous["unit_price"] > 0 and entry["unit_price"] <= previous["unit_price"] * HISTORICAL_RATIO:
        reasons.append(f"At least 10% below the unit price on your comparable confirmed receipt "
                       f"({previous['unit_price'].normalize():f} {currency}/{entry['unit']}).")
    return reasons


def candidates(owner, profile, preferences, now):
    ranked = []
    for currency in ("EUR", "BGN"):
        data = personalize(
            owner, profile, currency=currency, membership_retailers=[],
            include_review=False, now=now, alerts_only=True, match_filter=matching_reasons,
        )
        for interest in data["interests"]:
            preference = preferences.get(interest["id"])
            if preference is None:
                continue
            for entry in interest["matches"]:
                ranked.append((preference, entry))
    active = GroceryOffer.objects.current(now=now).filter(
        availability_status="advertised", requires_membership=False, price__gt=0, retailer__in=GroceryRetailer.values,
    )
    if profile.preferred_retailers:
        active = active.filter(retailer__in=profile.preferred_retailers)
    tracked = defaultdict(set)
    for pref in preferences.values():
        for tracking in pref.tracked_offers.all():
            tracked[tracking.offer_id].add(pref.pk)
    offers = active.in_bulk({entry["offer_id"] for _, entry in ranked} | tracked.keys())
    results = {}

    def include(offer, phase, reasons, pref):
        key = event_key(offer, phase)
        _, saved_reasons, prefs = results.setdefault(key, (offer, [], set()))
        prefs.add(pref.pk)
        saved_reasons.extend(reason for reason in reasons if reason not in saved_reasons)

    for preference, entry in ranked:
        offer = offers.get(entry["offer_id"])
        if not offer or expiry(offer) <= now or offer.price != entry["price"] or offer.last_successful_update != entry["observed_at"]:
            continue
        reasons = matching_reasons(preference, entry)
        if reasons:
            include(offer, "match", reasons, preference)

    for offer_id, preference_ids in tracked.items():
        offer = offers.get(offer_id)
        if offer and now < expiry(offer) <= now + timedelta(hours=24):
            product = describe(offer)
            for pk in sorted(preference_ids):
                pref = preferences[pk]
                result = assess(pref, interest_product(pref), offer, product)
                if not result or result[0] == "needs_review" or not discount_met(pref, offer):
                    continue
                if (pref.preferred_brand and not result[2]) or (pref.preferred_quantity is not None and not result[3]):
                    continue
                include(offer, "expiry", ["An offer you tracked ends within 24 hours."], pref)

    # Expiring confirmed watches take priority over discovery alerts.
    return sorted(results.items(), key=lambda row: (not row[0].endswith(":expiry"), expiry(row[1][0])))


def publish(owner, key, items, *, digest=False):
    """In-app publisher. The matching result also supports other delivery adapters."""
    return notify(owner.pk, DEAL, key, payload={"kind": "digest" if digest else "individual", "deals": items})


@transaction.atomic
def evaluate_deal_alerts(owner, *, now=None):
    now = now or timezone.now()
    # Serialize delivery with settings edits and other tasks for this account.
    if not get_user_model().objects.select_for_update().filter(pk=owner.pk, is_active=True).exists():
        return 0
    profile = ShoppingPersonalization.objects.filter(owner=owner, deal_alerts_enabled=True).first()
    if not profile or not categories_for(owner.pk)[DEAL]:
        return 0
    local = now.astimezone(account_timezone(owner))
    if in_quiet_hours(local.time(), profile.quiet_start, profile.quiet_end):
        return 0
    digest = profile.deal_delivery == ShoppingPersonalization.Delivery.DIGEST
    digest_key = f"deal-digest-v1:{local.date().isoformat()}"
    if digest:
        if local.time() < profile.digest_time:
            return 0
        # Do not reserve an empty digest. Later refreshes can still deliver today.
        if NotificationEvent.objects.filter(owner=owner, category=DEAL, digest=sha256(digest_key.encode()).hexdigest()).exists():
            return 0
    preferences = {pref.pk: pref for pref in ProductPreference.objects.filter(
        owner=owner, notifications_enabled=True, muted=False, excluded=False,
    ).select_related("product").prefetch_related("tracked_offers")}
    if not preferences:
        return 0
    results = candidates(owner, profile, preferences, now)
    delivered = 0
    digest_items = []
    updated = {}
    for key, (offer, reasons, preference_ids) in results:
        item = alert_details(offer, reasons)
        if digest:
            _, created = reserve_event(owner.pk, DEAL, key)
            if not created:
                continue
            digest_items.append(item)
        elif publish(owner, key, [item]):
            delivered += 1
        else:
            continue
        for pk in preference_ids:
            updated[pk] = offer.pk
        if (digest and len(digest_items) >= DIGEST_LIMIT) or delivered >= RUN_LIMIT:
            break
    if digest_items:
        delivered = int(bool(publish(owner, digest_key, digest_items, digest=True)))
    for pk, offer_id in updated.items():
        ProductPreference.objects.filter(owner=owner, pk=pk).update(last_notified_offer_id=offer_id)
    return delivered
