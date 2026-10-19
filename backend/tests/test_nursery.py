"""Nursery updates from Tapestry against a fake tapestryjournal.com (httpx.MockTransport): run from backend/ with
`python -m pytest`."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import db, tapestry  # noqa: E402
from moonlight.main import create_app  # noqa: E402

PIN = "4321"
EMAIL = "parent@example.com"
PASSWORD = "hunter2-tapestry"
TOKEN = "csrf-abc123"
CDN = "media.tapestry.test"

LOGIN_PAGE = f"""<!doctype html><html><head><title>Tapestry - Log In</title>
<meta name="csrf-token" content="{TOKEN}"></head><body>
<form class="search" action="/search" method="get"><input name="q"></form>
<form action="/login" method="POST">
  <input type="hidden" name="_token" value="{TOKEN}">
  <input type="email" name="email" id="email_generated_id">
  <input type="password" name="password" id="password_generated_id">
  <input type="checkbox" name="remember" value="1">
  <button type="submit">Log in</button>
</form></body></html>"""

JOURNAL_PAGE = """<!doctype html><html><head><title>Tapestry</title></head><body>
<div class="hidden">{"csrfToken":"api-token-xyz","user":{"id":5}}</div><div id="root"></div></body></html>"""

SCHOOLS_PAGE = """<!doctype html><html><body><h1>Choose a setting</h1>
<a href="/visit-school/101">Little Acorns Nursery</a>
<a href="/visit-school/202">Oak Lane Primary</a>
<a href="/logout">Log out</a></body></html>"""


def obs(i: int, **kw) -> dict:
    o = {"id": i, "title": f"Update {i}", "notes": f"<p>Notes for {i}</p>", "observationDate": f"2026-10-{i:02d} 10:30:00",
         "children": [{"id": 7, "fullName": "Rosie Standley"}], "mediaCount": 1, "media": [],
         "author": {"firstName": "Miss", "lastName": "Jones"}}
    o.update(kw)
    return o


class FakeTapestry:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.logins = 0
        self.down = False
        self.two_factor = False
        self.schools = False
        self.expired = False
        self.blocked = False
        self.chosen: str | None = None
        self.observations = [obs(12), obs(11, notes="Painted a <b>rainbow</b>&nbsp;today!<br>Very proud.")]
        self.details = {
            12: obs(12, notes="<p>Rosie built a tower of ten blocks.</p><p>She counted them all.</p>",
                    media=[{"id": 1, "type": "image", "url": f"https://{CDN}/xs/12-a.jpg?Signature=sig&Expires=1"},
                           {"id": 2, "type": "video/mp4", "url": f"https://{CDN}/xs/12-b.mp4?Signature=sig",
                            "thumbnailUrl": f"https://{CDN}/xs/12-b-thumb.jpg?Signature=sig"}],
                    mediaCount=2,
                    comments=[{"author": {"fullName": "Dad"}, "body": "<p>Brilliant!</p>", "createdAt": "2026-10-12T18:00:00"}]),
            11: obs(11, notes="Painted a <b>rainbow</b>&nbsp;today!<br>Very proud.", mediaCount=0),
        }

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if self.down:
            raise httpx.ConnectError("no route to host", request=req)
        if req.url.host == CDN:
            assert "cookie" not in req.headers  # the sign-in cookies never leave Tapestry
            if req.url.path.endswith(".mp4"):
                return httpx.Response(200, content=b"video", headers={"content-type": "video/mp4"})
            return httpx.Response(200, content=b"\xff\xd8JPEG" + req.url.path.encode(), headers={"content-type": "image/jpeg"})
        assert req.url.host == "tapestryjournal.com" and req.url.scheme == "https"
        path = req.url.path
        if self.blocked:
            return httpx.Response(403, html="<title>Just a moment...</title>",
                                  headers={"server": "cloudflare", "cf-mitigated": "challenge"})
        signed_in = req.headers.get("cookie", "").find("tapestry_session=good") >= 0
        if path == "/login" and req.method == "GET":
            return httpx.Response(200, html=LOGIN_PAGE, headers={"set-cookie": "tapestry_session=anon; Path=/; Secure"})
        if path == "/login" and req.method == "POST":
            form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            assert form["_token"] == TOKEN and "anon" in req.headers.get("cookie", "")
            if form.get("email") != EMAIL or form.get("password") != PASSWORD:
                return httpx.Response(302, headers={"location": "https://tapestryjournal.com/login"})
            self.logins += 1
            to = "/two-factor" if self.two_factor else "/select-school" if self.schools else "/s/little-acorns/observations"
            return httpx.Response(302, headers={"location": f"https://tapestryjournal.com{to}",
                                                "set-cookie": "tapestry_session=good; Path=/; Secure; HttpOnly"})
        if path == "/two-factor":
            return httpx.Response(200, html="<p>Enter the verification code from your authenticator app</p>")
        if path == "/select-school" and signed_in:
            return httpx.Response(200, html=SCHOOLS_PAGE)
        if path.startswith("/visit-school/") and signed_in:
            self.chosen = path.rsplit("/", 1)[1]
            return httpx.Response(302, headers={"location": "/s/oak-lane/observations"})
        if path.startswith("/s/") and signed_in:
            return httpx.Response(200, html=JOURNAL_PAGE)
        if path.startswith("/api/4/"):
            if not signed_in or self.expired:
                self.expired = False
                return httpx.Response(401, json={"message": "Unauthenticated."})
            assert req.headers["x-csrf-token"] == "api-token-xyz" and req.headers["x-tapestry-version"] == "3"
            if path == "/api/4/observations/list":
                return httpx.Response(200, json={"observations": self.observations, "nextCursor": None})
            if path.startswith("/api/4/observations/get/"):
                oid = int(path.rsplit("/", 1)[1])
                return httpx.Response(200, json={"observation": self.details[oid]})
        if not signed_in:
            return httpx.Response(302, headers={"location": "https://tapestryjournal.com/login"})
        return httpx.Response(404, text="not found")


@pytest.fixture
def fake(monkeypatch):
    f = FakeTapestry()
    monkeypatch.setattr(tapestry, "transport", httpx.MockTransport(f))
    return f


@pytest.fixture
def client(tmp_path, fake):
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "no-dist", auth_enabled=False)
    with TestClient(app) as c:
        assert c.patch("/api/settings", json={"pin": PIN}).status_code == 200
        yield c


def connect(c, **kw):
    r = c.put("/api/nursery", json={"pin": PIN, "email": EMAIL, "password": PASSWORD, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_not_connected(client):
    assert client.get("/api/nursery").json()["status"] == "unconfigured"
    assert client.get("/api/nursery/updates").json() == []
    assert client.post("/api/nursery/sync").status_code == 404


def test_connect_reads_updates_and_photos(client, fake, tmp_path):
    rosie = client.post("/api/people", json={"name": "Rosie", "color": "#F0679A", "role": "child"}).json()
    out = connect(client)
    assert out["status"] == "ok" and out["count"] == 2 and out["email"] == EMAIL
    assert PASSWORD not in client.get("/api/nursery").text
    ups = client.get("/api/nursery/updates").json()
    assert [u["id"] for u in ups] == ["12", "11"]
    first = ups[0]
    assert first["title"] == "Update 12" and first["author"] == "Miss Jones"
    assert first["notes"] == "Rosie built a tower of ten blocks.\nShe counted them all."
    assert first["date"] == "2026-10-12T10:30:00"
    assert first["children"] == [{"name": "Rosie Standley", "person_id": rosie["id"], "color": "#F0679A"}]
    assert first["comments"] == [{"author": "Dad", "date": "2026-10-12T18:00:00", "text": "Brilliant!"}]
    # The photo, and the video's still (the video itself isn't kept).
    assert [p["video"] for p in first["photos"]] == [False, True]
    r = client.get(first["photos"][0]["url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content.endswith(b"12-a.jpg")
    assert client.get(first["photos"][1]["url"]).content.endswith(b"12-b-thumb.jpg")
    assert (tmp_path / "nursery" / "12" / "0.jpg").is_file()
    assert ups[1]["notes"] == "Painted a rainbow today!\nVery proud." and ups[1]["photos"] == []
    assert client.get("/api/nursery/photos/12/5").status_code == 404
    assert client.get("/api/nursery/photos/..%2Ft.db/0").status_code == 404


def test_only_new_or_changed_updates_are_read_again(client, fake):
    connect(client)
    fake.requests.clear()
    assert client.post("/api/nursery/sync").json()["status"] == "ok"
    assert not [r for r in fake.requests if "/observations/get/" in r.url.path]
    fake.observations.insert(0, obs(13, title="Forest school"))
    fake.details[13] = obs(13, title="Forest school", notes="Splashing in puddles")
    fake.observations[2]["commentCount"] = 1  # 11 got a comment
    client.post("/api/nursery/sync")
    got = sorted(r.url.path for r in fake.requests if "/observations/get/" in r.url.path)
    assert got == ["/api/4/observations/get/11", "/api/4/observations/get/13"]
    assert client.get("/api/nursery/updates").json()[0]["title"] == "Forest school"


def test_wrong_password_and_two_factor(client, fake):
    r = client.put("/api/nursery", json={"pin": PIN, "email": EMAIL, "password": "nope"})
    assert r.status_code == 400 and "didn't accept" in r.json()["detail"] and "nope" not in r.text
    assert client.get("/api/nursery").json()["configured"] is False
    fake.two_factor = True
    r = client.put("/api/nursery", json={"pin": PIN, "email": EMAIL, "password": PASSWORD})
    assert r.status_code == 400 and "verification code" in r.json()["detail"]
    assert client.put("/api/nursery", json={"pin": "0000", "email": EMAIL, "password": PASSWORD}).status_code == 403


def test_blocked_sign_in_says_so_and_is_logged(client, fake, caplog):
    fake.blocked = True
    r = client.put("/api/nursery", json={"pin": PIN, "email": EMAIL, "password": PASSWORD})
    assert r.status_code == 502 and "blocked Moonlight as automated traffic" in r.json()["detail"]
    assert "Tapestry sign-in failed" in caplog.text and PASSWORD not in caplog.text


def test_session_lapse_signs_in_again(client, fake):
    connect(client)
    before = fake.logins
    fake.expired = True
    assert client.post("/api/nursery/sync").status_code == 200
    assert fake.logins == before + 1


def test_unreachable_keeps_updates(client, fake):
    connect(client)
    fake.down = True
    r = client.post("/api/nursery/sync")
    assert r.status_code == 502 and "Couldn't reach Tapestry" in r.json()["detail"]
    st = client.get("/api/nursery").json()
    assert st["status"] == "error" and st["count"] == 2
    assert len(client.get("/api/nursery/updates").json()) == 2


def test_choose_school(client, fake):
    fake.schools = True
    out = connect(client, school="oak lane")
    assert fake.chosen == "202" and out["school_name"] == "Oak Lane Primary"
    r = client.put("/api/nursery", json={"pin": PIN, "school": "Sunflowers"})  # password kept from before
    assert r.status_code == 400 and "Little Acorns Nursery, Oak Lane Primary" in r.json()["detail"]


def test_disconnect_forgets_everything(client, fake, tmp_path):
    connect(client)
    assert client.request("DELETE", "/api/nursery", json={"pin": PIN}).json() == {"ok": True}
    assert client.get("/api/nursery").json()["configured"] is False
    assert client.get("/api/nursery/updates").json() == []
    assert not (tmp_path / "nursery").exists()


def test_only_the_newest_are_kept(client, fake, monkeypatch):
    monkeypatch.setattr(tapestry, "KEEP", 1)
    connect(client)
    assert [u["id"] for u in client.get("/api/nursery/updates?limit=1").json()] == ["12"]
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM nursery_updates").fetchone()[0] == 1


def test_large_screens_get_the_nursery_section(client):
    s = client.get("/api/settings").json()
    assert "nursery" in s["screens"]["large"]["sections"]
    assert "nursery" not in s["screens"]["compact"]["sections"]


def test_plain_text():
    assert tapestry.plain_text("<ul><li>One</li><li>Two &amp; three</li></ul>") == "• One\n• Two & three"
    assert tapestry.plain_text("Fish &amp; chips") == "Fish & chips"
    assert tapestry.iso_time("2026-10-12") == "2026-10-12"
    assert tapestry.iso_time("12/10/2026 09:05") == "2026-10-12T09:05:00"
    assert tapestry.iso_time("nonsense") is None


def test_syncer_checks_in_the_background(tmp_path, fake, monkeypatch):
    db.configure(str(tmp_path / "bg.db"))
    db.init_db()
    with db.connect() as c:
        tapestry.save_config(c, EMAIL, PASSWORD, "")

    async def run():
        s = tapestry.Syncer()
        s.start()
        for _ in range(100):
            await asyncio.sleep(0.02)
            with db.connect() as c:
                if tapestry.config_out(c)["count"] == 2:
                    break
        await s.stop()

    asyncio.run(run())
    with db.connect() as c:
        assert tapestry.config_out(c)["status"] == "ok"


def test_existing_large_screens_get_the_section_once(tmp_path):
    import json
    import sqlite3
    path = str(tmp_path / "old.db")
    create_app(db_path=path, demo=False, static_dir=tmp_path / "x", auth_enabled=False)
    with sqlite3.connect(path) as c:
        c.execute("DELETE FROM settings WHERE key = ?", (db.NURSERY_MARKER,))
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('screens', ?)", (json.dumps(
            {"large": {"start": "meals", "sections": ["calendar", "meals"]},
             "compact": {"start": "today", "sections": ["today", "lists"]}}),))
        c.execute("INSERT INTO displays(id, name, layout, token_hash, created_at, revoked, setup) "
                  "VALUES('ds_1', 'Hall', 'large', 'h1', '2026-10-01', 0, ?)", (json.dumps({"sections": ["meals"]}),))
    db.init_db()
    with sqlite3.connect(path) as c:
        screens = json.loads(c.execute("SELECT value FROM settings WHERE key = 'screens'").fetchone()[0])
        assert screens["large"]["sections"] == ["calendar", "meals", "nursery"]
        assert screens["compact"]["sections"] == ["today", "lists"]
        assert json.loads(c.execute("SELECT setup FROM displays").fetchone()[0])["sections"] == ["meals", "nursery"]
        c.execute("UPDATE settings SET value = ? WHERE key = 'screens'",
                  (json.dumps({"large": {"start": "meals", "sections": ["meals"]}}),))
    db.init_db()  # hiding it later sticks
    with sqlite3.connect(path) as c:
        assert json.loads(c.execute("SELECT value FROM settings WHERE key = 'screens'").fetchone()[0])["large"]["sections"] == ["meals"]
