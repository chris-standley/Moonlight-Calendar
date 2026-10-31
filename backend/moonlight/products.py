"""Shop products found by their barcode, for adding to a shopping list. The barcode is looked up in Open Food Facts
(then its sister databases for household and beauty products), and the answer is offered two ways: the exact product
("Tesco Semi Skimmed Milk 2L") or the plain item it is ("Semi skimmed milk", "Milk")."""
from __future__ import annotations

import json
import logging
import re

from . import recipe_import

log = logging.getLogger(__name__)

# Same API on each: food first, then household products (washing up liquid, foil), then toiletries.
SOURCES = (
    "https://world.openfoodfacts.org/api/v2/product/{code}.json",
    "https://world.openproductsfacts.org/api/v2/product/{code}.json",
    "https://world.openbeautyfacts.org/api/v2/product/{code}.json",
)
FIELDS = "product_name,product_name_en,brands,quantity,categories_hierarchy,compared_to_category,image_front_small_url,image_front_url"
MAX_ANSWER_BYTES = 2_000_000

# Category words too broad to be the item on a list ("Dairies", "Plant-based foods and beverages").
_TOO_BROAD = {"foods", "food", "beverages", "drinks", "products", "dairies", "groceries", "snacks", "meals", "and",
              "based", "fermented", "sweet", "salty", "frozen", "fresh", "canned", "fats", "condiments", "desserts"}
# The last word of a category is plural ("Milks"); these read better singular on a shopping list. Others ("Crisps",
# "Biscuits", "Eggs") stay as they are.
_MASS_NOUNS = {"milks", "cheeses", "butters", "yogurts", "yoghurts", "breads", "juices", "waters", "flours", "sugars",
               "rices", "coffees", "teas", "wines", "beers", "ciders", "oils", "creams", "sauces", "soups", "pastas",
               "cereals", "honeys", "jams", "spreads", "mayonnaises", "ketchups", "mustards", "vinegars", "chocolates",
               "hams", "bacons", "salts", "squashes", "porridges", "granolas", "creams", "margarines",
               "gins", "vodkas", "whiskies", "custards", "stocks", "gravies", "tofus"}
_QUANTITY = re.compile(r"\b(\d+\s?x\s?)?\d+(?:[.,]\d+)?\s?(?:ml|cl|l|ltr|litres?|liters?|g|kg|pints?|pt|oz|lb|pack|pk)\b\.?",
                       re.I)


def gtin(value: str) -> str | None:
    """The 13-digit code for a shop barcode or a typed number (EAN-13, UPC-A's 12 or EAN-8's 8 digits, spaces
    allowed), or None when it isn't one or the check digit is wrong. Ported to frontend/src/recipes/barcode.ts: change both
    together."""
    s = re.sub(r"[\s-]", "", value or "")
    if not re.fullmatch(r"\d{8}|\d{12,14}", s):
        return None
    if sum(int(ch) * (3 if i % 2 else 1) for i, ch in enumerate(reversed(s))) % 10:
        return None
    if len(s) == 14:
        if not s.startswith("0"):
            return None
        s = s[1:]
    return s.zfill(13) if len(s) == 12 else s


def _clean(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip(" ,-")


def _category(tag: str) -> str:
    """ "en:semi-skimmed-milks" -> "Semi skimmed milk"."""
    words = tag.split(":", 1)[-1].split("-")
    w = words[-1]
    if w in _MASS_NOUNS:
        words[-1] = w[:-3] + "y" if w.endswith("ies") else w[:-2] if re.search(r"(ch|sh|ss|x)es$", w) else w[:-1]
    return " ".join(words).capitalize()


def _plain(name: str, brand: str) -> str:
    """The product's name without its brand or size: "Tesco British Semi Skimmed Milk 2L" -> "British Semi Skimmed Milk"."""
    out = _QUANTITY.sub(" ", name)
    for b in filter(None, (brand, brand.split(" ")[0] if brand else "")):
        out = re.sub(rf"^\s*{re.escape(b)}('s)?\b", " ", out, flags=re.I)
    out = _clean(out)
    if out.isupper():
        out = out.capitalize()
    return out


def describe(p: dict) -> dict | None:
    """{exact, options, image_url} for an Open Food Facts product, or None when it has no name."""
    name = _clean(p.get("product_name_en") or p.get("product_name"))
    brand = _clean(str(p.get("brands") or "").split(",")[0])
    quantity = _clean(p.get("quantity"))
    tags = [t for t in p.get("categories_hierarchy") or [] if isinstance(t, str) and t.startswith("en:")]
    specific = p.get("compared_to_category") if isinstance(p.get("compared_to_category"), str) else None
    if specific and not specific.startswith("en:"):
        specific = None
    specific = specific or (tags[-1] if tags else None)
    if not name:
        name = _category(specific) if specific else ""
        if not name:
            return None
    exact = name.title() if name.isupper() else name
    if brand and brand.lower() not in name.lower():
        exact = f"{brand} {exact}"
    if quantity and not _QUANTITY.search(name) and len(quantity) <= 20:
        size = re.sub(r"(?<=\d) (?=[a-zA-Z]{1,2}$)", "", quantity)
        exact = f"{exact} {re.sub(r'(?<=\d)l$', 'L', size)}"
    # Plain words for it: the name without brand or size, its own category, and the broad family it's in (the
    # shortest category ending in the same word: "Semi skimmed milk" -> "Milk").
    options = [_plain(name, brand)]
    if specific:
        options.append(_category(specific))
        words = lambda t: t.split(":", 1)[-1].split("-")  # noqa: E731
        family = [t for t in tags if words(t)[-1] == words(specific)[-1] and not _TOO_BROAD & set(words(t))]
        if family:
            options.append(_category(min(family, key=len)))
    seen, plain = {exact.lower()}, []
    for o in options:
        if o and len(o) > 1 and o.lower() not in seen:
            seen.add(o.lower())
            plain.append(o[:120])
    plain.sort(key=len, reverse=True)  # from "Semi skimmed milk" down to "Milk"
    image = p.get("image_front_small_url") or p.get("image_front_url")
    return {"exact": exact[:160], "options": plain[:3],
            "image_url": image if isinstance(image, str) and image.startswith("https://") else None}


async def lookup(code: str) -> dict | None:
    """describe() for a 13-digit (or EAN-8) code, or None when no database knows the product."""
    for url in SOURCES:
        try:
            data, _ = await recipe_import.fetch(f"{url.format(code=code)}?fields={FIELDS}", MAX_ANSWER_BYTES)
            answer = json.loads(data)
        except (recipe_import.ImportError_, ValueError) as e:
            log.info("Looking up barcode %s at %s failed: %s", code, url, e)
            continue
        product = answer.get("product") if isinstance(answer, dict) and answer.get("status") == 1 else None
        found = describe(product) if isinstance(product, dict) else None
        if found:
            return found
    return None
