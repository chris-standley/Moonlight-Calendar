"""Recipes: fields, parsing ingredients and steps, pictures, importing, adding to a list, the photo reader key."""
import base64
import json

import pytest
from fastapi.testclient import TestClient

from moonlight import recipe_import, recipe_text
from moonlight.main import create_app

PIN = "1234"
# A 1x1 PNG.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "no-dist")
    with TestClient(app) as c:
        assert c.patch("/api/settings", json={"pin": PIN}).status_code == 200
        yield c


# ---------------------------------------------------------------- reading text

@pytest.mark.parametrize("line, q, q2, unit, name, note", [
    ("2 1/2 cups plain flour, sifted", 2.5, None, "cup", "plain flour", "sifted"),
    ("1½ tbsp olive oil", 1.5, None, "tbsp", "olive oil", ""),
    ("200g butter", 200, None, "g", "butter", ""),
    ("3-4 cloves garlic, crushed", 3, 4, "clove", "garlic", "crushed"),
    ("1 (400g) tin chopped tomatoes", 1, None, "tin", "chopped tomatoes", "400g"),
    ("2 large eggs", 2, None, "", "large eggs", ""),
    ("2 garlic cloves", 2, None, "", "garlic cloves", ""),
    ("Salt and pepper", None, None, "", "Salt and pepper", ""),
    ("1 fl oz rum", 1, None, "fl oz", "rum", ""),
    ("- 2 cups of milk", 2, None, "cup", "milk", ""),
])
def test_parse_ingredient(line, q, q2, unit, name, note):
    i = recipe_text.parse_ingredient(line)
    assert (i["quantity"], i["quantity_max"], i["unit"], i["name"], i["note"]) == (q, q2, unit, name, note)
    assert i["text"] == line.strip()


def test_metric_kept_alongside_original():
    assert recipe_text.parse_ingredient("8 oz cheddar")["metric"] == {"quantity": 226.8, "quantity_max": None, "unit": "g"}
    assert recipe_text.parse_ingredient("1-2 cups stock")["metric"] == {"quantity": 240, "quantity_max": 480, "unit": "ml"}
    assert recipe_text.parse_ingredient("2 tsp salt")["metric"] is None  # spoons are the same everywhere
    assert recipe_text.parse_ingredient("For the sauce:")["heading"] is True


def test_step_timers_and_conversions():
    t = "Bake at 350°F for 25-30 minutes, then rest for 1 hour 15 minutes."
    assert recipe_text.find_durations(t) == [1500, 4500]
    assert [x["label"] for x in recipe_text.step_timers(t, None)] == ["25 min", "1 h 15 min"]
    assert recipe_text.step_timers("Stir.", 5) == [{"seconds": 300, "label": "5 min"}]
    assert recipe_text.find_durations("Add 2 slices of bread") == []
    assert recipe_text.metric_note(t).startswith("Bake at 350°F (175°C)")
    assert recipe_text.metric_note("Grease a 9x13-inch pan and add 1 cup stock") == \
        "Grease a 9x13-inch (23 x 33 cm) pan and add 1 cup (240 ml) stock"
    assert recipe_text.metric_note("Bake at 180°C for 20 minutes") is None


def test_parse_text_from_a_photo():
    text = """Lemon Drizzle Cake
A family favourite for birthdays.
Serves 8
Prep 15 mins  Cook 45 mins
Ingredients
225g unsalted butter, softened
225g caster sugar
4 eggs
225g self-raising flour
1 lemon, zested
Method
1. Heat oven to 180C. Beat the butter and sugar until
pale and creamy.
2. Add the eggs one at a time, then fold in the flour
and zest.
3. Bake for 45 minutes."""
    d = recipe_text.parse_text(text)
    assert d["title"] == "Lemon Drizzle Cake"
    assert d["description"] == "A family favourite for birthdays."
    assert (d["servings"], d["prep_minutes"], d["cook_minutes"]) == (8, 15, 45)
    assert len(d["ingredients"]) == 5 and d["ingredients"][0] == "225g unsalted butter, softened"
    assert [s["text"] for s in d["steps"]] == [
        "Heat oven to 180C. Beat the butter and sugar until pale and creamy.",
        "Add the eggs one at a time, then fold in the flour and zest.",
        "Bake for 45 minutes.",
    ]


def test_schema_org_page():
    ld = {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, {
        "@type": "Recipe", "name": "Pancakes &amp; syrup", "recipeYield": ["4", "4 servings"],
        "prepTime": "PT10M", "cookTime": "PT20M", "keywords": "breakfast, easy",
        "image": [{"url": "https://example.com/p.jpg"}],
        "recipeIngredient": ["1 cup flour", "1 egg"],
        "recipeInstructions": [{"@type": "HowToSection", "name": "Batter", "itemListElement": [
            {"@type": "HowToStep", "text": "Whisk everything."}]}, {"@type": "HowToStep", "text": "Fry for 2 minutes."}],
    }]}
    page = f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head><body>x</body></html>'
    d, _ = recipe_import.read_page(page, "https://example.com/pancakes")
    assert d["title"] == "Pancakes & syrup" and d["servings"] == 4
    assert (d["prep_minutes"], d["cook_minutes"]) == (10, 20)
    assert d["ingredients"] == ["1 cup flour", "1 egg"]
    assert [s["text"] for s in d["steps"]] == ["Whisk everything.", "Fry for 2 minutes."]
    assert d["tags"] == ["breakfast", "easy"] and d["image_url"] == "https://example.com/p.jpg"
    none, text = recipe_import.read_page("<html><title>Blog</title><p>Just words</p></html>", "u")
    assert none is None and "Just words" in text


# ---------------------------------------------------------------- the API

def full_recipe(**over):
    return {"title": "Lemon cake", "emoji": "🍋", "description": "Zesty", "rating": 4, "favourite": True,
            "servings": 8, "prep_minutes": 15, "cook_minutes": 45, "tags": ["Baking", "baking", " cake "],
            "ingredients": ["225g butter", "1 cup sugar", "For the icing:", "100g icing sugar"],
            "steps": [{"text": "Beat the butter.", "minutes": None},
                      "Bake at 350°F for 45 minutes.", {"text": " ", "minutes": None}],
            "notes": "Freezes well", **over}


def test_recipe_round_trip(client):
    r = client.post("/api/recipes", json=full_recipe())
    assert r.status_code == 200, r.text
    rc = r.json()
    assert rc["minutes"] == 60 and rc["rating"] == 4 and rc["favourite"] is True and rc["tags"] == ["baking", "cake"]
    assert [i["unit"] for i in rc["ingredients"]] == ["g", "cup", "", "g"]
    assert rc["ingredients"][1]["metric"]["unit"] == "ml" and rc["ingredients"][2]["heading"]
    assert len(rc["steps"]) == 2
    assert rc["steps"][1]["timers"] == [{"seconds": 2700, "label": "45 min"}]
    assert rc["steps"][1]["metric_text"] == "Bake at 350°F (175°C) for 45 minutes."
    assert rc["created_at"] and rc["cooked_count"] == 0
    assert client.get(f"/api/recipes/{rc['id']}").json() == rc
    patched = client.patch(f"/api/recipes/{rc['id']}", json={"rating": 5, "favourite": False}).json()
    assert patched["rating"] == 5 and patched["favourite"] is False and patched["title"] == "Lemon cake"
    for bad in ({"rating": 6}, {"servings": 0}, {"steps": [{"text": "x", "minutes": -1}]}, {"photo": "img_nope"},
                {"favourite": "yes"}, {"tags": "cake"}):
        assert client.patch(f"/api/recipes/{rc['id']}", json=bad).status_code == 400, bad


def test_old_recipes_still_read(client):
    """Recipes saved before 0.5 (just title, emoji, minutes and ingredient lines) keep working."""
    from moonlight import db
    with db.connect() as c:
        c.execute("INSERT INTO recipes(id, title, emoji, minutes, ingredients, url) VALUES('rc_old', 'Soup', '🥣', 20, "
                  "'[\"1 onion\"]', NULL)")
    rc = client.get("/api/recipes/rc_old").json()
    assert rc["minutes"] == 20 and rc["ingredients"][0]["quantity"] == 1 and rc["steps"] == [] and rc["rating"] == 0


def test_pictures(client):
    img = client.post("/api/images", content=PNG, headers={"Content-Type": "image/png"}).json()
    assert img["url"] == f"/api/images/{img['id']}"
    got = client.get(img["url"])
    assert got.content == PNG and got.headers["content-type"] == "image/png"
    assert client.post("/api/images", content=b"not a picture").status_code == 400
    rc = client.post("/api/recipes", json=full_recipe(photo=img["id"], steps=[{"text": "", "photo": img["id"]}])).json()
    assert rc["photo_url"] == img["url"] and rc["steps"][0]["photo_url"] == img["url"]


def test_unused_pictures_are_tidied(client):
    from moonlight import db
    keep = client.post("/api/images", content=PNG).json()["id"]
    drop = client.post("/api/images", content=PNG).json()["id"]
    fresh = client.post("/api/images", content=PNG).json()["id"]
    with db.connect() as c:
        c.execute("UPDATE images SET created_at = '2020-01-01T00:00:00' WHERE id IN (?, ?)", (keep, drop))
    client.post("/api/recipes", json=full_recipe(photo=keep))
    with db.connect() as c:
        left = {r[0] for r in c.execute("SELECT id FROM images")}
    assert left == {keep, fresh}


def test_to_list_with_chosen_items_and_cooked(client):
    rc = client.post("/api/recipes", json=full_recipe()).json()
    lid = client.post("/api/lists", json={"name": "Shop", "kind": "grocery"}).json()["id"]
    assert client.post(f"/api/recipes/{rc['id']}/to-list", json={"list_id": lid}).json() == {"added": 3}  # not the heading
    r = client.post(f"/api/recipes/{rc['id']}/to-list", json={"list_id": lid, "items": ["450g butter", " "]})
    assert r.json() == {"added": 1}
    assert "450g butter" in [i["title"] for i in client.get(f"/api/lists/{lid}/items").json()]
    done = client.post(f"/api/recipes/{rc['id']}/cooked", json={"date": "2026-10-01"}).json()
    assert done["cooked_count"] == 1 and done["last_cooked"] == "2026-10-01"
    done = client.post(f"/api/recipes/{rc['id']}/cooked", json={"date": "2026-09-01"}).json()
    assert done["cooked_count"] == 2 and done["last_cooked"] == "2026-10-01"


def test_preview_and_text_import(client):
    p = client.post("/api/recipes/preview", json={"ingredients": ["2 cups rice"], "steps": ["Cook 12 minutes"]}).json()
    assert p["id"] is None and p["ingredients"][0]["metric"]["quantity"] == 480 and p["steps"][0]["timers"][0]["seconds"] == 720
    d = client.post("/api/recipes/import", json={"text": "Toast\nIngredients\n2 slices bread\nMethod\nToast for 3 minutes."})
    assert d.status_code == 200, d.text
    d = d.json()
    assert d["id"] is None and d["title"] == "Toast" and d["ingredients"][0]["quantity"] == 2
    assert client.post("/api/recipes/import", json={"text": "  "}).status_code == 400
    assert client.post("/api/recipes/import", json={"text": "hello"}).status_code == 422


def test_url_import(client, monkeypatch):
    ld = {"@type": "Recipe", "name": "Soup", "recipeIngredient": ["1 onion"], "recipeInstructions": "Simmer.",
          "image": "https://example.com/soup.png"}
    pages = {"https://example.com/soup": f'<script type="application/ld+json">{json.dumps(ld)}</script>'.encode(),
             "https://example.com/soup.png": PNG, "https://example.com/blog": b"<p>no recipe data</p>"}

    async def fake_fetch(url, limit=0):
        return pages[url], ""
    monkeypatch.setattr(recipe_import, "fetch", fake_fetch)
    d = client.post("/api/recipes/import", json={"url": "https://example.com/soup"}).json()
    assert d["title"] == "Soup" and d["url"] == "https://example.com/soup" and d["photo_url"].startswith("/api/images/")
    r = client.post("/api/recipes/import", json={"url": "https://example.com/blog"})
    assert r.status_code == 422 and "paste" in r.json()["detail"]


def test_photo_import_needs_the_reader(client, monkeypatch):
    img = client.post("/api/images", content=PNG).json()["id"]
    r = client.post("/api/recipes/import", json={"images": [img]})
    assert r.status_code == 409 and "Settings" in r.json()["detail"]
    assert client.put("/api/recipes-reader", json={"pin": "0000", "api_key": "sk-ant-x"}).status_code == 403
    assert client.put("/api/recipes-reader", json={"pin": PIN, "api_key": "nope"}).status_code == 400
    out = client.put("/api/recipes-reader", json={"pin": PIN, "api_key": "sk-ant-test-abcd"}).json()
    assert out == {"configured": True, "model": "claude-opus-5-5", "key_hint": "…abcd"}
    assert "sk-ant" not in json.dumps(client.get("/api/settings").json())
    seen = {}

    async def fake_reader(key, model, images=None, text=None):
        seen.update(key=key, n=len(images or []))
        return {"title": "Read", "description": "", "servings": 2, "prep_minutes": None, "cook_minutes": None,
                "minutes": None, "ingredients": ["1 cup oats"], "steps": [{"text": "Soak overnight.", "minutes": None}],
                "tags": ["breakfast"], "notes": ""}
    monkeypatch.setattr(recipe_import, "read_with_claude", fake_reader)
    d = client.post("/api/recipes/import", json={"images": [img, img]}).json()
    assert seen == {"key": "sk-ant-test-abcd", "n": 2} and d["title"] == "Read" and d["servings"] == 2
    assert client.request("DELETE", "/api/recipes-reader", json={"pin": PIN}).json()["configured"] is False


def test_step_uses_names_the_ingredients_a_step_mentions():
    ings = [recipe_text.parse_ingredient(t) for t in [
        "225g unsalted butter, softened", "2 large eggs", "1 red onion, finely chopped", "2 spring onions",
        "6 chicken thighs, sliced", "100g blueberries", "2 peppers, sliced", "Salt and pepper"]]
    uses = lambda t: recipe_text.step_uses(t, ings)  # noqa: E731
    assert uses("Beat the butter, then add the eggs one at a time.") == [0, 1]
    assert uses("Toss the chicken thigh with the red onion.") == [4, 2]   # plural/singular, order of mention
    assert uses("Fry the onion.") == []                                   # two kinds of onion: not guessed
    assert uses("Scatter over the spring onions and a blueberry.") == [3, 5]
    assert uses("Season with salt and pepper.") == []                     # not the peppers, no amount for the salt


def test_scanning_a_cookbook(client, monkeypatch):
    import time

    from moonlight import recipe_batch

    def piece(title, ings, steps, continues=False):
        return {"title": title, "description": "", "servings": None, "prep_minutes": None, "cook_minutes": None,
                "minutes": None, "ingredients": ings, "steps": [{"text": s, "minutes": None} for s in steps],
                "tags": [], "notes": "", "continues": continues}

    book = {  # page bytes end in their number; page 2 is a photo; soup runs over onto page 4; page 5 fails once
        b"0": [piece("Pancakes", ["100g flour"], ["Whisk."]), piece("Toast", ["1 slice bread"], ["Toast it."])],
        b"1": [],
        b"2": [piece("Soup", ["1 onion"], ["Chop."])],
        b"3": [piece("", ["1 litre stock"], ["Simmer for 20 minutes."], continues=True)],
        b"4": "busy",
    }
    calls = []

    async def fake_page(key, model, image):
        n = image[1][-1:]
        calls.append(n)
        if book[n] == "busy":
            book[n] = [piece("Cake", ["2 eggs"], ["Bake."])]
            raise recipe_import.Busy("busy")
        return book[n]

    async def no_wait(_):
        return None

    monkeypatch.setattr(recipe_import, "read_cookbook_page", fake_page)
    monkeypatch.setattr(recipe_batch, "_wait", no_wait)
    imgs = [client.post("/api/images", content=PNG + bytes([48 + i])).json()["id"] for i in range(5)]
    assert client.post("/api/recipes-batches", json={"images": imgs}).status_code == 409  # needs the reader
    client.put("/api/recipes-reader", json={"pin": PIN, "api_key": "sk-ant-test-abcd"})
    b = client.post("/api/recipes-batches", json={"images": imgs}).json()
    assert b["pages"] == 5
    for _ in range(100):
        [b] = client.get("/api/recipes-batches").json()
        if not b["reading"]:
            break
        time.sleep(0.02)
    assert b["read"] == 5 and b["failed"] == [] and calls.count(b"4") == 2
    found = {d["recipe"]["title"]: d for d in b["drafts"]}
    assert list(found) == ["Pancakes", "Toast", "Soup", "Cake"]
    soup = found["Soup"]
    assert soup["pages"] == [3, 4] and [i["text"] for i in soup["recipe"]["ingredients"]] == ["1 onion", "1 litre stock"]
    assert soup["recipe"]["steps"][1]["timers"]

    # Save one as edited, put one aside, then save the rest; the scan is gone once all are dealt with.
    body = {**{k: soup["recipe"][k] for k in ("description", "servings", "tags", "notes")}, "title": "Onion soup",
            "ingredients": ["1 onion", "1 litre stock"], "steps": [{"text": "Simmer."}]}
    assert client.post(f"/api/recipe-drafts/{soup['id']}/save", json=body).json()["title"] == "Onion soup"
    assert client.post(f"/api/recipe-drafts/{soup['id']}/save").status_code == 404
    assert client.delete(f"/api/recipe-drafts/{found['Toast']['id']}").status_code == 200
    assert client.post(f"/api/recipes-batches/{b['id']}/save-all").json() == {"saved": 2}
    assert client.get("/api/recipes-batches").json() == []
    assert sorted(r["title"] for r in client.get("/api/recipes").json()) == ["Cake", "Onion soup", "Pancakes"]


def test_scanning_a_cookbook_cheaper(client, monkeypatch):
    """Sent as one Anthropic Message Batch: checked on until it ends, failed pages sent again as a new batch."""
    import asyncio
    import time

    from moonlight import recipe_batch

    def piece(title):
        return {"title": title, "description": "", "servings": None, "prep_minutes": None, "cook_minutes": None,
                "minutes": None, "ingredients": ["1 egg"], "steps": [{"text": "Cook.", "minutes": None}], "tags": [],
                "notes": "", "continues": False}

    sent, checks, cancelled = [], [], []

    async def submit(key, model, pages):
        sent.append([p for p, _ in pages])
        return f"msgbatch_{len(sent)}"

    async def results(key, aid):
        checks.append(aid)
        if len(checks) == 1 or aid == "msgbatch_3":
            return None  # still reading
        if aid == "msgbatch_1":
            return {0: ([piece("Omelette")], None), 1: (None, "Anthropic couldn't read this page. Try again.")}
        return {1: ([piece("Frittata")], None)}

    async def cancel(key, aid):
        cancelled.append(aid)

    async def no_wait(_):
        await asyncio.sleep(0.005)

    monkeypatch.setattr(recipe_import, "submit_pages", submit)
    monkeypatch.setattr(recipe_import, "batch_results", results)
    monkeypatch.setattr(recipe_import, "cancel_batch", cancel)
    monkeypatch.setattr(recipe_batch, "_wait", no_wait)
    client.put("/api/recipes-reader", json={"pin": PIN, "api_key": "sk-ant-test-abcd"})
    imgs = [client.post("/api/images", content=PNG + bytes([48 + i])).json()["id"] for i in range(2)]

    def settled():
        for _ in range(100):
            [b] = client.get("/api/recipes-batches").json()
            if not b["reading"]:
                return b
            time.sleep(0.02)
        raise AssertionError("still reading")

    b = client.post("/api/recipes-batches", json={"images": imgs, "cheaper": True}).json()
    assert b["cheaper"] is True
    b = settled()
    assert sent == [[0, 1]] and checks[:2] == ["msgbatch_1", "msgbatch_1"]
    assert b["failed"] == [{"page": 2, "error": "Anthropic couldn't read this page. Try again."}]
    assert [d["recipe"]["title"] for d in b["drafts"]] == ["Omelette"]

    client.post(f"/api/recipes-batches/{b['id']}/retry")
    b = settled()
    assert sent[1] == [1] and b["failed"] == [] and [d["recipe"]["title"] for d in b["drafts"]] == ["Omelette", "Frittata"]

    # Clearing a scan while Anthropic still has it cancels the Anthropic batch.
    b = client.post("/api/recipes-batches", json={"images": imgs[:1], "cheaper": True}).json()
    for _ in range(100):
        if "msgbatch_3" in checks:
            break
        time.sleep(0.02)
    client.delete(f"/api/recipes-batches/{b['id']}")
    for _ in range(100):
        if cancelled:
            break
        time.sleep(0.02)
    assert cancelled == ["msgbatch_3"]


def test_reading_anthropic_batch_results(monkeypatch):
    """batch_results against the SDK's shapes: pages matched by custom_id, each kind of result explained."""
    import asyncio
    from types import SimpleNamespace as NS

    import anthropic

    page = json.dumps({"recipes": [{"continues_previous_page": False, "title": "Scones", "description": "",
                                     "servings": 8, "prep_minutes": None, "cook_minutes": 12,
                                     "ingredients": ["225g flour"], "steps": [{"text": "Bake.", "minutes": 12}],
                                     "tags": [], "notes": ""}]})
    lines = [
        NS(custom_id="page-3", result=NS(type="succeeded", message=NS(stop_reason="end_turn",
                                                                      content=[NS(type="text", text=page)]))),
        NS(custom_id="page-4", result=NS(type="succeeded", message=NS(stop_reason="refusal", content=[]))),
        NS(custom_id="page-5", result=NS(type="errored", error=NS(type="error"))),
        NS(custom_id="page-6", result=NS(type="expired")),
    ]

    class Results:
        def __aiter__(self):
            async def gen():
                for line in lines:
                    yield line
            return gen()

    status = {"now": "in_progress"}

    class Batches:
        async def retrieve(self, aid):
            return NS(processing_status=status["now"])

        async def results(self, aid):
            return Results()

    class Client:
        def __init__(self, **_):
            self.messages = NS(batches=Batches())

    monkeypatch.setattr(anthropic, "AsyncAnthropic", Client)
    assert asyncio.run(recipe_import.batch_results("k", "b")) is None
    status["now"] = "ended"
    out = asyncio.run(recipe_import.batch_results("k", "b"))
    assert out[3][0][0]["title"] == "Scones" and out[3][0][0]["continues"] is False
    assert out[4][0] is None and "declined" in out[4][1]
    assert out[5] == (None, "Anthropic couldn't read this page. Try again.")
    assert "within a day" in out[6][1]


def test_course_and_cookbook(client):
    r = client.post("/api/recipes", json={"title": "Eton mess", "course": "dessert", "book": "Simple", "book_page": 212})
    assert (r.json()["course"], r.json()["book"], r.json()["book_page"]) == ("dessert", "Simple", 212)
    assert client.post("/api/recipes", json={"title": "X", "course": "elevenses"}).status_code == 400
    rid = r.json()["id"]
    assert client.patch(f"/api/recipes/{rid}", json={"course": None}).json()["course"] is None
    assert [recipe_text.course_from(t) for t in (["Main course"], ["vegan", "Desserts"], ["Light bites"], ["quick"])] == \
        ["main", "dessert", "light", None]
    page = ('<script type="application/ld+json">{"@type":"Recipe","name":"Soup","recipeCategory":"Starter",'
            '"recipeIngredient":["1 onion"],"recipeInstructions":"Chop."}</script>')
    draft, _ = recipe_import.read_page(page, "https://example.com/soup")
    assert draft["course"] == "starter"


def test_cookbook_scan_names_the_book(client, monkeypatch):
    import time

    async def fake_page(key, model, image):
        return [{"title": "Scones", "description": "", "servings": None, "prep_minutes": None, "cook_minutes": None,
                 "minutes": None, "ingredients": ["225g flour"], "steps": [{"text": "Bake.", "minutes": None}],
                 "tags": [], "notes": "", "course": "baking", "book_page": 88, "continues": False}]

    monkeypatch.setattr(recipe_import, "read_cookbook_page", fake_page)
    client.put("/api/recipes-reader", json={"pin": PIN, "api_key": "sk-ant-test-abcd"})
    img = client.post("/api/images", content=PNG).json()["id"]
    b = client.post("/api/recipes-batches", json={"images": [img], "book": "Bake Off"}).json()
    assert b["book"] == "Bake Off"
    for _ in range(100):
        [b] = client.get("/api/recipes-batches").json()
        if b["drafts"]:
            break
        time.sleep(0.02)
    rec = b["drafts"][0]["recipe"]
    assert (rec["book"], rec["book_page"], rec["course"]) == ("Bake Off", 88, "baking")
    client.post(f"/api/recipes-batches/{b['id']}/save-all")
    [saved] = client.get("/api/recipes").json()
    assert (saved["book"], saved["book_page"], saved["course"]) == ("Bake Off", 88, "baking")


def test_isbn13():
    from moonlight.cookbooks import isbn13

    assert isbn13("978-1-78503-399-5") == "9781785033995"
    assert isbn13("0 7432 7356 7") == "9780743273565"  # an ISBN-10 becomes the 978 ISBN-13
    assert isbn13("080442957X") == "9780804429573"
    assert isbn13("9781785033994") is None  # wrong check digit
    assert isbn13("5012345678900") is None  # a supermarket barcode, not a book
    assert isbn13("") is None


def test_cookbook_found_by_barcode(client, monkeypatch):
    import time

    from moonlight import cookbooks

    isbn = "9781785033995"
    answers = {
        cookbooks.OPEN_LIBRARY.format(isbn=isbn): json.dumps({f"ISBN:{isbn}": {
            "title": "Simple", "subtitle": "Effortless food, big flavours", "authors": [{"name": "Yotam Ottolenghi"}],
            "publishers": [{"name": "Ebury Press"}], "publish_date": "Sep 06, 2018",
            "cover": {"large": "https://covers.openlibrary.org/b/id/1-L.jpg"}}}).encode(),
        "https://covers.openlibrary.org/b/id/1-L.jpg": PNG,
    }
    asked = []

    async def fake_fetch(url, limit=0):
        asked.append(url)
        if url not in answers:
            raise recipe_import.ImportError_("That page answered with error 404.")
        return answers[url], ""
    monkeypatch.setattr(recipe_import, "fetch", fake_fetch)

    assert client.get("/api/cookbooks/12345").status_code == 400
    book = client.get("/api/cookbooks/978-1-78503-399-5").json()
    assert (book["isbn"], book["title"], book["authors"], book["publisher"], book["year"]) == \
        (isbn, "Simple: Effortless food, big flavours", "Yotam Ottolenghi", "Ebury Press", 2018)
    assert client.get(book["cover_url"]).content == PNG
    n = len(asked)
    assert client.get(f"/api/cookbooks/{isbn}").json()["title"] == book["title"]
    assert len(asked) == n  # kept: not looked up again

    # Unknown to Open Library: Google Books is asked next; unknown to both is a 404.
    other = "9780743273565"
    answers[cookbooks.OPEN_LIBRARY.format(isbn=other)] = b"{}"
    answers[cookbooks.GOOGLE_BOOKS.format(isbn=other)] = json.dumps({"items": [{"volumeInfo": {
        "title": "The Great Gatsby", "authors": ["F. Scott Fitzgerald"], "publishedDate": "2004"}}]}).encode()
    g = client.get(f"/api/cookbooks/{other}").json()
    assert (g["title"], g["authors"], g["year"], g["cover_url"]) == ("The Great Gatsby", "F. Scott Fitzgerald", 2004, None)
    assert client.get("/api/cookbooks/9780804429573").status_code == 404

    # A scan given the book's ISBN files every recipe under its title.
    async def fake_page(key, model, image):
        return [{"title": "Hummus", "description": "", "servings": None, "prep_minutes": None, "cook_minutes": None,
                 "minutes": None, "ingredients": ["1 tin chickpeas"], "steps": [{"text": "Blend.", "minutes": None}],
                 "tags": [], "notes": "", "course": "starter", "book_page": 12, "continues": False}]
    monkeypatch.setattr(recipe_import, "read_cookbook_page", fake_page)
    client.put("/api/recipes-reader", json={"pin": PIN, "api_key": "sk-ant-test-abcd"})
    img = client.post("/api/images", content=PNG).json()["id"]
    b = client.post("/api/recipes-batches", json={"images": [img], "isbn": isbn}).json()
    assert b["book"] == book["title"]
    for _ in range(100):
        [b] = client.get("/api/recipes-batches").json()
        if b["drafts"]:
            break
        time.sleep(0.02)
    client.post(f"/api/recipes-batches/{b['id']}/save-all")
    [saved] = client.get("/api/recipes").json()
    assert saved["book"] == book["title"]
    listed = {x["isbn"]: x for x in client.get("/api/cookbooks").json()}
    assert listed[isbn]["recipes"] == 1 and listed[other]["recipes"] == 0

    # Typing a different name over the found one renames the book and its recipes.
    img = client.post("/api/images", content=PNG).json()["id"]
    b2 = client.post("/api/recipes-batches", json={"images": [img], "isbn": isbn, "book": "Simple"}).json()
    assert b2["book"] == "Simple"
    assert client.get("/api/recipes").json()[0]["book"] == "Simple"
    assert {x["isbn"]: x for x in client.get("/api/cookbooks").json()}[isbn]["title"] == "Simple"
