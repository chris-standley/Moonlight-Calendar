"""Now playing / speaker control against a fake Home Assistant (REST via httpx.MockTransport, WebSocket via a
small local server). Run from backend/ with `python -m pytest`."""
from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import media  # noqa: E402
from moonlight.main import create_app  # noqa: E402

TOKEN = "supervisor-secret"
PROXY_TOKEN = "proxytoken123"
KITCHEN = "media_player.kitchen"
LOUNGE = "media_player.lounge"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-art" * 10
PIC = f"/api/media_player_proxy/{KITCHEN}?token={PROXY_TOKEN}&cache=abc123"
PIN = "1234"


def kitchen_state(**over):
    attrs = {
        "friendly_name": "Kitchen", "supported_features": 1 | 4 | 8 | 16 | 32 | 16384 | 32768 | 262144 | 2,
        "volume_level": 0.35, "is_volume_muted": False, "media_content_type": "music",
        "media_title": "Blue Hour", "media_artist": "The Paper Kites", "media_album_name": "Twelvefour",
        "media_duration": 241, "media_position": 63, "media_position_updated_at": "2026-10-10T09:00:00+00:00",
        "shuffle": False, "repeat": "off", "entity_picture": PIC, "app_id": "music_assistant",
        "mass_player_type": "player", "active_queue": "kitchen_queue", "source": "Music Assistant Queue",
    }
    state = over.pop("state", "playing")
    attrs.update(over)
    return {"entity_id": KITCHEN, "state": state, "attributes": {k: v for k, v in attrs.items() if v is not None},
            "last_changed": "2026-10-10T09:00:00+00:00"}


class FakeHA:
    """Answers like HA's REST API behind the Supervisor proxy; records service calls and checks the token."""

    def __init__(self):
        self.states = {
            KITCHEN: kitchen_state(),
            LOUNGE: {"entity_id": LOUNGE, "state": "off", "attributes": {"friendly_name": "Lounge TV",
                                                                         "entity_picture": "/api/x?token=lounge"}},
            "light.kitchen": {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
        }
        self.calls: list[tuple[str, str, dict]] = []
        self.requests: list[httpx.Request] = []
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        url = request.url
        if url.host == "art.example":
            return httpx.Response(200, content=b"external-art", headers={"content-type": "image/jpeg"})
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"message": "Unauthorized"})
        path = url.path
        if path == f"/core/api/media_player_proxy/{KITCHEN}":
            if url.params.get("token") != PROXY_TOKEN:
                return httpx.Response(403)
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        if request.method == "GET" and path == "/core/api/states":
            return httpx.Response(200, json=list(self.states.values()))
        if request.method == "GET" and path.startswith("/core/api/states/"):
            eid = path.rsplit("/", 1)[1]
            if eid not in self.states:
                return httpx.Response(404, json={"message": "Entity not found."})
            return httpx.Response(200, json=self.states[eid])
        if request.method == "GET" and path == "/core/api/config/config_entries/entry":
            assert url.params.get("domain") == "music_assistant"
            return httpx.Response(200, json=[{"entry_id": "ma_entry", "domain": "music_assistant", "state": "loaded"}])
        if request.method == "POST" and path.startswith("/core/api/services/"):
            domain, service = path.split("/")[-2:]
            data = json.loads(request.content)
            self.calls.append((domain, service, data))
            if domain == "music_assistant" and service == "get_library":
                assert "return_response" in url.query.decode()
                items = {"playlist": [{"media_type": "playlist", "uri": "library://playlist/1", "name": "Sunday Kitchen"}],
                         "radio": [{"media_type": "radio", "uri": "library://radio/7", "name": "Jazz FM"}]}
                return httpx.Response(200, json={"changed_states": [], "service_response": {
                    "items": items[data["media_type"]], "limit": data["limit"], "offset": 0}})
            st = self.states.get(data.get("entity_id"))
            if domain == "media_player" and st:
                a = st["attributes"]
                if service == "media_play_pause":
                    st["state"] = "paused" if st["state"] == "playing" else "playing"
                elif service == "volume_set":
                    a["volume_level"] = data["volume_level"]
                elif service == "volume_mute":
                    a["is_volume_muted"] = data["is_volume_muted"]
                elif service == "media_next_track":
                    a["media_title"] = "Next Song"
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": "Not found"})


def make_service(fake: FakeHA, **kw) -> media.MediaService:
    return media.MediaService("http://supervisor/core/api", TOKEN, transport=httpx.MockTransport(fake.handler), **kw)


@pytest.fixture
def fake():
    return FakeHA()


@pytest.fixture
def client(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("MOONLIGHT_MEDIA_ENTITY", KITCHEN)
    media.reset()
    media.set_service(make_service(fake))
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, auth_enabled=False)
    c = TestClient(app)
    c.patch("/api/settings", json={"pin": PIN})  # first PIN becomes the household PIN
    yield c
    media.reset()


# ---------------------------------------------------------------- mapping

def test_now_playing_mapping(client, fake):
    r = client.get("/api/media/now-playing?layout=kitchen").json()
    assert r["configured"] and r["entity"] == KITCHEN and r["name"] == "Kitchen"
    assert r["state"] == "playing" and r["show"] is True
    assert (r["title"], r["artist"], r["album"]) == ("Blue Hour", "The Paper Kites", "Twelvefour")
    assert r["duration"] == 241 and r["position"] == 63
    assert r["position_updated_at"] == "2026-10-10T09:00:00+00:00"
    assert r["volume"] == 0.35 and r["muted"] is False and r["shuffle"] is False and r["repeat"] == "off"
    assert r["music_assistant"] is True and r["app"] == "music_assistant" and r["source"] == "Music Assistant Queue"
    assert r["has_art"] and r["art_url"].startswith("/api/media/art?layout=kitchen&v=")
    assert r["supports"] == {"play_pause": True, "previous": True, "next": True, "volume": True, "mute": True,
                             "shuffle": True, "repeat": True, "seek": True}
    assert r["reachable"] and r["error"] is None and r["server_time"]
    body = json.dumps(r)
    assert PROXY_TOKEN not in body and TOKEN not in body and "media_player_proxy" not in body


@pytest.mark.parametrize("state,title,show", [
    ("off", None, False), ("idle", None, False), ("standby", None, False), ("unavailable", None, False),
    ("idle", "Last song", True), ("paused", "Paused song", True), ("buffering", None, True),
])
def test_show_rules(state, title, show):
    st = kitchen_state(state=state, media_title=title)
    assert media.now_playing("kitchen", KITCHEN, st)["show"] is show


def test_minimal_player_has_no_extras():
    st = {"entity_id": KITCHEN, "state": "playing", "attributes": {"media_title": "Radio", "supported_features": 1}}
    r = media.now_playing("kitchen", KITCHEN, st)
    assert r["volume"] is None and r["shuffle"] is None and r["repeat"] is None and r["has_art"] is False
    assert r["music_assistant"] is False and r["supports"]["play_pause"] and not r["supports"]["next"]


def test_not_configured_for_hallway(client):
    r = client.get("/api/media/now-playing?layout=hallway").json()
    assert r["configured"] is False and r["show"] is False and r["entity"] is None
    assert client.post("/api/media/command", json={"layout": "hallway", "action": "next"}).status_code == 409
    assert client.get("/api/media/now-playing?layout=attic").status_code == 400


def test_entity_missing_in_ha(client, fake):
    del fake.states[KITCHEN]
    r = client.get("/api/media/now-playing").json()
    assert r["state"] == "unavailable" and r["show"] is False and "not found" in r["error"]


def test_ha_unreachable(client, fake):
    fake.down = True
    r = client.get("/api/media/now-playing").json()
    assert r["state"] == "unavailable" and r["reachable"] is False and r["show"] is False
    assert client.post("/api/media/command", json={"action": "next"}).status_code == 502
    assert client.get("/api/media/players").status_code == 502


def test_short_outage_keeps_last_state(fake):
    clock = [100.0]
    svc = make_service(fake, clock=lambda: clock[0])
    st, err = asyncio.run(svc.get_state(KITCHEN))
    assert st["state"] == "playing" and err is None
    fake.down = True
    clock[0] += 30  # past the REST cache, within the stale window
    st, err = asyncio.run(svc.get_state(KITCHEN))
    assert st["state"] == "playing" and err is None
    clock[0] += 120
    st, err = asyncio.run(svc.get_state(KITCHEN))
    assert st is None and err == "Home Assistant is unreachable"


def test_no_home_assistant(tmp_path, monkeypatch):
    monkeypatch.setenv("MOONLIGHT_MEDIA_ENTITY", KITCHEN)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("MOONLIGHT_HA_TOKEN", raising=False)
    media.reset()
    c = TestClient(create_app(db_path=str(tmp_path / "n.db"), demo=False, auth_enabled=False))
    r = c.get("/api/media/now-playing").json()
    assert r["configured"] and r["show"] is False and r["error"]
    assert c.get("/api/media/players").status_code == 409
    assert c.get("/api/media/favourites").json() == []
    media.reset()


# ---------------------------------------------------------------- commands

@pytest.mark.parametrize("action,value,service,extra", [
    ("play_pause", None, "media_play_pause", {}),
    ("play", None, "media_play", {}),
    ("pause", None, "media_pause", {}),
    ("next", None, "media_next_track", {}),
    ("previous", None, "media_previous_track", {}),
    ("volume_set", 0.6, "volume_set", {"volume_level": 0.6}),
    ("volume_mute", True, "volume_mute", {"is_volume_muted": True}),
    ("shuffle_set", True, "shuffle_set", {"shuffle": True}),
    ("repeat_set", "all", "repeat_set", {"repeat": "all"}),
])
def test_commands_map_to_services(client, fake, action, value, service, extra):
    r = client.post("/api/media/command", json={"layout": "kitchen", "action": action, "value": value})
    assert r.status_code == 200, r.text
    assert fake.calls == [("media_player", service, {"entity_id": KITCHEN, **extra})]


def test_command_returns_fresh_state(client, fake):
    r = client.post("/api/media/command", json={"action": "play_pause"}).json()
    assert r["state"] == "paused"
    r = client.post("/api/media/command", json={"action": "volume_set", "value": 0.8}).json()
    assert r["volume"] == 0.8


@pytest.mark.parametrize("body", [
    {"action": "volume_set", "value": 1.5}, {"action": "volume_set", "value": "loud"},
    {"action": "volume_mute", "value": "yes"}, {"action": "repeat_set", "value": "twice"},
    {"action": "turn_off"}, {"action": "shuffle_set"}, {},
])
def test_bad_commands(client, fake, body):
    assert client.post("/api/media/command", json=body).status_code == 400
    assert fake.calls == []


def test_commands_only_reach_the_configured_entity(client, fake):
    r = client.post("/api/media/command", json={"action": "next", "entity_id": LOUNGE})
    assert r.status_code == 200
    assert [c[2]["entity_id"] for c in fake.calls] == [KITCHEN]


# ---------------------------------------------------------------- album art

def test_art_proxy(client, fake):
    np = client.get("/api/media/now-playing").json()
    r = client.get(np["art_url"])
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert "immutable" in r.headers["cache-control"]
    proxied = [q for q in fake.requests if q.url.path.endswith("media_player_proxy/" + KITCHEN)]
    assert len(proxied) == 1 and proxied[0].url.params["token"] == PROXY_TOKEN
    # Cached by the picture's hash: a second load doesn't go back to HA.
    assert client.get(np["art_url"]).content == PNG
    assert len([q for q in fake.requests if "media_player_proxy" in q.url.path]) == 1
    for h, v in r.headers.items():
        assert TOKEN not in v and PROXY_TOKEN not in v


def test_art_only_for_the_configured_players_current_picture(client, fake):
    assert client.get("/api/media/art?layout=kitchen&v=nothash").status_code == 404
    lounge_key = media.art_key("/api/x?token=lounge")
    assert client.get(f"/api/media/art?layout=kitchen&v={lounge_key}").status_code == 404
    assert client.get(f"/api/media/art?layout=hallway&v={lounge_key}").status_code == 404
    assert not [q for q in fake.requests if q.url.path == "/core/api/x"]


def test_art_from_public_url_gets_no_token(client, fake):
    fake.states[KITCHEN] = kitchen_state(entity_picture="https://art.example/cover.jpg")
    np = client.get("/api/media/now-playing").json()
    r = client.get(np["art_url"])
    assert r.status_code == 200 and r.content == b"external-art"
    ext = [q for q in fake.requests if q.url.host == "art.example"]
    assert ext and all("authorization" not in q.headers for q in ext)


def test_art_prefers_local_proxy_path(fake):
    attrs = {"entity_picture": "https://art.example/cover.jpg", "entity_picture_local": PIC}
    assert media.picture_of(attrs) == PIC


def test_art_for_unreachable_ha(client, fake):
    np = client.get("/api/media/now-playing").json()
    fake.down = True
    assert client.get(np["art_url"]).status_code == 404


# ---------------------------------------------------------------- players, settings, favourites

def test_players_list(client):
    ps = client.get("/api/media/players").json()
    assert [p["entity_id"] for p in ps] == [KITCHEN, LOUNGE]
    assert ps[0]["music_assistant"] is True and ps[1]["music_assistant"] is False
    assert ps[0]["name"] == "Kitchen"


def test_settings_per_layout(client, fake):
    s = client.get("/api/settings").json()
    assert s["media_players"] == {"hallway": "", "kitchen": KITCHEN, "phone": ""}
    r = client.patch("/api/settings", json={"pin": PIN, "media_players": {"hallway": LOUNGE}})
    assert r.status_code == 200 and r.json()["media_players"]["hallway"] == LOUNGE
    assert client.get("/api/media/now-playing?layout=hallway").json()["entity"] == LOUNGE
    r = client.patch("/api/settings", json={"pin": PIN, "media_players": {"kitchen": ""}})
    assert r.json()["media_players"]["kitchen"] == ""
    assert client.get("/api/media/now-playing?layout=kitchen").json()["configured"] is False
    for bad in ({"kitchen": "light.kitchen"}, {"attic": KITCHEN}, "media_player.x", {"kitchen": 3}):
        assert client.patch("/api/settings", json={"pin": PIN, "media_players": bad}).status_code == 400
    assert client.patch("/api/settings", json={"pin": "0000", "media_players": {"kitchen": KITCHEN}}).status_code == 403


def test_favourites_and_quick_play(client, fake):
    favs = client.get("/api/media/favourites").json()
    assert favs == [{"uri": "library://playlist/1", "name": "Sunday Kitchen", "media_type": "playlist"},
                    {"uri": "library://radio/7", "name": "Jazz FM", "media_type": "radio"}]
    lib = [c for c in fake.calls if c[1] == "get_library"]
    assert lib[0][2] == {"config_entry_id": "ma_entry", "media_type": "playlist", "favorite": True, "limit": 10}
    fake.calls.clear()
    r = client.post("/api/media/play", json={"uri": "library://radio/7"})
    assert r.status_code == 200
    assert fake.calls == [("music_assistant", "play_media", {"entity_id": KITCHEN, "media_id": "library://radio/7",
                                                             "media_type": "radio", "enqueue": "replace"})]
    assert client.post("/api/media/play", json={"uri": "spotify://anything"}).status_code == 404


def test_no_favourites_for_non_ma_player(client, fake):
    st = kitchen_state()
    st["attributes"].pop("mass_player_type")
    fake.states[KITCHEN] = st
    assert client.get("/api/media/favourites").json() == []


# ---------------------------------------------------------------- live updates over the WebSocket

class FakeHAWebSocket:
    """HA's WebSocket API, enough for auth + subscribe_trigger; `push()` sends a state change."""

    def __init__(self, token=TOKEN):
        self.token = token
        self.conns: list = []
        self.subscriptions: list[dict] = []
        self.server = None
        self.port = 0

    async def handler(self, ws):
        await ws.send(json.dumps({"type": "auth_required", "ha_version": "2026.10.0"}))
        msg = json.loads(await ws.recv())
        if msg.get("access_token") != self.token:
            await ws.send(json.dumps({"type": "auth_invalid", "message": "Invalid access token"}))
            return
        await ws.send(json.dumps({"type": "auth_ok", "ha_version": "2026.10.0"}))
        msg = json.loads(await ws.recv())
        self.subscriptions.append(msg)
        await ws.send(json.dumps({"id": msg["id"], "type": "result", "success": True, "result": None}))
        self.conns.append(ws)
        try:
            await ws.wait_closed()
        finally:
            self.conns.remove(ws)

    async def start(self):
        from websockets.asyncio.server import serve

        self.server = await serve(self.handler, "127.0.0.1", self.port)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    async def push(self, entity, to_state):
        for ws in list(self.conns):
            await ws.send(json.dumps({"id": 1, "type": "event", "event": {"variables": {"trigger": {
                "platform": "state", "entity_id": entity, "from_state": None, "to_state": to_state}}}}))


async def wait_for(cond, timeout=5.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        if loop.time() > end:
            raise AssertionError("timed out")
        await asyncio.sleep(0.02)


def test_websocket_live_updates_and_ha_restart(fake):
    async def scenario():
        ha_ws = FakeHAWebSocket()
        await ha_ws.start()
        changes = []

        async def on_change():
            changes.append(1)

        svc = make_service(fake, ws_url=f"ws://127.0.0.1:{ha_ws.port}", on_change=on_change,
                           poll_seconds=0.05, backoff=(0.3,))
        svc.set_watched({KITCHEN})
        svc.start()
        await wait_for(lambda: svc.ws_connected)
        sub = ha_ws.subscriptions[0]
        assert sub["type"] == "subscribe_trigger"
        assert sub["trigger"] == {"platform": "state", "entity_id": [KITCHEN]}
        assert svc.states[KITCHEN]["state"] == "playing"  # caught up over REST after subscribing

        # A pushed change lands in the cache and notifies screens (no REST needed).
        n_req = len(fake.requests)
        await ha_ws.push(KITCHEN, kitchen_state(media_title="Pushed Song"))
        await wait_for(lambda: svc.states[KITCHEN]["attributes"]["media_title"] == "Pushed Song")
        await wait_for(lambda: changes)
        st, err = await svc.get_state(KITCHEN)
        assert st["attributes"]["media_title"] == "Pushed Song" and len(fake.requests) == n_req
        # Changes for other entities are ignored.
        await ha_ws.push(LOUNGE, {"entity_id": LOUNGE, "state": "playing", "attributes": {}})
        await asyncio.sleep(0.1)
        assert LOUNGE not in svc.states

        # HA restarts: the WebSocket drops, polling takes over and still sees changes.
        await ha_ws.stop()
        await wait_for(lambda: not svc.ws_connected)
        fake.states[KITCHEN] = kitchen_state(state="paused", media_title="Polled Song")
        await wait_for(lambda: svc.states[KITCHEN]["attributes"]["media_title"] == "Polled Song")
        # HA is back: the WebSocket reconnects and resubscribes.
        await ha_ws.start()
        await wait_for(lambda: svc.ws_connected and svc.ws_sessions == 2)
        assert len(ha_ws.subscriptions) == 2

        # Changing the configured players resubscribes with the new set.
        svc.set_watched({KITCHEN, LOUNGE})
        await wait_for(lambda: len(ha_ws.subscriptions) == 3 and svc.ws_connected)
        assert ha_ws.subscriptions[2]["trigger"]["entity_id"] == [KITCHEN, LOUNGE]
        await svc.stop()
        await ha_ws.stop()

    asyncio.run(scenario())


def test_websocket_bad_token_falls_back_to_polling(fake):
    async def scenario():
        ha_ws = FakeHAWebSocket(token="something-else")
        await ha_ws.start()
        svc = make_service(fake, ws_url=f"ws://127.0.0.1:{ha_ws.port}", poll_seconds=0.05, backoff=(0.2,))
        svc.set_watched({KITCHEN})
        svc.start()
        await wait_for(lambda: KITCHEN in svc.states)
        assert not svc.ws_connected
        fake.states[KITCHEN] = kitchen_state(media_title="Seen by polling")
        await wait_for(lambda: svc.states[KITCHEN]["attributes"]["media_title"] == "Seen by polling")
        await svc.stop()
        await ha_ws.stop()

    asyncio.run(scenario())


def test_ws_url_for(monkeypatch):
    monkeypatch.delenv("MOONLIGHT_HA_WS_URL", raising=False)
    assert media.ws_url_for("http://supervisor/core/api") == "ws://supervisor/core/websocket"
    assert media.ws_url_for("http://ha.local:8123/api") == "ws://ha.local:8123/api/websocket"
    assert media.ws_url_for("https://ha.example.com/api/") == "wss://ha.example.com/api/websocket"


def test_websocket_broadcasts_media_topic_to_screens(client, fake):
    """End to end: the app starts the watcher, and a change makes it broadcast `media` to connected screens."""
    svc = media.service()
    svc.on_change = media._broadcast

    def no_ws(url):
        raise OSError("no websocket in this test")

    svc.ws_connect = no_ws
    svc.poll_seconds = 0.05
    with client:  # one event loop for startup (watcher), requests and the screen's socket
        with client.websocket_connect("/api/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            assert svc.watched == {KITCHEN} and svc._task is not None
            client.post("/api/media/command", json={"action": "next"})
            assert ws.receive_json() == {"type": "changed", "topic": "media"}
    assert svc._task is None  # stopped on shutdown


def test_state_copy_is_not_shared(fake):
    # _store compares state + attributes, so a mutated dict from HA counts as a change.
    svc = make_service(fake)
    a = kitchen_state()
    assert svc._store(KITCHEN, a) is True
    assert svc._store(KITCHEN, copy.deepcopy(a)) is False
    b = copy.deepcopy(a)
    b["attributes"]["volume_level"] = 0.9
    assert svc._store(KITCHEN, b) is True
