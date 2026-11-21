import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher

from django.core.exceptions import PermissionDenied

from api.models import GroceryMatchReview
from api.services.grocery_catalog import normalized, parse_package

# Specific preparations are evaluated before generic grocery names.
ALIASES = {
    "rice_cake": ("rice cakes", "rice cake", "оризовки", "оризови вафли"),
    "rice_flour": ("rice flour", "оризово брашно", "брашно от ориз"),
    "rice_noodles": ("rice noodles", "оризови спагети", "оризово фиде"),
    "plant_drink": (
        "oat milk", "almond milk", "soy milk", "soya milk", "rice milk", "coconut milk",
        "plant milk", "plant based milk", "milk alternative", "oat drink", "almond drink",
        "soy drink", "rice drink", "coconut drink", "овесено мляко", "бадемово мляко",
        "соево мляко", "оризово мляко", "кокосово мляко", "растително мляко",
        "овесена напитка", "бадемова напитка", "соева напитка", "оризова напитка",
    ),
    "yogurt": ("yogurt", "yoghurt", "кисело мляко"),
    "milk_powder": ("powdered milk", "milk powder", "сухо мляко"),
    "condensed_milk": ("condensed milk", "evaporated milk", "кондензирано мляко"),
    "chocolate": ("milk chocolate", "млечен шоколад"),
    "coffee_drink": ("iced coffee", "coffee drink", "студено кафе", "кафе напитка"),
    "candy": ("coffee candy", "coffee flavored candy", "coffee chocolate", "бонбони с кафе"),
    "infant_formula": ("infant formula", "baby formula", "baby milk", "адаптирано мляко"),
    "nut_spread": ("peanut butter", "almond butter", "фъстъчено масло", "бадемово масло"),
    "egg_pasta": ("egg pasta", "egg noodles", "яйчена паста", "яйчено фиде"),
    "egg_powder": ("egg powder", "powdered eggs", "яйца на прах", "яйчен прах"),
    "milk": ("milk", "прясно мляко", "мляко"),
    "eggs": ("eggs", "egg", "яйца", "яйце"),
    "rice": ("rice", "ориз"),
    "coffee": ("coffee", "кафе"),
    "butter": ("butter", "краве масло", "масло от краве мляко"),
    "cheese": ("cheese", "сирене", "кашкавал"),
    "bread": ("bread", "хляб"),
    "pasta": ("pasta", "spaghetti", "макарони", "спагети"),
    "cooking_oil": ("cooking oil", "olive oil", "sunflower oil", "зехтин", "олио"),
    "flour": ("flour", "брашно"),
}
STAPLES = ("milk", "eggs", "rice", "coffee", "butter", "cheese", "bread", "pasta", "cooking_oil", "flour")
FAMILY_UNITS = {
    "milk": {"l"}, "plant_drink": {"l"}, "coffee_drink": {"l"}, "eggs": {"item"},
    "rice": {"kg"}, "milk_powder": {"kg"}, "rice_flour": {"kg"},
    "coffee": {"kg", "item"}, "egg_powder": {"kg"}, "chocolate": {"kg"},
    "butter": {"kg"}, "cheese": {"kg"}, "bread": {"kg", "item"}, "pasta": {"kg"},
    "cooking_oil": {"l"}, "flour": {"kg"},
}
NON_FOOD = (
    "shampoo", "soap", "lotion", "body wash", "skin care", "pet food", "dog food", "cat food",
    "rice cooker", "coffee machine", "coffee maker", "coffee mug", "coffee mugs", "coffee filters",
    "шампоан", "сапун", "лосион", "за тяло", "храна за кучета", "храна за котки",
    "уред за ориз", "кафемашина", "кафе машина", "чаша за кафе", "филтри за кафе",
)
NON_FOOD_CATEGORIES = (
    "cosmetics", "beauty", "personal care", "household appliances", "pet supplies",
    "козметика", "лична хигиена", "електроуреди", "домашни любимци",
)
TRAITS = {
    "milk": {
        "species": {"cow": ("cow", "краве"), "goat": ("goat", "козе"), "sheep": ("sheep", "овче")},
        "flavor": {"chocolate": ("chocolate milk", "шоколадово мляко"),
                   "strawberry": ("strawberry milk", "ягодово мляко")},
        "lactose": {"free": ("lactose free", "без лактоза", "безлактозно"), "regular": ("with lactose", "с лактоза")},
        "processing": {"uht": ("uht", "ultra pasteurized"), "pasteurized": ("pasteurized", "пастьоризирано")},
    },
    "plant_drink": {
        "plant": {
            "oat": ("oat", "овесено", "овесена"), "almond": ("almond", "бадемово", "бадемова"),
            "soy": ("soy", "soya", "соево", "соева"), "rice": ("rice", "оризово", "оризова"),
            "coconut": ("coconut", "кокосово"),
        },
    },
    "eggs": {"species": {"quail": ("quail", "пъдпъдъчи"), "duck": ("duck", "патешки"),
                         "chicken": ("chicken", "кокоши", "кокоши яйца")}},
    "rice": {
        "variety": {"basmati": ("basmati", "басмати"), "jasmine": ("jasmine", "жасмин"),
                    "arborio": ("arborio", "арборио")},
        "processing": {"brown": ("brown", "кафяв"), "white": ("white", "бял"),
                       "parboiled": ("parboiled", "пропарен")},
        "preparation": {"cooked": ("cooked", "ready to eat", "сварен", "готов за консумация"),
                        "dry": ("dry", "uncooked", "сух", "несварен")},
    },
    "cheese": {
        "type": {"white": ("white cheese", "бяло сирене"), "yellow": ("yellow cheese", "кашкавал"),
                 "feta": ("feta", "фета"), "cheddar": ("cheddar", "чедър")},
    },
    "cooking_oil": {"type": {"olive": ("olive oil", "зехтин"), "sunflower": ("sunflower oil", "слънчогледово олио")}},
    "flour": {"type": {"wheat": ("wheat", "пшенично"), "corn": ("corn", "царевично"), "rye": ("rye", "ръжено")}},
    "coffee": {
        "form": {
            "ground": ("ground", "мляно", "смляно"), "beans": ("beans", "whole bean", "на зърна", "зърна"),
            "instant": ("instant", "разтворимо", "инстантно"), "capsules": ("capsules", "pods", "капсули"),
        },
        "caffeine": {"decaf": ("decaf", "decaffeinated", "безкофеиново", "без кофеин"),
                     "regular": ("caffeinated", "с кофеин")},
        "variety": {"arabica": ("arabica", "арабика"), "robusta": ("robusta", "робуста")},
        "mix": {"mix": ("3 in 1", "2 in 1", "3 в 1", "2 в 1")},
    },
}
STOPWORDS = {"fresh", "premium", "quality", "прясно", "висококачествено", "от", "of"}


def has_phrase(text, phrase):
    return f" {phrase} " in f" {text} "


def classify(name, source_category):
    if any(has_phrase(name, term) for term in NON_FOOD) or any(
        has_phrase(source_category, term) for term in NON_FOOD_CATEGORIES
    ):
        return "non_food", name, False
    for family, aliases in ALIASES.items():
        if family in STAPLES:
            continue
        if any(has_phrase(name, alias) for alias in aliases):
            return family, replace_aliases(name, aliases, family), False
    families = [
        key for key in STAPLES
        if any(has_phrase(name, alias) for alias in ALIASES[key])
    ]
    if len(families) != 1:
        return "", name, len(families) > 1
    family = families[0]
    if family == "milk" and any(
        has_phrase(name, term) for terms in TRAITS["plant_drink"]["plant"].values() for term in terms
    ):
        return "plant_drink", replace_aliases(name, ALIASES["milk"], "plant_drink"), False
    return family, replace_aliases(name, ALIASES[family], family), False


def replace_aliases(text, aliases, replacement):
    for alias in sorted(aliases, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(alias)}(?!\w)", replacement, text)
    return text


def number(value):
    try:
        amount = Decimal(str(value))
        return amount if amount.is_finite() and amount > 0 else None
    except (InvalidOperation, ValueError):
        return None


@dataclass(frozen=True)
class Product:
    title: str
    brand: str
    category: str
    source_category: str
    traits: tuple
    ambiguous: bool
    quantity: Decimal | None
    unit: str
    pack_count: int | None
    unit_price: Decimal | None
    currency: str | None


@dataclass(frozen=True)
class Match:
    relation: str
    method: str
    confidence: Decimal | None
    reasons: tuple[str, ...]
    left: Product
    right: Product
    ai_suggestion: str | None = None

    @property
    def comparable_prices(self):
        if (self.relation in ("identical", "comparable") and self.left.currency
                and self.left.currency == self.right.currency
                and self.left.unit_price is not None and self.right.unit_price is not None):
            return self.left.unit_price, self.right.unit_price
        return None


def describe(offer):
    title = unicodedata.normalize("NFKC", offer.product_name)
    package = parse_package(title)
    quantity = number(offer.quantity)
    unit = offer.measurement_unit
    count = offer.pack_count
    conflict = bool(package and quantity and (
        (quantity, unit) != package[:2] or (count is not None and count != package[2])
    ))
    if package:
        if not quantity:
            quantity, unit, count = package[:3]
        elif count is None and not conflict:
            count = package[2]
        match = package[3]
        title = title[:match.start()] + " " + title[match.end():]
    name = normalized(title[:255])
    brand = normalized(offer.brand)
    source_category = normalized(offer.category)
    if brand:
        name = replace_aliases(name, (brand,), " ").strip()
    family, canonical, ambiguous = classify(name, source_category)

    if family == "eggs" and not package and len(re.findall(r"\b\d+\b", canonical)) == 1:
        egg_count = re.search(r"\bpack of ([1-9]\d?)\b|\beggs? x ([1-9]\d?)\b", canonical)
        if not egg_count:
            egg_count = re.fullmatch(r"(?:eggs ([1-9]\d?)|([1-9]\d?) eggs)", canonical)
        if egg_count:
            items = Decimal(next(item for item in egg_count.groups() if item))
            if quantity:
                conflict = conflict or (quantity, unit, count or 1) != (items, "item", 1)
            else:
                quantity, unit, count = items, "item", 1
            canonical = (canonical[:egg_count.start()] + " " + canonical[egg_count.end():]).strip() or family

    traits = {}
    for facet, choices in TRAITS.get(family, {}).items():
        matched = [(value, alias) for value, aliases in choices.items() for alias in aliases if has_phrase(name, alias)]
        hits = {
            value for value, term in matched
            if not any(value != other and term != longer and has_phrase(longer, term) for other, longer in matched)
        }
        if len(hits) > 1:
            ambiguous = True
        elif hits:
            value = next(iter(hits))
            traits[facet] = value
            canonical = replace_aliases(canonical, choices[value], value)
    if family == "milk":
        fat = re.findall(r"(?<![\d.,])(\d{1,2}(?:[.,]\d+)?)\s*%", title)
        if len(fat) > 1:
            ambiguous = True
        elif fat:
            traits["fat"] = str(Decimal(fat[0].replace(",", ".")).normalize())
            canonical = re.sub(r"\b" + re.escape(normalized(fat[0])) + r"\b", " ", canonical)

    words = [word for word in canonical.split() if word not in STOPWORDS]
    price = number(offer.price)
    currency = offer.currency
    valid_unit = unit in ("kg", "l", "item")
    if not valid_unit or not quantity or quantity < Decimal("0.000001") or conflict:
        unit_price = None
    else:
        unit_price = (price / quantity).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP) if price and currency else None
    return Product(" ".join(words), brand, family, source_category, tuple(sorted(traits.items())),
                   ambiguous or conflict, quantity, unit, count, unit_price, currency)


def rule_match(left, right):
    return compare_products(describe(left), describe(right))


def compare_products(a, b):

    def result(relation, reason, method="rules", confidence=None):
        return Match(relation, method, confidence, (reason,), a, b)

    if "non_food" in (a.category, b.category):
        return result("incompatible", "non_grocery_product")
    if a.unit and b.unit and a.unit != b.unit:
        return result("incompatible", "different_measurement_units")
    if a.category and b.category and a.category != b.category:
        return result("incompatible", "different_product_categories")
    for product in (a, b):
        if product.unit and product.category in FAMILY_UNITS and product.unit not in FAMILY_UNITS[product.category]:
            return result("incompatible", "unexpected_unit_for_category")
        if product.category == "coffee" and product.unit == "item" and dict(product.traits).get("form") != "capsules":
            return result("needs_review", "uncertain_coffee_package_type")

    traits_a, traits_b = dict(a.traits), dict(b.traits)
    if any(traits_a[key] != traits_b[key] for key in traits_a.keys() & traits_b.keys()):
        return result("incompatible", "conflicting_product_variants")
    if a.ambiguous or b.ambiguous or not (a.quantity and b.quantity and a.unit and b.unit):
        return result("needs_review", "unverified_package_or_title")
    if a.category != b.category or not a.category:
        return result("needs_review", "unverified_product_category")
    if traits_a != traits_b:
        return result("needs_review", "missing_variant_information")

    same_pack = a.quantity == b.quantity and a.pack_count is not None and a.pack_count == b.pack_count
    same_brand = bool(a.brand and a.brand == b.brand)
    if a.title and a.title == b.title:
        relation = "identical" if same_pack and same_brand else "comparable"
        return result(relation, "normalized_title_match", "exact")

    left_words, right_words = set(a.title.split()), set(b.title.split())
    common = left_words & right_words
    different_a, different_b = left_words - common, right_words - common
    # Exact shared tokens plus small spelling changes can support a fuzzy match.
    similarities = [
        SequenceMatcher(None, word_a, word_b).ratio()
        for word_a, word_b in zip(sorted(different_a), sorted(different_b))
    ]
    denominator = max(1, len(left_words | right_words) - min(len(different_a), len(different_b)))
    score = Decimal(str(round((len(common) + sum(similarities)) / denominator, 3)))
    spelling_only = (
        len(different_a) == len(different_b) and all(value >= 0.84 for value in similarities)
        and all(word.isalpha() for word in different_a | different_b)
    )
    if a.title and b.title and spelling_only and score >= Decimal("0.88"):
        return result("comparable", "similar_titles", "fuzzy", score)
    return result("needs_review", "ambiguous_title_similarity", "fuzzy", score)


def persisted_pair(left, right):
    if left.pk is None or right.pk is None or left.pk == right.pk:
        return None
    return tuple(sorted((left, right), key=lambda offer: offer.pk))


def review_signature(pair):
    values = [
        [offer.pk, offer.product_name, offer.brand, offer.category, str(offer.quantity),
         offer.measurement_unit, offer.pack_count]
        for offer in pair
    ]
    return hashlib.sha256(json.dumps(["rules-v1", values], ensure_ascii=False).encode()).hexdigest()


def is_reviewable(match):
    a, b = match.left, match.right
    return (
        match.relation == "needs_review" and not (a.ambiguous or b.ambiguous)
        and a.unit == b.unit and a.unit in ("kg", "l", "item") and a.quantity is not None and b.quantity is not None
    )


def match_offers(left, right, *, ai_assist=False):
    match = rule_match(left, right)
    if not is_reviewable(match):
        return match
    pair = persisted_pair(left, right)
    if pair:
        review = GroceryMatchReview.objects.filter(
            left=pair[0], right=pair[1], signature=review_signature(pair),
        ).first()
        if review:
            relation = "comparable" if review.decision == GroceryMatchReview.Decision.APPROVE else "incompatible"
            return replace(match, relation=relation, method="human_review", confidence=None)
    if ai_assist is True:
        from api.services.grocery_match_ai import suggest_match

        match = replace(match, ai_suggestion=suggest_match(match))
    return match


def review_match(left, right, *, reviewer, decision):
    if not reviewer or not reviewer.is_authenticated or not reviewer.is_active or not reviewer.is_staff:
        raise PermissionDenied("Only catalog staff can review product matches.")
    if decision not in GroceryMatchReview.Decision.values:
        raise ValueError("Choose a supported review decision.")
    pair = persisted_pair(left, right)
    if not pair or not is_reviewable(rule_match(*pair)):
        raise ValueError("Only persisted, compatible-unit pairs marked for review can be reviewed.")
    return GroceryMatchReview.objects.update_or_create(
        left=pair[0], right=pair[1],
        defaults={"signature": review_signature(pair), "decision": decision, "reviewer": reviewer},
    )[0]
