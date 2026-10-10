"""Screen pairing, the auth middleware and photo uploads: run from backend/ with `python -m pytest`."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight.main import create_app  # noqa: E402
from moonlight.routes import photos as photos_mod  # noqa: E402

PIN = "4321"
INGRESS_IP = "172.30.32.2"
INGRESS = {"X-Ingress-Path": "/api/hassio_ingress/abc123", "X-Remote-User-Display-Name": "Chris"}


def jpeg(w=1200, h=800, color=(200, 120, 60), orientation=None, taken=None, fmt="JPEG") -> bytes:
    im = Image.new("RGB", (w, h), color)
    im.paste((20, 40, 200), (0, 0, w // 4, h // 4))  # marker in the top-left corner
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    if taken:
        exif.get_ifd(0x8769)[0x9003] = taken
    buf = io.BytesIO()
    im.save(buf, fmt, exif=exif.tobytes()) if fmt == "JPEG" else im.save(buf, fmt)
    return buf.getvalue()


def size_of(content: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(content)).size


# ---------------------------------------------------------------- auth on

@pytest.fixture
def app_on(tmp_path):
    return create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "no-dist",
                      data_dir=tmp_path / "data", auth_enabled=True)


@pytest.fixture
def ha(app_on):
    """A Home Assistant user arriving through ingress."""
    c = TestClient(app_on, client=(INGRESS_IP, 40000), headers=INGRESS)
    assert c.patch("/api/settings", json={"pin": PIN}).status_code == 200
    return c


def lan(app, **kw):
    return TestClient(app, client=("192.168.1.50", 51000), **kw)


def pair(ha_client, screen, name="Kitchen", layout="kitchen"):
    start = screen.post("/api/pair/start", json={"layout": layout}).json()
    r = ha_client.post("/api/displays/approve", json={"code": start["code"], "name": name, "pin": PIN})
    assert r.status_code == 200, r.text
    r = screen.get(f"/api/pair/{start['pair_id']}")
    assert r.json()["status"] == "approved"
    return r.json()["token"], r.json()["display"]


def test_unpaired_lan_is_locked_out(app_on, ha):
    s = lan(app_on)
    assert s.get("/api/people").status_code == 401
    assert s.get("/api/people").json()["pairing"] is True
    assert s.post("/api/events", json={}).status_code == 401
    assert s.get("/api/health").status_code == 200
    assert s.get("/api/auth/status").json() == {"required": True, "authorised": False, "via": None, "display": None}
    # HTML still served so the pairing screen can load.
    assert s.get("/display/kitchen").status_code == 200
    # Faking the ingress header from the LAN, or the ingress IP without the header, is not enough.
    assert s.get("/api/people", headers=INGRESS).status_code == 401
    assert TestClient(app_on, client=(INGRESS_IP, 1)).get("/api/people").status_code == 401
    # A made-up token is rejected.
    assert s.get("/api/people", headers={"Authorization": "Bearer mlt_nope"}).status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with s.websocket_connect("/api/ws") as ws:
            ws.receive_json()


def test_ingress_allowed(ha):
    assert ha.get("/api/people").status_code == 200
    st = ha.get("/api/auth/status").json()
    assert st["authorised"] and st["via"] == "ingress"
    with ha.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"


def test_pairing_flow(app_on, ha):
    screen = lan(app_on)
    start = screen.post("/api/pair/start", json={"layout": "kitchen"}).json()
    assert len(start["code"]) == 6 and start["code"].isdigit() and start["expires_in"] == 600
    assert screen.get(f"/api/pair/{start['pair_id']}").json()["status"] == "pending"
    assert screen.get("/api/pair/not-a-real-id").json() == {"status": "expired"}

    # Approving needs an authorised session, the right PIN and a waiting code.
    assert lan(app_on).post("/api/displays/approve", json={"code": start["code"], "pin": PIN}).status_code == 401
    assert ha.post("/api/displays/approve", json={"code": start["code"], "pin": "0000"}).status_code == 403
    bad_code = "000000" if start["code"] != "000000" else "111111"
    assert ha.post("/api/displays/approve", json={"code": bad_code, "pin": PIN}).status_code == 404
    assert ha.post("/api/displays/approve", json={"code": "12ab", "pin": PIN}).status_code == 400
    r = ha.post("/api/displays/approve", json={"code": start["code"], "name": "Kitchen", "pin": PIN})
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "Kitchen" and d["layout"] == "kitchen" and d["revoked"] is False

    r = screen.get(f"/api/pair/{start['pair_id']}")
    body = r.json()
    assert body["status"] == "approved" and body["token"].startswith("mlt_") and body["display"]["id"] == d["id"]
    sc = r.headers["set-cookie"]
    assert "moonlight_display=" in sc and "HttpOnly" in sc and "Max-Age=" in sc
    # Handed out once only.
    assert screen.get(f"/api/pair/{start['pair_id']}").json()["status"] == "expired"
    # The cookie now opens the API, and the screen shows up with last_seen.
    assert screen.get("/api/people").status_code == 200
    st = screen.get("/api/auth/status").json()
    assert st["via"] == "display" and st["display"]["name"] == "Kitchen"
    listed = screen.get("/api/displays").json()
    assert [x["id"] for x in listed] == [d["id"]] and listed[0]["current"] is True and listed[0]["last_seen"]
    assert ha.get("/api/displays").json()[0]["current"] is False
    # The token is stored hashed.
    import sqlite3
    from moonlight import db
    raw = sqlite3.connect(db.db_path()).execute("SELECT token_hash FROM displays").fetchone()[0]
    assert body["token"] not in raw


def test_token_bearer_query_and_websocket(app_on, ha):
    token, _ = pair(ha, lan(app_on))
    assert lan(app_on, headers={"Authorization": f"Bearer {token}"}).get("/api/people").status_code == 200
    # ?token= on the first page load (TouchKio) sets the long-lived cookie.
    fresh = lan(app_on)
    r = fresh.get(f"/display/kitchen?token={token}")
    assert r.status_code == 200 and "moonlight_display=" in r.headers.get("set-cookie", "")
    assert fresh.get("/api/people").status_code == 200
    # Bearer without cookie also (re)sets it.
    r = lan(app_on).get("/api/people", headers={"Authorization": f"Bearer {token}"})
    assert "moonlight_display=" in r.headers.get("set-cookie", "")
    with lan(app_on).websocket_connect(f"/api/ws?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"


def test_service_pairing_home_assistant(app_on, ha):
    """The HA integration pairs as a non-screen "service" client with a suggested name, then uses a Bearer token."""
    hass = lan(app_on)
    st = hass.get("/api/auth/status").json()
    assert st["required"] is True and st["authorised"] is False
    start = hass.post("/api/pair/start", json={"layout": "service", "name": "Home Assistant"}).json()
    assert start["layout"] == "service"
    # The approver can't turn it into a screen; a blank name falls back to the suggested one.
    r = ha.post("/api/displays/approve", json={"code": start["code"], "name": "", "layout": "kitchen", "pin": PIN})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["layout"] == "service" and d["name"] == "Home Assistant"
    token = hass.get(f"/api/pair/{start['pair_id']}").json()["token"]
    client = lan(app_on, headers={"Authorization": f"Bearer {token}"})
    assert client.get("/api/summary").status_code == 200
    assert client.get("/api/auth/status").json()["authorised"] is True
    with lan(app_on).websocket_connect("/api/ws", headers={"Authorization": f"Bearer {token}"}) as ws:
        assert ws.receive_json()["type"] == "hello"
    assert [x["layout"] for x in ha.get("/api/displays").json()] == ["service"]
    # Revoking it locks the integration out again (it then re-pairs via a reauth flow).
    assert ha.request("DELETE", f"/api/displays/{d['id']}", json={"pin": PIN}).status_code == 200
    assert client.get("/api/summary").status_code == 401


def test_pair_start_validation(app_on, ha):
    s = lan(app_on)
    assert s.post("/api/pair/start", json={"layout": "toaster"}).status_code == 400
    assert s.post("/api/pair/start", json={"layout": "kitchen", "name": 5}).status_code == 400
    # A screen can't be approved as a service, and a screen's suggested name is used when none is typed.
    start = s.post("/api/pair/start", json={"layout": "hallway", "name": "Landing"}).json()
    assert ha.post("/api/displays/approve",
                   json={"code": start["code"], "layout": "service", "pin": PIN}).status_code == 400
    d = ha.post("/api/displays/approve", json={"code": start["code"], "pin": PIN}).json()
    assert d["layout"] == "hallway" and d["name"] == "Landing"


def test_revoked_screen_is_rejected(app_on, ha):
    screen = lan(app_on)
    token, d = pair(ha, screen)
    assert screen.get("/api/people").status_code == 200
    assert ha.request("DELETE", f"/api/displays/{d['id']}", json={"pin": "0000"}).status_code == 403
    assert ha.request("DELETE", f"/api/displays/{d['id']}", json={"pin": PIN}).status_code == 200
    r = screen.get("/api/people")
    assert r.status_code == 401
    assert "Max-Age=0" in r.headers.get("set-cookie", "")  # stale cookie cleared
    assert lan(app_on, headers={"Authorization": f"Bearer {token}"}).get("/api/people").status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with lan(app_on).websocket_connect(f"/api/ws?token={token}") as ws:
            ws.receive_json()
    assert ha.get("/api/displays").json() == []
    assert ha.request("DELETE", f"/api/displays/{d['id']}", json={"pin": PIN}).status_code == 404


def test_photo_urls_work_for_paired_screen(app_on, ha):
    screen = lan(app_on)
    pair(ha, screen, name="Hallway", layout="hallway")
    r = screen.post("/api/photos", files=[("files", ("a.jpg", jpeg(), "image/jpeg"))])
    assert r.status_code == 200, r.text
    p = r.json()["uploaded"][0]
    assert p["uploaded_by"] == "Hallway"
    assert screen.get(p["thumb_url"]).status_code == 200
    assert screen.get(p["display_url"]).status_code == 200
    assert lan(app_on).get(p["thumb_url"]).status_code == 401
    r = ha.post("/api/photos", files=[("files", ("b.jpg", jpeg(), "image/jpeg"))])
    assert r.json()["uploaded"][0]["uploaded_by"] == "Chris"


def test_auth_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("MOONLIGHT_AUTH", raising=False)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "x", data_dir=tmp_path / "d")
    assert lan(app).get("/api/people").status_code == 200
    monkeypatch.setenv("SUPERVISOR_TOKEN", "abc")  # inside the add-on: on unless MOONLIGHT_AUTH=off
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "x", data_dir=tmp_path / "d")
    assert lan(app).get("/api/people").status_code == 401
    monkeypatch.setenv("MOONLIGHT_AUTH", "off")
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "x", data_dir=tmp_path / "d")
    assert lan(app).get("/api/people").status_code == 200


# ---------------------------------------------------------------- photos (auth off)

@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "no-dist",
                     data_dir=tmp_path / "data", auth_enabled=False)
    with TestClient(app) as c:
        assert c.patch("/api/settings", json={"pin": PIN}).status_code == 200
        yield c


def upload(c, *files, album_id=None):
    data = {"album_id": album_id} if album_id else None
    return c.post("/api/photos", data=data, files=[("files", f) for f in files])


def test_upload_resize_and_thumbnail(client, tmp_path):
    albums = client.get("/api/albums").json()
    assert [a["name"] for a in albums] == ["Family"]
    r = upload(client, ("big.jpg", jpeg(3000, 2000, taken="2024:07:14 15:30:00"), "image/jpeg"))
    assert r.status_code == 200, r.text
    p = r.json()["uploaded"][0]
    assert r.json()["errors"] == []
    assert (p["width"], p["height"]) == (3000, 2000)
    assert p["taken_at"] == "2024-07-14T15:30:00" and p["album_id"] == albums[0]["id"] and p["filename"] == "big.jpg"
    assert p["uploaded_by"] is None
    d = client.get(p["display_url"])
    assert d.status_code == 200 and d.headers["content-type"] == "image/jpeg"
    assert "immutable" in d.headers["cache-control"] and "max-age=31536000" in d.headers["cache-control"]
    assert size_of(d.content) == (2560, 1707)
    t = client.get(p["thumb_url"])
    assert size_of(t.content) == (600, 400) and "immutable" in t.headers["cache-control"]
    assert len(list((tmp_path / "data" / "photos" / "originals").iterdir())) == 1
    assert client.get("/api/albums").json()[0]["photo_count"] == 1
    assert client.get("/api/albums").json()[0]["cover_photo_id"] == p["id"]


def test_exif_rotation_is_applied(client):
    # Stored 1200x800 landscape pixels with "rotate 90 CW" (orientation 6): a portrait photo.
    r = upload(client, ("phone.jpg", jpeg(1200, 800, orientation=6), "image/jpeg"))
    p = r.json()["uploaded"][0]
    assert (p["width"], p["height"]) == (800, 1200) and p["taken_at"] is None
    im = Image.open(io.BytesIO(client.get(p["display_url"]).content)).convert("RGB")
    assert im.size == (800, 1200)
    # The blue marker was top-left in the stored pixels; after rotating 90 CW it is top-right.
    assert im.getpixel((780, 20))[2] > 150 and im.getpixel((20, 20))[2] < 100
    assert im.getexif().get(0x0112) in (None, 1)
    assert size_of(client.get(p["thumb_url"]).content) == (400, 600)


def test_multiple_files_png_and_bad_file(client):
    r = upload(client, ("a.jpg", jpeg(), "image/jpeg"), ("b.png", jpeg(fmt="PNG"), "image/png"),
               ("notes.txt", b"hello", "text/plain"))
    assert r.status_code == 200
    assert [p["filename"] for p in r.json()["uploaded"]] == ["a.jpg", "b.png"]
    assert len(r.json()["errors"]) == 1 and "notes.txt" in r.json()["errors"][0]["detail"]
    assert len(client.get("/api/photos").json()) == 2
    r = upload(client, ("notes.txt", b"hello", "text/plain"))
    assert r.status_code == 400 and "notes.txt" in r.json()["detail"]


def test_size_limit(client):
    big = b"\xff\xd8" + b"\0" * (25 * 1024 * 1024)
    r = upload(client, ("huge.jpg", big, "image/jpeg"))
    assert r.status_code == 413 and "25 MB" in r.json()["detail"]
    assert client.get("/api/photos").json() == []


def test_heic(client):
    try:
        import pillow_heif  # noqa: F401
        buf = io.BytesIO()
        Image.new("RGB", (640, 480), (10, 200, 10)).save(buf, "HEIF")
        data = buf.getvalue()
    except Exception:
        data = b"\0\0\0\x18ftypheic\0\0\0\0mif1heic" + b"\0" * 100
    r = upload(client, ("IMG_0001.HEIC", data, "image/heic"))
    if photos_mod.HEIF_SUPPORTED:
        assert r.status_code == 200, r.text
        assert (r.json()["uploaded"][0]["width"], r.json()["uploaded"][0]["height"]) == (640, 480)
    else:
        assert r.status_code == 400 and "HEIC" in r.json()["detail"]


def test_delete_photo(client, tmp_path):
    p = upload(client, ("a.jpg", jpeg(), "image/jpeg")).json()["uploaded"][0]
    assert client.request("DELETE", f"/api/photos/{p['id']}", json={"pin": "0000"}).status_code == 403
    assert client.request("DELETE", f"/api/photos/{p['id']}", json={}).status_code == 403
    assert client.request("DELETE", f"/api/photos/{p['id']}", json={"pin": PIN}).status_code == 200
    assert client.get(p["thumb_url"]).status_code == 404
    assert client.get(p["display_url"]).status_code == 404
    assert client.get("/api/photos").json() == []
    for sub in ("originals", "display", "thumbs"):
        assert list((tmp_path / "data" / "photos" / sub).iterdir()) == []
    assert client.request("DELETE", f"/api/photos/{p['id']}", json={"pin": PIN}).status_code == 404


def test_albums_and_screensaver_settings(client):
    trip = client.post("/api/albums", json={"name": "Summer trip"}).json()
    assert trip["name"] == "Summer trip" and trip["photo_count"] == 0
    assert client.post("/api/albums", json={"name": " "}).status_code == 400
    upload(client, ("a.jpg", jpeg(), "image/jpeg"), album_id=trip["id"])
    upload(client, ("b.jpg", jpeg(), "image/jpeg"))
    assert upload(client, ("c.jpg", jpeg(), "image/jpeg"), album_id="al_missing").status_code == 404
    assert [p["filename"] for p in client.get(f"/api/photos?album={trip['id']}").json()] == ["a.jpg"]
    assert len(client.get("/api/photos").json()) == 2

    s = client.get("/api/settings").json()
    assert s["screensaver_album"] is None and s["screensaver_seconds"] == 10
    assert s["idle_minutes"] == {"hallway": 5, "kitchen": 3, "phone": 0}
    r = client.patch("/api/settings", json={"pin": PIN, "screensaver_album": trip["id"], "screensaver_seconds": 20,
                                            "idle_minutes": {"kitchen": 10}})
    assert r.status_code == 200, r.text
    assert r.json()["screensaver_album"] == trip["id"] and r.json()["screensaver_seconds"] == 20
    assert r.json()["idle_minutes"] == {"hallway": 5, "kitchen": 10, "phone": 0}
    assert client.patch("/api/settings", json={"pin": PIN, "idle_minutes": 7}).json()["idle_minutes"] == \
        {"hallway": 7, "kitchen": 7, "phone": 0}
    assert client.patch("/api/settings", json={"pin": PIN, "screensaver_seconds": 1}).status_code == 400
    assert client.patch("/api/settings", json={"pin": PIN, "screensaver_album": "nope"}).status_code == 400
    assert client.patch("/api/settings", json={"pin": PIN, "idle_minutes": {"attic": 1}}).status_code == 400

    assert client.request("DELETE", f"/api/albums/{trip['id']}", json={"pin": "0000"}).status_code == 403
    r = client.request("DELETE", f"/api/albums/{trip['id']}", json={"pin": PIN})
    assert r.json() == {"ok": True, "deleted_photos": 1}
    assert client.get("/api/settings").json()["screensaver_album"] is None
    assert [a["name"] for a in client.get("/api/albums").json()] == ["Family"]
    assert len(client.get("/api/photos").json()) == 1
