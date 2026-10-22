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
        self.updated = {self.holiday: "2025-08-01T10:00:00.000Z", self.garden: "2026-05-01T10:00:00.000Z",
                        self.private: "2024-01-01T10:00:00.000Z"}
        self.favs = [asset(isFavorite=True), asset("VIDEO", isFavorite=True)]
        self.memory = [asset(), asset("VIDEO")]
        self.removed = [a for xs in self.photos.values() for a in xs]  # to put back the same asset
        self.view_only: set[str] = set()  # shared albums the key's user can only look at
        self.no_album_edit = False  # a key without albumAsset.delete / albumAsset.create

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
                {"id": k, "albumName": self.names[k], "assetCount": len(v), "shared": False, "albumThumbnailAssetId": None,
                 "updatedAt": self.updated[k], "lastModifiedAssetTimestamp": self.updated[k]}
                for k, v in self.photos.items()])
        if path.startswith("/api/albums/") and path.endswith("/assets") and req.method in ("PUT", "DELETE"):
            if self.no_album_edit:
                return httpx.Response(403, json={"message": "Missing required permission"})
            album = path.split("/")[3]
            if album not in self.photos:
                return httpx.Response(400, json={"message": "Not found or no album.read access"})
            out = []
            for aid in json.loads(req.content)["ids"]:
                items = self.photos[album]
                there = next((a for a in items if a["id"] == aid), None)
                if album in self.view_only:
                    out.append({"id": aid, "success": False, "error": "no_permission"})
                elif req.method == "DELETE":
                    if there:
                        items.remove(there)
                        self.updated[album] = "2026-10-22T10:00:00.000Z"
                    out.append({"id": aid, "success": bool(there), **({} if there else {"error": "not_found"})})
                else:
                    if not there:
                        items.append(next((a for a in self.removed if a["id"] == aid), asset(id=aid)))
                        self.updated[album] = "2026-10-22T11:00:00.000Z"
                    out.append({"id": aid, "success": not there, **({"error": "duplicate"} if there else {})})
            return httpx.Response(200, json=out)
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
    assert client.get("/api/screensaver/photos").json() == {"source": "none", "status": "unconfigured", "photos": [], "albums": []}
    assert client.get("/api/immich/albums").status_code == 404
    assert fake.requests == []


def test_test_connection_and_album_listing(client, fake):
    assert client.post("/api/immich/test", json={"pin": "0000", "server_url": URL, "api_key": KEY}).status_code == 403
    r = client.post("/api/immich/test", json={"pin": PIN, "server_url": URL, "api_key": KEY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["version"] == "3.3.1"
    assert [a["name"] for a in body["albums"]] == ["Garden", "Holiday 2025", "Private"]
    assert body["albums"][1] == {"id": fake.holiday, "name": "Holiday 2025", "asset_count": 5, "shared": False,
                                 "updated_at": "2025-08-01T10:00:00.000Z"}
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
    assert r.status_code == 502 and "Nothing answered at http://immich.test:2283" in r.json()["detail"]
    no_key(r)
    assert client.get("/api/immich").json()["status"] == "error"  # reported straight away
    immich.cache.fetched_at -= immich.REFRESH_SECONDS + 1  # time for a refresh
    body = client.get("/api/screensaver/photos").json()
    assert body["status"] == "error" and len(body["photos"]) == 3  # last good list
    cfg = client.get("/api/immich").json()
    assert cfg["status"] == "error" and "Nothing answered" in cfg["last_error"]
    r = client.post("/api/immich/test", json={"pin": PIN})
    assert r.status_code == 502
    no_key(r)
    assert client.get("/api/immich/albums").status_code == 502
    # Down from the start (e.g. after a restart): nothing cached, so the screens show their scenes.
    immich.cache.reset()
    body = client.get("/api/screensaver/photos").json()
    assert body == {"source": "immich", "status": "error", "photos": [], "albums": []}
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


def test_connection_problems_say_what_to_try(client, monkeypatch):
    import socket

    def answer(req: httpx.Request) -> httpx.Response:
        host = req.url.host
        if host == "homeassistant.local":
            raise httpx.ConnectError("[Errno -2] Name or service not known", request=req) from socket.gaierror(-2, "x")
        if host == "slow.test":
            raise httpx.ConnectTimeout("", request=req)
        if host == "proxy.test":
            return httpx.Response(502, text="<html>Bad Gateway</html>")
        if host == "redirect.test":
            return httpx.Response(301, headers={"location": "https://immich.example.com/api/albums"})
        return httpx.Response(404, text="Not found")

    def detail(url: str) -> str:
        r = client.post("/api/immich/test", json={"pin": PIN, "server_url": url, "api_key": KEY})
        assert r.status_code == 502, r.text
        no_key(r)
        return r.json()["detail"]

    monkeypatch.setattr(immich, "transport", httpx.MockTransport(answer))
    client.put("/api/settings", json={"pin": PIN, "new_pin": PIN})
    assert "use the IP address" in detail("http://homeassistant.local:2283")
    assert "didn't answer in time" in detail("http://slow.test:2283")
    assert "answered 502" in detail("http://proxy.test") and "Immich is running" in detail("http://proxy.test")
    assert "redirects to https://immich.example.com/api/albums" in detail("http://redirect.test")
    assert "no Immich API (404)" in detail("http://other.test/photos")


def test_self_signed_https_needs_skip_cert_check(client, monkeypatch, tmp_path):
    """A real HTTPS server with a self-signed certificate, like an Immich add-on with SSL reached by IP address."""
    import json as _json
    import ssl
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=immich.example",
                    "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.headers.get("x-api-key") != KEY:
                self.send_response(401); self.end_headers(); return  # noqa: E702
            body = _json.dumps([{"id": "0b6c2e0a-1f3d-4c5e-9a7b-2d4e6f8a0c1e", "albumName": "Garden", "assetCount": 3}] if self.path == "/api/albums"
                               else {"major": 2, "minor": 1, "patch": 0}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()  # noqa: E702
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(immich, "transport", None)  # the real network stack, so TLS is really checked
        for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.delenv(var, raising=False)
        url = f"https://127.0.0.1:{server.server_port}"
        client.put("/api/settings", json={"pin": PIN, "new_pin": PIN})
        r = client.post("/api/immich/test", json={"pin": PIN, "server_url": url, "api_key": KEY})
        assert r.status_code == 502 and "Skip certificate check" in r.json()["detail"], r.text
        r = client.post("/api/immich/test", json={"pin": PIN, "server_url": url, "api_key": KEY, "skip_cert_check": True})
        assert r.status_code == 200 and r.json()["albums"][0]["name"] == "Garden", r.text
        r = client.put("/api/immich", json={"pin": PIN, "server_url": url, "api_key": KEY, "album_ids": ["0b6c2e0a-1f3d-4c5e-9a7b-2d4e6f8a0c1e"],
                                            "skip_cert_check": True})
        assert r.status_code == 200 and r.json()["skip_cert_check"] is True, r.text
        assert client.get("/api/immich/albums").status_code == 200  # the saved setting is used
        # Plain http:// to the HTTPS port says to use https://.
        r = client.post("/api/immich/test", json={"pin": PIN, "server_url": f"http://127.0.0.1:{server.server_port}",
                                                  "api_key": KEY})
        assert r.status_code == 502, r.text
    finally:
        server.shutdown()


def test_place_name_prefers_ha_zone_then_town():
    zones = [{"name": "Home", "latitude": 51.5, "longitude": -0.1, "radius": 100.0},
             {"name": "Peppa Pig World", "latitude": 50.9568, "longitude": -1.5378, "radius": 400.0},
             {"name": "Hampshire", "latitude": 50.95, "longitude": -1.53, "radius": 20000.0}]
    # Inside two zones: the smaller (more specific) one wins.
    assert immich.place_name({"latitude": 50.9570, "longitude": -1.5380, "city": "Romsey"}, zones) == "Peppa Pig World"
    assert immich.place_name({"latitude": 51.5004, "longitude": -0.1, "city": "London"}, zones) == "Home"
    # Outside every zone: the town Immich worked out, else region, else country.
    assert immich.place_name({"latitude": 48.85, "longitude": 2.35, "city": "Paris"}, zones) == "Paris"
    assert immich.place_name({"state": "Brittany", "country": "France"}, zones) == "Brittany"
    assert immich.place_name({"country": "France"}, []) == "France"
    assert immich.place_name({}, zones) is None


def test_photos_carry_place_from_zones(client, fake, monkeypatch):
    async def zones():
        return [{"name": "Home", "latitude": 51.5, "longitude": -0.1, "radius": 100.0}]
    monkeypatch.setattr(immich.ha_client, "zones", zones)
    home, away, unknown = fake.photos[fake.holiday][:3]
    home["exifInfo"] = {"latitude": 51.5001, "longitude": -0.1001, "city": "London"}
    away["exifInfo"] = {"latitude": 50.72, "longitude": -3.53, "city": "Exeter"}
    connect(client, fake)
    places = {p["id"]: p["place"] for p in client.get("/api/screensaver/photos").json()["photos"]}
    assert places == {home["id"]: "Home", away["id"]: "Exeter", unknown["id"]: None}
    # Moonlight asks Immich for the EXIF data that holds the location.
    searches = [json.loads(q.content) for q in fake.requests if q.url.path == "/api/search/metadata"]
    assert searches and all(s["withExif"] is True for s in searches)


def test_photo_details_setting(client):
    assert client.get("/api/settings").json()["photo_details"] is True
    assert client.patch("/api/settings", json={"pin": PIN, "photo_details": False}).json()["photo_details"] is False
    assert client.patch("/api/settings", json={"pin": PIN, "photo_details": "no"}).status_code == 400


def images(xs) -> set[str]:
    return {a["id"] for a in xs if a["type"] == "IMAGE" and not a["isTrashed"] and a["visibility"] == "timeline"}


def test_all_albums_except_excluded(client, fake):
    loose = asset()  # in no album: only shown as a favourite
    fake.favs.append(loose)
    cfg = connect(client, fake, mode="all", excluded_album_ids=[fake.garden], album_ids=[])
    assert cfg["mode"] == "all" and cfg["excluded_album_ids"] == [fake.garden]
    want = images(fake.photos[fake.holiday]) | images(fake.photos[fake.private])
    ids = {p["id"] for p in client.get("/api/screensaver/photos").json()["photos"]}
    assert ids == want and len(want) == 5
    garden = next(iter(images(fake.photos[fake.garden])))
    assert client.get(f"/api/immich/assets/{garden}/preview").status_code == 404
    # A photo that is also in an excluded album stays hidden.
    fake.photos[fake.garden].append(fake.photos[fake.holiday][0])
    fake.updated[fake.garden] = "2026-06-01T10:00:00.000Z"
    assert client.put("/api/immich", json={"pin": PIN, "favorites": True}).json()["photo_count"] == 6  # 5 - the shared one + 2 favourites
    # Back to chosen albums: the exclusions are kept for next time but don't apply.
    r = client.put("/api/immich", json={"pin": PIN, "mode": "albums", "album_ids": [fake.garden], "favorites": False}).json()
    assert r["photo_count"] == 2 and r["excluded_album_ids"] == [fake.garden]
    for bad in ({"mode": "some"}, {"excluded_album_ids": ["x"]}):
        assert client.put("/api/immich", json={"pin": PIN, **bad}).status_code == 400


def test_photos_come_grouped_by_album(client, fake):
    for i, a in enumerate(fake.photos[fake.holiday]):
        a["localDateTime"] = f"2025-07-1{5 - i}T10:00:00.000Z"  # listed newest first by Immich
    connect(client, fake, mode="all", album_ids=[], favorites=True)
    body = client.get("/api/screensaver/photos").json()
    # Most recently changed album first; Favourites after the albums.
    assert [a["name"] for a in body["albums"]] == ["Garden", "Holiday 2025", "Private", "Favourites"]
    holiday = body["albums"][1]
    assert holiday["id"] == fake.holiday and holiday["updated_at"] == "2025-08-01T10:00:00.000Z"
    taken = {p["id"]: p["taken_at"] for p in body["photos"]}
    assert [taken[i] for i in holiday["photos"]] == sorted(taken[i] for i in holiday["photos"])  # oldest first
    assert {i for a in body["albums"] for i in a["photos"]} == {p["id"] for p in body["photos"]}
    # Unchanged albums aren't read again on the next refresh; a changed one is.
    fake.requests.clear()
    immich.cache.fetched_at -= immich.REFRESH_SECONDS + 1
    client.get("/api/screensaver/photos")
    searched = [json.loads(q.content) for q in fake.requests if q.url.path == "/api/search/metadata"]
    assert all("albumIds" not in b for b in searched) and searched  # only favourites
    fake.photos[fake.private].append(asset())
    fake.requests.clear()
    immich.cache.fetched_at -= immich.REFRESH_SECONDS + 1
    body = client.get("/api/screensaver/photos").json()
    searched = [json.loads(q.content) for q in fake.requests if q.url.path == "/api/search/metadata"]
    assert [b["albumIds"] for b in searched if "albumIds" in b] == [[fake.private]]  # its asset count changed
    assert len(body["albums"][2]["photos"]) == 3


def test_festive_albums_only_in_december(client, fake, monkeypatch):
    from datetime import date
    day = {"d": date(2026, 10, 17)}
    monkeypatch.setattr(immich, "household_today", lambda tz: day["d"])
    fake.names[fake.private] = "Christmas 2024"
    fake.names[fake.garden] = "Snow day"
    connect(client, fake, mode="all", album_ids=[])
    body = client.get("/api/screensaver/photos").json()
    assert [a["name"] for a in body["albums"]] == ["Snow day", "Holiday 2025"]  # Christmas hidden outside December
    # Chosen albums too: a festive album that is chosen only shows in December.
    assert client.put("/api/immich", json={"pin": PIN, "mode": "albums", "album_ids": [fake.private, fake.holiday]}).json()["photo_count"] == 3
    day["d"] = date(2026, 12, 1)  # December: festive and winter albums only, straight away
    body = client.get("/api/screensaver/photos").json()
    assert sorted(a["name"] for a in body["albums"]) == ["Christmas 2024", "Snow day"]
    assert {p["id"] for p in body["photos"]} == images(fake.photos[fake.private]) | images(fake.photos[fake.garden])
    assert client.get("/api/immich").json()["festive_now"] is True
    # "On this day" still shows in December (it's Christmases past), favourites don't.
    body = client.put("/api/immich", json={"pin": PIN, "memories": True, "favorites": True}).json()
    names = [a["name"] for a in client.get("/api/screensaver/photos").json()["albums"]]
    assert "On this day" in names and "Favourites" not in names
    client.put("/api/immich", json={"pin": PIN, "memories": False, "favorites": False})
    # Filter off: Christmas albums are ordinary albums all year.
    r = client.put("/api/immich", json={"pin": PIN, "festive": False}).json()
    assert r["festive"] is False and r["festive_now"] is False and r["photo_count"] == 5
    assert client.put("/api/immich", json={"pin": PIN, "festive": "yes"}).status_code == 400
    # No festive albums at all: December is like any other month.
    client.put("/api/immich", json={"pin": PIN, "festive": True, "mode": "all", "excluded_album_ids": [fake.private]})
    assert {a["name"] for a in client.get("/api/screensaver/photos").json()["albums"]} == {"Snow day", "Holiday 2025"}


def test_festive_and_winter_names():
    for name in ("Christmas 2024", "XMAS", "Christmas2023", "Festive fun", "Yule log", "Advent calendar", "Santa visit",
                 "Nativity play", "Carols by candlelight", "Boxing Day walk", "christmas"):
        assert immich.is_festive(name), name
    for name in ("Adventure park", "Caroline's birthday", "Holiday 2025", "Boxing class", "Santander trip"):
        assert not immich.is_festive(name), name
    for name in ("Winter 2025", "Snow day", "Skiing in Austria", "Frosty morning", "Ice skating"):
        assert immich.is_winter(name), name
    for name in ("Ice cream", "Skipton", "Snowdonia"):
        assert not immich.is_winter(name), name


def test_hide_photo_removes_it_from_its_albums(client, fake):
    shared = fake.holiday
    both = fake.photos[fake.garden][0]
    fake.photos[shared].append(both)  # in Garden and Holiday 2025
    connect(client, fake, album_ids=[fake.holiday, fake.garden, fake.private], favorites=True)
    body = client.get("/api/screensaver/photos").json()
    assert both["id"] in {p["id"] for p in body["photos"]}
    fake.view_only.add(shared)  # Holiday 2025 is someone else's shared album
    r = client.post(f"/api/screensaver/photos/{both['id']}/hide")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["removed"] == [{"id": fake.garden, "name": "Garden"}]
    assert out["failed"] == [{"id": shared, "name": "Holiday 2025", "error": "Immich only lets you view this album"}]
    assert both not in fake.photos[fake.garden] and both in fake.photos[shared]
    # Gone from the screens straight away, and after a refresh (still in Holiday 2025 in Immich).
    body = client.get("/api/screensaver/photos").json()
    assert both["id"] not in {p["id"] for p in body["photos"]}
    assert all(both["id"] not in a["photos"] for a in body["albums"])
    immich.cache.fetched_at -= immich.REFRESH_SECONDS + 1
    body = client.get("/api/screensaver/photos").json()
    assert both["id"] not in {p["id"] for p in body["photos"]}
    # Settings lists it, with a thumbnail the proxy still serves.
    hidden = client.get("/api/immich/hidden").json()
    assert [h["id"] for h in hidden] == [both["id"]] and hidden[0]["albums"] == [{"id": fake.garden, "name": "Garden"}]
    assert client.get(hidden[0]["url"]).status_code == 200
    assert client.post(f"/api/screensaver/photos/{both['id']}/hide").status_code == 404  # not on the screens now
    # Show again: needs the PIN, goes back into Garden.
    assert client.post(f"/api/immich/hidden/{both['id']}/restore", json={"pin": "0000"}).status_code == 403
    r = client.post(f"/api/immich/hidden/{both['id']}/restore", json={"pin": PIN}).json()
    assert r["restored"] == [{"id": fake.garden, "name": "Garden"}] and r["failed"] == []
    assert both in fake.photos[fake.garden] and client.get("/api/immich/hidden").json() == []
    assert both["id"] in {p["id"] for p in client.get("/api/screensaver/photos").json()["photos"]}


def test_hide_photo_when_immich_refuses_or_not_in_an_album(client, fake):
    connect(client, fake, favorites=True)
    fav = fake.favs[0]["id"]
    r = client.post(f"/api/screensaver/photos/{fav}/hide").json()  # a favourite: nothing to take it out of
    assert r == {"ok": True, "removed": [], "failed": []}
    fake.no_album_edit = True
    one = fake.photos[fake.holiday][0]["id"]
    r = client.post(f"/api/screensaver/photos/{one}/hide").json()
    assert r["removed"] == [] and "albumAsset.delete" in r["failed"][0]["error"]
    ids = {p["id"] for p in client.get("/api/screensaver/photos").json()["photos"]}
    assert not ids & {fav, one}
    assert client.post(f"/api/screensaver/photos/{uid()}/hide").status_code == 404
    assert client.post("/api/screensaver/photos/not-a-uuid/hide").status_code == 404
