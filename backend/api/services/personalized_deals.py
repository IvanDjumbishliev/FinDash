"""Rank current advertised offers against explicitly saved product interests."""
from collections import defaultdict
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256

from django.db.models import Q
from django.utils import timezone

from api.models import GroceryOffer, GroceryRetailer, PersonalizedOfferReview, ProductPreference, Receipt, ReceiptItem
from api.services.grocery_basket import infer_unit, shopping_match
from api.services.grocery_catalog import normalized
from api.services.grocery_matching import compare_products, describe
from api.services.product_preferences import LOOKBACK_DAYS
from api.services.receipts import product_identity

MAX_OFFERS = 6000
MAX_MATCHES = 12
MAX_REVIEW = 5


def interest_product(preference):
    if preference.product_id:
        return describe(preference.product)
    product = describe(GroceryOffer(product_name=preference.name, brand=preference.preferred_brand))
    if not product.quantity and preference.preferred_quantity is not None:
        product = replace(product, quantity=preference.preferred_quantity, unit=preference.preferred_unit,
                          pack_count=1 if preference.preferred_unit != "item" else None)
    return product


def assess(preference, target, offer, product):
    if not target.title or not product.title or target.ambiguous or product.ambiguous:
        return None
    if not product.quantity or not product.unit:
        return None
    unit = target.unit or infer_unit(target)
    if (unit and unit != product.unit) or (preference.preferred_unit and preference.preferred_unit != product.unit):
        return None
    if not unit and target.title != product.title:
        return None
    # Use the offer's quantity only to compare generic requests. Known package
    # and brand evidence still determine whether the result can be called exact.
    requested = replace(target, unit=unit or product.unit, quantity=target.quantity or product.quantity)
    comparison = compare_products(requested, product)
    if comparison.relation == "incompatible":
        return None
    if not comparison.left.category and comparison.right.category and target.title != product.title:
        return None
    relation = shopping_match({
        "product": requested, "allow_substitutions": True, "named_package": target.quantity,
        "named_pack_count": target.pack_count,
    }, product)
    if relation in {"unrelated", "incompatible"}:
        return None
    brand_expected = normalized(preference.preferred_brand) or target.brand
    brand_match = bool(brand_expected and brand_expected == product.brand)
    requested_quantity = preference.preferred_quantity or target.quantity
    quantity_match = bool(requested_quantity and requested_quantity == product.quantity
                          and (not preference.preferred_unit or preference.preferred_unit == product.unit))
    if relation == "exact":
        if preference.product_id == offer.pk or (comparison.relation == "identical" and brand_match and quantity_match):
            return "exact", Decimal("1.00"), brand_match, quantity_match
        return "comparable", Decimal("0.96"), brand_match, quantity_match
    if relation == "fuzzy" and comparison.confidence is not None:
        return "comparable", comparison.confidence, brand_match, quantity_match
    if relation == "alternative":
        return "comparable", Decimal("0.85"), brand_match, quantity_match
    if (target.category and target.category == product.category) or target.title == product.title:
        return "needs_review", min(comparison.confidence or Decimal("0.65"), Decimal("0.79")), brand_match, quantity_match
    return None


def input_signature(preference, target, product):
    evidence = (target, product.title, product.brand, product.source_category, product.category, product.traits,
                product.quantity, product.unit, product.pack_count, preference.preferred_brand,
                preference.preferred_quantity, preference.preferred_unit)
    # Prices are deliberately excluded so the decision applies across price refreshes.
    evidence = (replace(target, unit_price=None, currency=None), *evidence[1:])
    return sha256(repr(evidence).encode()).hexdigest()


def current_offers(*, currency, membership_retailers, now):
    return GroceryOffer.objects.current(now=now).filter(
        Q(requires_membership=False) | Q(retailer__in=membership_retailers),
        currency=currency, retailer__in=GroceryRetailer.values, availability_status="advertised", price__gt=0,
    )


def discount_met(preference, offer):
    return preference.minimum_discount is None or (
        offer.discount_percent is not None and offer.discount_percent >= preference.minimum_discount
    )


def recent_prices(owner, preferences, currency, now):
    names = {preference.normalized_name for preference in preferences}
    if not names:
        return {}
    rows = ReceiptItem.objects.filter(
        receipt__owner=owner, receipt__status=Receipt.Status.CONFIRMED, receipt__currency=currency,
        receipt__total__gt=0, receipt__purchased_at__range=(now - timedelta(days=LOOKBACK_DAYS), now),
        line_total__gt=0, quantity__gt=0, normalized_name__in=names, unit__in=["kg", "l"],
    ).order_by("-receipt__purchased_at", "-pk").values_list(
        "normalized_name", "brand", "unit", "line_total", "quantity", "receipt__purchased_at",
    )[:3000]
    output = {}
    for name, brand, unit, amount, quantity, purchased_at in rows:
        key = (name, normalized(brand), unit)
        output.setdefault(key, (amount / quantity, purchased_at))
    return output


def rank_key(entry, preferred_retailers):
    historical = entry["historical"]
    price = entry["unit_price"]
    # Comparisons are within this interest and currency. The unit-price ratio
    # applies only when the user's receipt provides the same known brand/unit.
    return (
        entry["relation"] != "exact", -entry["confidence"], not entry["brand_match"],
        not entry["quantity_match"], entry["retailer"] not in preferred_retailers if preferred_retailers else False,
        entry["unit"],
        historical is not None and price > historical["unit_price"],
        price, entry["expires_on"], entry["offer_id"],
    )


def personalize(owner, settings, *, currency, membership_retailers, include_review, now=None,
                alerts_only=False, match_filter=None):
    now = now or timezone.now()
    library = list(ProductPreference.objects.filter(owner=owner).select_related("product"))
    preferences = [pref for pref in library if not pref.muted and not pref.excluded
                   and (not alerts_only or pref.notifications_enabled)]
    suppressed = {pref.normalized_name for pref in library if pref.muted or pref.excluded}
    preferences.sort(key=lambda row: (row.source != ProductPreference.Source.MANUAL, not row.favorite, row.normalized_name))
    if not preferences:
        return {"interests": [], "catalog_truncated": False}
    targets = {pref.pk: interest_product(pref) for pref in preferences}
    history = recent_prices(owner, preferences, currency, now) if settings.automatic_enabled else {}
    matches, uncertain = defaultdict(list), defaultdict(list)
    by_category, by_title = defaultdict(set), defaultdict(set)
    for pk, target in targets.items():
        if target.category:
            by_category[target.category].add(pk)
        by_title[target.title].add(pk)
    by_id = {pref.pk: pref for pref in preferences}
    offer_query = current_offers(currency=currency, membership_retailers=membership_retailers, now=now)
    if alerts_only and settings.preferred_retailers:
        offer_query = offer_query.filter(retailer__in=settings.preferred_retailers)
    offers = list(offer_query.order_by("-last_successful_update", "pk")[:MAX_OFFERS + 1])
    reviews = {(review.preference_id, review.offer_id): review for review in
               PersonalizedOfferReview.objects.filter(
                   preference__owner=owner, offer_id__in=[offer.pk for offer in offers[:MAX_OFFERS]],
               )}
    def ranked(rows, limit):
        return sorted(rows, key=lambda entry: rank_key(entry, settings.preferred_retailers))[:limit]

    for offer in offers[:MAX_OFFERS]:
        if offer.normalized_name in suppressed or product_identity(offer.normalized_name) in suppressed:
            continue
        product = describe(offer)
        if product.unit_price is None:
            continue
        for pk in by_category.get(product.category, set()) | by_title.get(product.title, set()):
            pref, target = by_id[pk], targets[pk]
            if not discount_met(pref, offer):
                continue
            assessed = assess(pref, target, offer, product)
            if assessed is None:
                continue
            relation, confidence, brand_match, quantity_match = assessed
            review = reviews.get((pk, offer.pk))
            user_reviewed = bool(review and review.signature == input_signature(pref, target, product))
            if user_reviewed:
                if review.decision == PersonalizedOfferReview.Decision.REJECT:
                    continue
                if relation == "needs_review":
                    relation = "comparable"
            if relation == "needs_review" and not include_review:
                continue
            same_definition = target.title == product.title and target.traits == product.traits
            historical = history.get((pref.normalized_name, product.brand, product.unit)) if product.brand and same_definition else None
            entry = {
                "offer_id": offer.pk, "product_name": offer.product_name, "retailer": offer.retailer,
                "brand": offer.brand, "quantity": product.quantity, "unit": product.unit, "price": offer.price,
                "unit_price": product.unit_price, "currency": currency, "requires_membership": offer.requires_membership,
                "expires_on": offer.expires_on, "observed_at": offer.last_successful_update, "relation": relation,
                "confidence": confidence, "brand_match": brand_match, "quantity_match": quantity_match,
                "user_reviewed": user_reviewed, "discount_percent": offer.discount_percent,
                "historical": {"unit_price": historical[0].quantize(Decimal("0.000001")),
                               "purchased_at": historical[1]} if historical else None,
            }
            if match_filter and not match_filter(pref, entry):
                continue
            needs_review = relation == "needs_review"
            bucket = (uncertain if needs_review else matches)[pk]
            limit = MAX_REVIEW if needs_review else MAX_MATCHES
            bucket.append(entry)
            if len(bucket) >= 2 * limit:
                bucket[:] = ranked(bucket, limit)

    return {
        "interests": [{
            "id": pref.pk, "name": pref.name, "source": pref.source, "favorite": pref.favorite,
            "matches": ranked(matches[pref.pk], MAX_MATCHES), "review": ranked(uncertain[pref.pk], MAX_REVIEW),
        } for pref in preferences],
        "catalog_truncated": len(offers) > MAX_OFFERS,
    }
