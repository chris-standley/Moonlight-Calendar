"""Immich photo screensaver against a fake Immich (httpx.MockTransport): run from backend/ with `python -m pytest`."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import immich  # noqa: E402
from moonlight.main import create_app  # noqa: E402

PIN = "4321"
KEY = "immich-secret-key-ABC123xyz"
URL = "http://immich.test:2283"


def uid() -> str:
    return str(uuid.uuid4())


def asset(kind="IMAGE", **kw) -> dict:
    a = {"id": uid(), "type": kind, "width": 4032, "height": 3024, "isTrashed": False, "isFavorite": False,
         "visibility": "timeline", "localDateTime": "2025-07-14T15:30:00.000Z", "originalFileName": "IMG.jpg"}
    a.update(kw)
    return a


class FakeImmich:
    """Just enough of the Immich API (v3.3) for Moonlight."""

    def __init__(self) -> None:
        self.down = False
        self.flat_rejected = False  # a future server without the deprecated search fields
        self.page_size_override: int | None = None
        self.requests: list[httpx.Request] = []
        self.holiday, self.garden, self.private = uid(), uid(), uid()
        self.photos = {
            self.holiday: [asset() for _ in range(3)] + [asset("VIDEO"), asset(isTrashed=True)],
            self.garden: [asset(width=3024, height=4032), asset(visibility="locked")],
            self.private: [asset(), asset()],
        }
        self.names = {self.holiday: "Holiday 2025", self.garden: "Garden", self.private: "Private"}
        self.favs = [asset(isFavorite=True), asset("VIDEO", isFavorite=True)]
        self.memory = [asset(), asset("VIDEO")]

    def all_assets(self):
        return [a for xs in self.photos.values() for a in xs] + self.favs + self.memory

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if self.down:
            raise httpx.ConnectError("connection refused", request=req)
        assert req.url.host == "immich.test"
        path = req.url.path
        if path == "/api/server/version":
            return httpx.Response(200, json={"major": 3, "minor": 3, "patch": 1, "prerelease": None})
        if req.headers.get("x-api-key") != KEY:
            return httpx.Response(401, json={"message": "Invalid API key", "statusCode": 401})
        if path == "/api/albums" and req.method == "GET":
            return httpx.Response(200, json=[
                {"id": k, "albumName": self.names[k], "assetCount": len(v), "shared": False, "albumThumbnailAssetId": None}
                for k, v in self.photos.items()])
        if path == "/api/search/metadata" and req.method == "POST":
            return self.search(json.loads(req.content))
        if path == "/api/memories":
            assert req.url.params["type"] == "on_this_day" and len(req.url.params["for"]) == 10
            return httpx.Response(200, json=[{"id": uid(), "type": "on_this_day", "data": {"year": 2020},
                                              "assets": self.memory}])
        if path.startswith("/api/assets/") and path.endswith("/thumbnail"):
            aid = path.split("/")[3]
            assert req.url.params["size"] == "preview"
            if not any(a["id"] == aid for a in self.all_assets()):
                return httpx.Response(404, json={"message": "Not found"})
            return httpx.Response(200, content=b"\xff\xd8JPEG-" + aid.encode(), headers={"content-type": "image/jpeg"})
        return httpx.Response(404, json={"message": f"no route {path}"})

    def search(self, body: dict) -> httpx.Response:
        if "filter" in body:
            f = body["filter"]
            album = (f.get("albumIds") or {}).get("any", [None])[0]
            fav = (f.get("isFavorite") or {}).get("eq")
            kind = (f.get("type") or {}).get("eq")
            start = int(body.get("cursor") or 0)
        else:
            if self.flat_rejected:
                return httpx.Response(400, json={"message": ["property albumIds should not exist"]})
            album = (body.get("albumIds") or [None])[0]
            fav = body.get("isFavorite")
            kind = body.get("type")
            start = (int(body.get("page") or 1) - 1) * (self.page_size_override or int(body["size"]))
        items = self.photos.get(album, []) if album else (self.favs if fav else self.all_assets())
        if kind:  # like Immich: the type filter is applied server side
            items = [a for a in items if a["type"] == kind]
        size = self.page_size_override or int(body["size"])
        page = items[start:start + size]
        more = start + size < len(items)
        nxt = start + size
        return httpx.Response(200, json={"albums": {"items": [], "total": 0, "count": 0, "facets": []}, "assets": {
            "items": page, "total": len(page), "count": len(page), "facets": [],
            "nextPage": str(nxt // size + 1) if more and "filter" not in body else None,
            "nextCursor": str(nxt) if more and "filter" in body else None}})


@pytest.fixture
def fake(monkeypatch):
    f = FakeImmich()
    monkeypatch.setattr(immich, "transport", httpx.MockTransport(f))
    return f


@pytest.fixture
def client(tmp_path, fake):
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "no-dist", auth_enabled=False)
    with TestClient(app) as c:
        assert c.patch("/api/settings", json={"pin": PIN}).status_code == 200
        yield c


def connect(c, fake, **kw):
    body = {"pin": PIN, "server_url": URL + "/api/", "api_key": KEY, "album_ids": [fake.holiday], **kw}
    r = c.put("/api/immich", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def no_key(resp: httpx.Response) -> None:
    assert KEY not in resp.text
    assert all(KEY not in v for v in resp.headers.values())


def test_not_configured_falls_back(client, fake):
    r = client.get("/api/immich").json()
    assert r["configured"] is False and r["status"] == "unconfigured"
    assert client.get("/api/screensaver/photos").json() == {"source": "none", "status": "unconfigured", "photos": []}
    assert client.get("/api/immich/albums").status_code == 404
    assert fake.requests == []


def test_test_connection_and_album_listing(client, fake):
    assert client.post("/api/immich/test", json={"pin": "0000", "server_url": URL, "api_key": KEY}).status_code == 403
    r = client.post("/api/immich/test", json={"pin": PIN, "server_url": URL, "api_key": KEY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["version"] == "3.3.1"
    assert [a["name"] for a in body["albums"]] == ["Garden", "Holiday 2025", "Private"]
    assert body["albums"][1] == {"id": fake.holiday, "name": "Holiday 2025", "asset_count": 5, "shared": False}
    no_key(r)
    r = client.post("/api/immich/test", json={"pin": PIN, "server_url": URL, "api_key": "nope"})
    assert r.status_code == 400 and "API key" in r.json()["detail"]
    assert client.post("/api/immich/test", json={"pin": PIN, "server_url": "ftp://x", "api_key": KEY}).status_code == 400
    assert client.post("/api/immich/test", json={"pin": PIN}).status_code == 400  # nothing saved yet
    # Every request to Immich carried the key in the header, never in the URL.
    assert all("x-api-key" in q.headers and KEY not in str(q.url) for q in fake.requests if q.url.path != "/api/server/version")


def test_connect_save_and_key_is_write_only(client, fake):
    assert client.put("/api/immich", json={"server_url": URL, "api_key": KEY, "pin": "0000"}).status_code == 403
    r = client.put("/api/immich", json={"pin": PIN, "server_url": URL, "api_key": "wrong"})
    assert r.status_code == 400
    assert client.get("/api/immich").json()["configured"] is False
    assert client.put("/api/immich", json={"pin": PIN, "server_url": URL, "api_key": KEY,
                                           "album_ids": ["not-a-uuid"]}).status_code == 400
    cfg = connect(client, fake)
    assert cfg["server_url"] == URL and cfg["key_set"] is True and cfg["album_ids"] == [fake.holiday]
    assert cfg["status"] == "ok" and cfg["photo_count"] == 3 and cfg["version"] == "3.3.1"
    assert "api_key" not in cfg
    # Change albums without re-sending the key; the saved key keeps working.
    r = client.put("/api/immich", json={"pin": PIN, "album_ids": [fake.holiday, fake.garden], "favorites": True})
    assert r.status_code == 200, r.text
    assert r.json()["photo_count"] == 5  # 3 holiday + 1 garden (locked one skipped) + 1 favourite image
    for path in ("/api/immich", "/api/settings", "/api/screensaver/photos", "/api/immich/albums"):
        no_key(client.get(path))
    # Stored only in the database.
    import sqlite3
    from moonlight import db
    assert sqlite3.connect(db.db_path()).execute("SELECT api_key FROM immich").fetchone()[0] == KEY
    assert client.request("DELETE", "/api/immich", json={"pin": "0000"}).status_code == 403
    assert client.request("DELETE", "/api/immich", json={"pin": PIN}).json() == {"ok": True}
    assert client.get("/api/immich").json()["configured"] is False
    assert client.get("/api/screensaver/photos").json()["photos"] == []


def test_asset_filtering_only_images_from_chosen_albums(client, fake):
    connect(client, fake)
    r = client.get("/api/screensaver/photos")
    body = r.json()
    assert body["source"] == "immich" and body["status"] == "ok"
    want = {a["id"] for a in fake.photos[fake.holiday] if a["type"] == "IMAGE" and not a["isTrashed"]}
    assert {p["id"] for p in body["photos"]} == want and len(want) == 3
    p = body["photos"][0]
    assert p["url"] == f"/api/immich/assets/{p['id']}/preview"
    assert p["width"] == 4032 and p["height"] == 3024 and p["taken_at"].startswith("2025-07-14")
    # Even if Immich ignored the type filter, videos are dropped on our side.
    vids = {a["id"] for a in fake.all_assets() if a["type"] == "VIDEO"}
    assert not vids & {x["id"] for x in body["photos"]}
    assert all(x["url"].startswith("/api/immich/") for x in body["photos"])


def test_favourites_and_memories(client, fake):
    connect(client, fake, album_ids=[], favorites=True, memories=True)
    ids = {p["id"] for p in client.get("/api/screensaver/photos").json()["photos"]}
    assert ids == {fake.favs[0]["id"], fake.memory[0]["id"]}


def test_paging_and_new_search_filter(client, fake):
    fake.photos[fake.holiday] = [asset() for _ in range(7)]
    fake.page_size_override = 3
    assert connect(client, fake)["photo_count"] == 7
    fake.flat_rejected = True  # server without the deprecated fields: falls back to `filter` + `cursor`
    assert client.put("/api/immich", json={"pin": PIN, "album_ids": [fake.holiday, fake.garden]}).json()["photo_count"] == 8
    assert any("filter" in json.loads(q.content or b"{}") for q in fake.requests if q.url.path == "/api/search/metadata")


def test_proxy_serves_only_chosen_assets(client, fake):
    connect(client, fake)
    photos = client.get("/api/screensaver/photos").json()["photos"]
    r = client.get(photos[0]["url"])
    assert r.status_code == 200 and r.content == b"\xff\xd8JPEG-" + photos[0]["id"].encode()
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "private, max-age=86400"
    no_key(r)
    # An asset that exists in Immich but isn't in a chosen album, a video in a chosen album, junk ids.
    other = fake.photos[fake.private][0]["id"]
    video = next(a["id"] for a in fake.photos[fake.holiday] if a["type"] == "VIDEO")
    n = len(fake.requests)
    for bad in (other, video, "../albums", "not-a-uuid", uid()):
        assert client.get(f"/api/immich/assets/{bad}/preview").status_code == 404
    assert not any("/thumbnail" in q.url.path for q in fake.requests[n:])
    # Dropping the album from the choice revokes access straight away.
    client.put("/api/immich", json={"pin": PIN, "album_ids": [fake.garden]})
    assert client.get(photos[0]["url"]).status_code == 404


def test_immich_down(client, fake):
    connect(client, fake)
    photos = client.get("/api/screensaver/photos").json()["photos"]
    fake.down = True
    # The cached list is kept until the next refresh; previews fail cleanly.
    r = client.get(photos[0]["url"])
    assert r.status_code == 502 and "Couldn't reach Immich" in r.json()["detail"]
    no_key(r)
    assert client.get("/api/immich").json()["status"] == "error"  # reported straight away
    immich.cache.fetched_at -= immich.REFRESH_SECONDS + 1  # time for a refresh
    body = client.get("/api/screensaver/photos").json()
    assert body["status"] == "error" and len(body["photos"]) == 3  # last good list
    cfg = client.get("/api/immich").json()
    assert cfg["status"] == "error" and "Couldn't reach Immich" in cfg["last_error"]
    r = client.post("/api/immich/test", json={"pin": PIN})
    assert r.status_code == 502
    no_key(r)
    assert client.get("/api/immich/albums").status_code == 502
    # Down from the start (e.g. after a restart): nothing cached, so the screens show their scenes.
    immich.cache.reset()
    body = client.get("/api/screensaver/photos").json()
    assert body == {"source": "immich", "status": "error", "photos": []}
    assert client.get(photos[0]["url"]).status_code == 404
    fake.down = False
    immich.cache.tried_at -= immich.RETRY_SECONDS + 1
    assert len(client.get("/api/screensaver/photos").json()["photos"]) == 3


def test_key_revoked_in_immich(client, fake, monkeypatch):
    connect(client, fake)
    fake_key = KEY
    fake.requests.clear()
    # Simulate the key being deleted in Immich: the fake now expects a different key.
    monkeypatch.setitem(globals(), "KEY", "a-new-key-the-user-made")
    immich.cache.fetched_at -= immich.REFRESH_SECONDS + 1
    body = client.get("/api/screensaver/photos").json()
    assert body["status"] == "auth_failed"
    cfg = client.get("/api/immich").json()
    assert cfg["status"] == "auth_failed" and "API key" in cfg["last_error"]
    assert fake_key not in json.dumps(cfg)


def test_screensaver_timing_settings(client):
    s = client.get("/api/settings").json()
    assert "screensaver_album" not in s and s["screensaver_seconds"] == 10
    assert s["idle_minutes"] == {"large": 5, "compact": 3, "phone": 0}
    r = client.patch("/api/settings", json={"pin": PIN, "screensaver_seconds": 20, "idle_minutes": {"kitchen": 10}})
    assert r.status_code == 200, r.text
    assert r.json()["screensaver_seconds"] == 20 and r.json()["idle_minutes"] == {"large": 5, "compact": 10, "phone": 0}
    assert client.patch("/api/settings", json={"pin": PIN, "idle_minutes": 7}).json()["idle_minutes"] == \
        {"large": 7, "compact": 7, "phone": 0}
    assert client.patch("/api/settings", json={"pin": PIN, "screensaver_seconds": 1}).status_code == 400
    assert client.patch("/api/settings", json={"pin": PIN, "idle_minutes": {"attic": 1}}).status_code == 400


def test_paired_screen_gets_previews_unpaired_does_not(tmp_path, fake):
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "x", auth_enabled=True)
    ha = TestClient(app, client=("172.30.32.2", 1), headers={"X-Ingress-Path": "/x"})
    assert ha.patch("/api/settings", json={"pin": PIN}).status_code == 200
    connect(ha, fake)
    url = ha.get("/api/screensaver/photos").json()["photos"][0]["url"]
    screen = TestClient(app, client=("192.168.1.50", 2))
    start = screen.post("/api/pair/start", json={"layout": "hallway"}).json()
    assert ha.post("/api/displays/approve", json={"code": start["code"], "pin": PIN}).status_code == 200
    assert screen.get(f"/api/pair/{start['pair_id']}").json()["status"] == "approved"
    assert screen.get(url).status_code == 200
    assert TestClient(app, client=("192.168.1.51", 3)).get(url).status_code == 401
    # A screen can't change the source without the PIN.
    assert screen.put("/api/immich", json={"server_url": "http://evil.test", "api_key": "x"}).status_code == 403
