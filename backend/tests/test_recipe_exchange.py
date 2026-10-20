"""Recipe collections to and from Mela, Paprika and schema.org files."""
import base64
import gzip
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from moonlight import recipe_exchange
from moonlight.main import create_app

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "no-dist")
    with TestClient(app) as c:
        yield c


def _box(client):
    photo = client.post("/api/images", content=PNG).json()["id"]
    step_photo = client.post("/api/images", content=PNG + b"x").json()["id"]
    client.post("/api/recipes", json={
        "title": "Lasagne", "description": "Family favourite", "course": "main", "book": "Pasta Grannies", "photo": photo, "rating": 4, "favourite": True,
        "servings": 6, "prep_minutes": 30, "cook_minutes": 75, "tags": ["pasta", "oven"], "notes": "Freezes well",
        "url": "https://example.com/lasagne",
        "ingredients": ["For the sauce:", "500g beef mince", "1 onion", "For the topping:", "50g parmesan"],
        "steps": [{"text": "Brown the mince."}, {"text": "Bake for 45 minutes.", "photo": step_photo}],
    })
    client.post("/api/recipes", json={"title": "Toast", "ingredients": ["1 slice bread"], "steps": ["Toast it."]})


def _clear(client):
    for r in client.get("/api/recipes").json():
        client.delete(f"/api/recipes/{r['id']}")


@pytest.mark.parametrize("fmt", ["mela", "paprika", "schema"])
def test_round_trip(client, fmt):
    _box(client)
    res = client.get(f"/api/recipes/export?format={fmt}")
    assert res.status_code == 200 and "attachment" in res.headers["content-disposition"]
    data = res.content
    _clear(client)
    out = client.post("/api/recipes/collection", content=data).json()
    assert out == {"added": 2, "skipped": [], "failed": []}
    [lasagne, toast] = client.get("/api/recipes").json()
    assert lasagne["title"] == "Lasagne" and lasagne["photo"] and lasagne["servings"] == 6
    assert (lasagne["prep_minutes"], lasagne["cook_minutes"], lasagne["minutes"]) == (30, 75, 105)
    assert [i["text"] for i in lasagne["ingredients"]] == ["For the sauce:", "500g beef mince", "1 onion",
                                                           "For the topping:", "50g parmesan"]
    assert lasagne["ingredients"][0]["heading"] and [s["text"] for s in lasagne["steps"]] == ["Brown the mince.",
                                                                                              "Bake for 45 minutes."]
    assert sorted(lasagne["tags"]) == ["oven", "pasta"] and lasagne["notes"] == "Freezes well"
    assert lasagne["description"] == "Family favourite" and lasagne["url"] == "https://example.com/lasagne"
    if fmt == "mela":
        assert lasagne["favourite"]
    else:
        assert lasagne["rating"] == 4
    if fmt == "schema":
        assert lasagne["steps"][1]["photo"]  # step pictures travel too
    assert lasagne["course"] == "main" and lasagne["book"] == ("" if fmt == "mela" else "Pasta Grannies")
    assert toast["steps"][0]["text"] == "Toast it." and toast["course"] is None
    # Importing again skips what's already there.
    again = client.post("/api/recipes/collection", content=data).json()
    assert again["added"] == 0 and sorted(again["skipped"]) == ["Lasagne", "Toast"]


def test_reads_other_apps_files(client):
    paprika = {"name": "Scones", "ingredients": "225g flour\n50g butter", "directions": "1. Rub in.\n\n2. Bake.",
               "servings": "8 scones", "prep_time": "15 mins", "cook_time": "1 hr 5 min", "total_time": "",
               "categories": ["Baking"], "rating": 5, "photo_data": base64.b64encode(PNG).decode(),
               "notes": "", "source_url": ""}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Scones.paprikarecipe", gzip.compress(json.dumps(paprika).encode()))
        z.writestr("__MACOSX/._Scones.paprikarecipe", b"junk")
    assert client.post("/api/recipes/collection", content=buf.getvalue()).json()["added"] == 1
    # One Mela recipe on its own, headings marked with #.
    mela = {"id": "x", "title": "Curry", "text": "", "yield": "4", "prepTime": "10m", "cookTime": "1h30m",
            "totalTime": "", "ingredients": "# Paste\n2 garlic cloves\n# Curry\n400ml coconut milk",
            "instructions": "Blend.\nSimmer.", "images": [], "categories": [], "favorite": True}
    assert client.post("/api/recipes/collection", content=json.dumps(mela).encode()).json()["added"] == 1
    page = ('<html><script type="application/ld+json">{"@context":"https://schema.org","@type":"Recipe",'
            '"name":"Soup","recipeIngredient":["1 onion"],"recipeInstructions":"Chop."}</script></html>')
    assert client.post("/api/recipes/collection", content=page.encode()).json()["added"] == 1
    got = {r["title"]: r for r in client.get("/api/recipes").json()}
    scones, curry = got["Scones"], got["Curry"]
    assert scones["servings"] == 8 and (scones["prep_minutes"], scones["cook_minutes"]) == (15, 65)
    assert [s["text"] for s in scones["steps"]] == ["Rub in.", "Bake."] and scones["photo"] and scones["rating"] == 5
    assert [i["text"] for i in curry["ingredients"]] == ["Paste:", "2 garlic cloves", "Curry:", "400ml coconut milk"]
    assert curry["cook_minutes"] == 90 and curry["favourite"] and got["Soup"]["ingredients"][0]["text"] == "1 onion"
    bad = client.post("/api/recipes/collection", content=b"just some words")
    assert bad.status_code == 422 and "Mela" in bad.json()["detail"]
    assert client.get("/api/recipes/export?format=word").status_code == 400


def test_minutes():
    m = recipe_exchange.minutes
    assert [m("1 hr 30 mins"), m("1h30m"), m("45 minutes"), m("PT1H5M"), m("1:30"), m("20"), m(""), m("soon")] == \
        [90, 90, 45, 65, 90, 20, None, None]
