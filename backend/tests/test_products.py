"""Shop products found by their barcode for the shopping list: the exact product or the plain item."""
import json

import pytest
from fastapi.testclient import TestClient

from moonlight import products, recipe_import
from moonlight.main import create_app

MILK = "5000436589877"


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "no-dist")
    with TestClient(app) as c:
        yield c


def test_gtin():
    assert products.gtin("5000436589877") == MILK
    assert products.gtin("5 000436 589877") == MILK
    assert products.gtin("012345678905") == "0012345678905"  # a UPC-A from America gets its leading 0
    assert products.gtin("00012345678905") == "0012345678905"  # GTIN-14 with a leading 0
    assert products.gtin("96385074") == "96385074"  # EAN-8 on small packs
    assert products.gtin("5000436589878") is None  # wrong check digit
    assert products.gtin("12345") is None
    assert products.gtin("") is None


@pytest.mark.parametrize("product, exact, options", [
    ({"product_name": "Semi Skimmed Milk", "brands": "Tesco,Tesco Stores", "quantity": "2 l",
      "categories_hierarchy": ["en:dairies", "en:milks", "en:semi-skimmed-milks"], "compared_to_category": "en:semi-skimmed-milks"},
     "Tesco Semi Skimmed Milk 2L", ["Semi Skimmed Milk", "Milk"]),
    ({"product_name": "TESCO BRITISH SEMI SKIMMED MILK 4 PINTS", "brands": "Tesco", "quantity": "2.272 L",
      "categories_hierarchy": ["en:dairies", "en:milks", "en:semi-skimmed-milks"]},
     "Tesco British Semi Skimmed Milk 4 Pints", ["British semi skimmed milk", "Semi skimmed milk", "Milk"]),
    ({"product_name": "Ready Salted Crisps", "brands": "Walkers", "quantity": "6 x 25 g",
      "categories_hierarchy": ["en:snacks", "en:salty-snacks", "en:crisps", "en:potato-crisps"]},
     "Walkers Ready Salted Crisps 6 x 25g", ["Ready Salted Crisps", "Potato crisps", "Crisps"]),
    ({"product_name": "Mature Cheddar", "brands": "Cathedral City", "quantity": "350g",
      "categories_hierarchy": ["en:dairies", "fr:fromages", "en:cheeses", "en:cheddar-cheeses"]},
     "Cathedral City Mature Cheddar 350g", ["Mature Cheddar", "Cheddar cheese", "Cheese"]),
    ({"product_name": "", "categories_hierarchy": ["en:beverages", "en:squashes"]}, "Squash", []),
])
def test_exact_and_plain_names(product, exact, options):
    d = products.describe(product)
    assert (d["exact"], d["options"]) == (exact, options)


def test_no_name_is_no_product():
    assert products.describe({"brands": "Tesco"}) is None


def test_scanning_a_barcode_onto_the_shopping_list(client, monkeypatch):
    asked = []
    answer = {"status": 1, "product": {
        "product_name": "Semi Skimmed Milk", "brands": "Tesco", "quantity": "2 l",
        "categories_hierarchy": ["en:dairies", "en:milks", "en:semi-skimmed-milks"],
        "image_front_small_url": "https://images.openfoodfacts.org/images/products/500/043/658/9877/front_en.3.200.jpg"}}

    async def fake_fetch(url, limit=0):
        asked.append(url)
        if MILK in url and "openfoodfacts" in url:
            return json.dumps(answer).encode(), "application/json"
        return json.dumps({"status": 0, "status_verbose": "product not found"}).encode(), "application/json"
    monkeypatch.setattr(recipe_import, "fetch", fake_fetch)

    assert client.get("/api/products/12345").status_code == 400
    p = client.get(f"/api/products/{MILK}").json()
    assert p == {"code": MILK, "found": True, "exact": "Tesco Semi Skimmed Milk 2L",
                 "options": ["Semi Skimmed Milk", "Milk"], "image_url": answer["product"]["image_front_small_url"],
                 "last": None}
    # Found once, kept: the next scan doesn't ask again.
    n = len(asked)
    assert client.get(f"/api/products/{MILK}").json()["exact"] == p["exact"]
    assert len(asked) == n

    shop = client.post("/api/lists", json={"name": "Shopping", "kind": "grocery"}).json()
    assert client.post(f"/api/lists/{shop['id']}/items", json={"title": "Milk", "barcode": "123"}).status_code == 400
    item = client.post(f"/api/lists/{shop['id']}/items", json={"title": "Milk", "barcode": MILK}).json()
    assert item["title"] == "Milk"
    assert client.get(f"/api/products/{MILK}").json()["last"] == "Milk"

    # Unknown everywhere: not found, but what the family called it is remembered.
    other = "96385074"
    q = client.get(f"/api/products/{other}").json()
    assert (q["found"], q["exact"], q["options"], q["last"]) == (False, None, [], None)
    assert len([u for u in asked if other in u]) == len(products.SOURCES)
    client.post(f"/api/lists/{shop['id']}/items", json={"title": "Kitchen roll", "barcode": other})
    q = client.get(f"/api/products/{other}").json()
    assert (q["found"], q["last"]) == (False, "Kitchen roll")
