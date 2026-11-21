from collections import Counter
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from heapq import heappop, heappush
from itertools import combinations
from zoneinfo import ZoneInfo

from django.db.models import Exists, OuterRef
from django.utils import timezone

from api.models import GroceryOffer, GroceryRetailer
from api.services.grocery_matching import FAMILY_UNITS, compare_products, describe

MAX_CATALOG_ROWS = 6000
MAX_SOLVER_STEPS = 350_000
MAX_DIAGNOSTICS = 15
SCALE = 1_000_000
LOCAL_ZONE = ZoneInfo("Europe/Sofia")
ASSUMPTIONS = [
    "Costs use advertised offers in one currency and round purchases up to whole packages.",
    "The solver can combine package sizes for a line. Surplus quantities are reported for that line.",
    "Each shopping-list line is fulfilled separately. Preferred brands break equal-price ties when substitutions are allowed.",
    "Travel or shopping overhead applies once per store actually used.",
    "Coverage is limited to the current observed catalog. Advertised offers do not establish store-level stock.",
    "Repeated packages are costed at the advertised price. Store purchase limits can affect the estimate.",
]


class BasketLimit(ValueError):
    pass


def money(value):
    return format(value, ".2f")


def measure(value):
    return format(value.normalize(), "f")


def requested_product(name, brand=""):
    return describe(GroceryOffer(product_name=name, brand=brand))


def infer_unit(product):
    if product.unit:
        return product.unit
    if product.category == "coffee":
        return "item" if dict(product.traits).get("form") == "capsules" else "kg"
    units = FAMILY_UNITS.get(product.category, ())
    return next(iter(units)) if len(units) == 1 else None


def safe_extra_trait(category, key, value):
    return (
        category == "milk" and (key in ("fat", "processing") or (key, value) == ("species", "cow"))
        or category == "eggs" and (key, value) == ("species", "chicken")
        or category == "rice" and (key, value) in {("processing", "white"), ("preparation", "dry")}
    )


def shopping_match(item, candidate):
    request = item["product"]
    preferred = request.brand
    if not (request.title and candidate.title):
        return "unrelated"
    if request.title != candidate.title and (not request.category or request.category != candidate.category):
        return "unrelated"
    if request.ambiguous or candidate.ambiguous or not candidate.quantity or not candidate.unit:
        return "uncertain"
    if request.unit != candidate.unit:
        return "incompatible"
    if not item["allow_substitutions"] and (
        preferred and preferred != candidate.brand
        or item["named_package"] is not None and (
            (item["named_package"], item["named_pack_count"]) != (candidate.quantity, candidate.pack_count)
        )
    ):
        return "incompatible"

    # SKU identity is unnecessary for a shopping request. Exact unclassified titles
    # are usable if the unit is explicit and neither title has conflicting signals.
    if not request.category and not candidate.category and request.title == candidate.title:
        return "exact"

    compared = compare_products(request, candidate)
    if compared.relation == "incompatible":
        return "incompatible"
    if compared.method == "exact":
        return "exact"
    if not item["allow_substitutions"]:
        return "uncertain" if compared.relation == "needs_review" else "incompatible"
    if compared.relation == "comparable":
        return "fuzzy"

    request_traits, candidate_traits = dict(request.traits), dict(candidate.traits)
    extra = candidate_traits.keys() - request_traits.keys()
    if (
        request.category == candidate.category and request.title == request.category
        and request_traits.items() <= candidate_traits.items()
        and extra and all(safe_extra_trait(request.category, key, candidate_traits[key]) for key in extra)
    ):
        remaining = set(candidate.title.split()) - {candidate_traits[key] for key in extra}
        if remaining == {request.category}:
            return "alternative"
    return "uncertain"


def availability(offer, currency, now):
    today = now.astimezone(LOCAL_ZONE).date()
    if (offer.expires_on and offer.expires_on < today) or (offer.expires_at and offer.expires_at < now):
        return "expired"
    if (
        (offer.starts_on and offer.starts_on > today) or (offer.starts_at and offer.starts_at > now)
        or offer.requires_membership or (offer.currency and offer.currency != currency)
        or offer.availability_status not in ("advertised", "unverified")
    ):
        return "unavailable"
    if offer.availability_status == "unverified" or not (offer.starts_on and offer.expires_on and offer.price and offer.currency):
        return "uncertain"
    if not offer.is_current:
        return "unavailable"
    return "eligible"


@dataclass(frozen=True)
class Pack:
    offer: GroceryOffer
    units: int
    price: Decimal
    match: str
    preferred: bool


def basket_snapshot(currency, *, retailers=None, now=None):
    now = now or timezone.now()
    # Old observations are useful for explaining why a recently advertised item is missing.
    current = GroceryOffer.objects.current(now=now).filter(pk=OuterRef("pk"))
    observations = list(GroceryOffer.objects.filter(
        retailer__in=retailers if retailers is not None else GroceryRetailer.values,
        last_successful_update__gte=now - timedelta(days=30),
    ).annotate(is_current=Exists(current)).order_by("pk")[:MAX_CATALOG_ROWS + 1])
    if len(observations) > MAX_CATALOG_ROWS:
        raise BasketLimit("The recent catalog exceeds the comparison limit.")
    return [
        (offer, describe(offer), availability(offer, currency, now))
        for offer in observations
    ]


def choices_for(item, observations):
    options = []
    counts = Counter()
    diagnostics = []
    for offer, product, state in observations:
        match = shopping_match(item, product)
        if match == "unrelated":
            continue
        if state == "eligible" and match not in ("incompatible", "uncertain"):
            units = int(product.quantity * SCALE)
            if units > 0:
                options.append(Pack(offer, units, offer.price, match, bool(product.brand and product.brand == item["product"].brand)))
                continue
        status = state if state != "eligible" else "unavailable" if match == "incompatible" else "uncertain"
        counts[status] += 1
        if len(diagnostics) < MAX_DIAGNOSTICS:
            diagnostics.append({
                "offer_id": offer.pk, "retailer": offer.retailer, "name": offer.product_name,
                "status": status, "match": match, "expires_on": offer.expires_on,
                "catalog_availability_status": offer.availability_status,
            })
    return options, {"counts": dict(counts), "offers": diagnostics, "truncated": sum(counts.values()) > len(diagnostics)}


@dataclass
class WorkLimit:
    remaining: int = MAX_SOLVER_STEPS

    def spend(self, count):
        self.remaining -= count
        if self.remaining < 0:
            raise BasketLimit("This shopping list and catalog exceed the exact comparison limit.")


def cheapest_packages(options, target, work):
    if not options:
        return None
    # For equal coverage, retain the cheapest labeled package, then prefer the
    # requested brand and finally the offer ID. A dominated equal-size pack cannot help.
    sizes = {}
    for pack in options:
        key = min(target, pack.units)
        existing = sizes.get(key)
        if existing is None or (
            pack.price, not pack.preferred, pack.units, pack.offer.pk,
        ) < (existing.price, not existing.preferred, existing.units, existing.offer.pk):
            sizes[key] = pack
    options = list(sizes.values())
    # Every edge adds coverage. Processing reachable quantities in ascending
    # order allows exact unbounded package combinations without a dense grid.
    ranks = {0: (Decimal(0), 0, 0, 0)}
    predecessors = {}
    pending = [0]
    while pending:
        covered = heappop(pending)
        if covered == target:
            break
        work.spend(len(options))
        cost, substitutions, packages, delivered = ranks[covered]
        for pack in options:
            next_value = min(target, covered + pack.units)
            candidate = (cost + pack.price, substitutions + int(not pack.preferred), packages + 1, delivered + pack.units)
            existing = ranks.get(next_value)
            if existing is None or candidate < existing:
                if existing is None:
                    heappush(pending, next_value)
                ranks[next_value] = candidate
                predecessors[next_value] = (covered, pack)
    if target not in ranks:
        return None
    counts = {}
    position = target
    while position:
        position, pack = predecessors[position]
        pk = pack.offer.pk
        counts[pk] = (pack, counts.get(pk, (pack, 0))[1] + 1)
    cost, _, _, delivered = ranks[target]
    return cost, delivered, tuple(counts.values())


def build_basket(items, options, retailers, overhead, work, memo):
    lines = []
    subtotal = Decimal(0)
    used = set()
    unmatched = []
    substitutions = 0
    for index, (item, packs) in enumerate(zip(items, options, strict=True)):
        subset = tuple(pack for pack in packs if pack.offer.retailer in retailers)
        key = (index, tuple(pack.offer.pk for pack in subset))
        if key not in memo:
            memo[key] = cheapest_packages(subset, int(item["quantity"] * SCALE), work)
        result = memo[key]
        if result is None:
            unmatched.append(index)
            continue
        cost, delivered, counts = result
        subtotal += cost
        used.update(pack.offer.retailer for pack, _ in counts)
        if item["product"].brand:
            substitutions += sum(count for pack, count in counts if not pack.preferred)
        quantity = Decimal(delivered) / SCALE
        lines.append({
            "item_index": index, "quantity_purchased": measure(quantity),
            "surplus_quantity": measure(quantity - item["quantity"]), "unit": item["product"].unit,
            "estimated_cost": money(cost),
            "packages": [
                {
                    "offer_id": pack.offer.pk, "retailer": pack.offer.retailer, "name": pack.offer.product_name,
                    "count": count, "quantity_per_package": measure(Decimal(pack.units) / SCALE),
                    "package_price": money(pack.price), "estimated_cost": money(pack.price * count),
                    "unit_price": format((pack.price * SCALE / pack.units).quantize(
                        Decimal("0.000001"), rounding=ROUND_HALF_UP,
                    ), "f"), "availability_status": pack.offer.availability_status,
                    "match": pack.match, "source_url": pack.offer.source_url, "expires_on": pack.offer.expires_on,
                    "image_url": pack.offer.image_url, "last_successful_update": pack.offer.last_successful_update,
                }
                for pack, count in sorted(counts, key=lambda value: value[0].offer.pk)
            ],
        })
    overhead_total = overhead * len(used)
    return {
        "allowed_retailers": list(retailers), "retailers_used": sorted(used),
        "complete": not unmatched, "lines": lines, "unmatched_item_indexes": unmatched,
        "nonpreferred_package_count": substitutions,
        "matched_items_subtotal": money(subtotal), "overhead_cost": money(overhead_total),
        "estimated_total": None if unmatched else money(subtotal + overhead_total),
    }


def basket_rank(plan):
    return (
        len(plan["unmatched_item_indexes"]),
        Decimal(plan["matched_items_subtotal"]) + Decimal(plan["overhead_cost"]),
        plan["nonpreferred_package_count"], len(plan["retailers_used"]), tuple(plan["retailers_used"]),
    )


def optimize_basket(items, *, currency="EUR", allow_multi_store=True, max_stores=3,
                    overhead_per_store=Decimal("0.00"), retailers=None, now=None):
    now = now or timezone.now()
    selected = GroceryRetailer.values if retailers is None else retailers
    retailers = tuple(retailer for retailer in GroceryRetailer.values if retailer in selected)
    max_stores = min(max_stores, len(retailers))
    snapshot = basket_snapshot(currency, retailers=retailers, now=now)
    results = [choices_for(item, snapshot) for item in items]
    options = [entry[0] for entry in results]
    work = WorkLimit()
    memo = {}
    singles = [build_basket(items, options, (retailer,), overhead_per_store, work, memo) for retailer in retailers]
    single_reference = min((plan for plan in singles if plan["complete"]), key=basket_rank, default=None)
    plans = list(singles)
    if allow_multi_store:
        for size in range(2, max_stores + 1):
            for stores in combinations(retailers, size):
                plans.append(build_basket(items, options, stores, overhead_per_store, work, memo))
    combined = min(plans, key=basket_rank) if allow_multi_store else None
    best = min((plan for plan in plans if plan["complete"]), key=basket_rank, default=None)
    savings = None
    if best is not None and single_reference is not None:
        savings = {
            "reference": "lowest_estimated_complete_single_retailer_basket_in_catalog",
            "reference_retailer": single_reference["retailers_used"][0],
            "reference_total": single_reference["estimated_total"],
            "estimated_savings": money(Decimal(single_reference["estimated_total"]) - Decimal(best["estimated_total"])),
        }
    return {
        "currency": currency, "as_of": now.isoformat(),
        "allow_multi_store": allow_multi_store, "max_stores": max_stores if allow_multi_store else 1,
        "overhead_per_store": money(overhead_per_store),
        "items": [
            {
                "index": index, "name": item["name"], "quantity": measure(item["quantity"]), "unit": item["product"].unit,
                "eligible_offer_count": len(options[index]), "excluded_offers": results[index][1],
            }
            for index, item in enumerate(items)
        ],
        "unmatched_item_indexes": [index for index, packs in enumerate(options) if not packs],
        "single_retailer_baskets": singles, "multi_retailer_basket": combined, "best_basket": best,
        "best_partial_basket": min(plans, key=basket_rank) if best is None else None,
        "savings": savings, "assumptions": ASSUMPTIONS,
    }
