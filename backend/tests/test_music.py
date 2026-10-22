"""The Music tab: queue, library, play now/next/add, rooms, and the optional Music Assistant connection, against a
fake Home Assistant (and a fake Music Assistant). Run from backend/ with `python -m pytest`."""
from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import media, music  # noqa: E402
from moonlight.main import create_app  # noqa: E402
from test_media import KITCHEN, PIN, TOKEN, FakeHA, kitchen_state  # noqa: E402

SONOS = "media_player.kitchen_sonos_sonos"
LIVING = "media_player.living_room"
LIVING_SONOS = "media_player.living_room_sonos"
MA_IMG = "http://10.0.0.5:8095/imageproxy/abc?size=0"
GROUPING = 524288


def sonos_state(**over):
    attrs = {"friendly_name": "Kitchen Sonos", "supported_features": 1 | 4 | 8 | 16 | 32 | 16384 | GROUPING | 2097152,
             "volume_level": 0.2, "media_title": "Two", "media_artist": "B", "queue_position": 2, "queue_size": 3,
             "group_members": [SONOS]}
    state = over.pop("state", "playing")
    attrs.update(over)
    return {"entity_id": SONOS, "state": state, "attributes": attrs}


class MusicHA(FakeHA):
    def __init__(self):
        super().__init__()
        self.states[KITCHEN] = kitchen_state(supported_features=1 | 4 | 8 | 16 | 32 | GROUPING, group_members=[],
                                             active_queue=KITCHEN)
        self.states[LIVING] = {"entity_id": LIVING, "state": "idle", "attributes": {
            "friendly_name": "Living room", "supported_features": 4 | GROUPING, "volume_level": 0.1,
            "mass_player_type": "player", "group_members": []}}
        self.states[SONOS] = sonos_state()
        self.states[LIVING_SONOS] = {"entity_id": LIVING_SONOS, "state": "idle", "attributes": {
            "friendly_name": "Living room Sonos", "supported_features": 4 | GROUPING, "group_members": [LIVING_SONOS]}}
        self.sonos_queue = [{"media_title": t, "media_artist": a, "media_album_name": "Alb", "media_content_id": "x"}
                            for t, a in (("One", "A"), ("Two", "B"), ("Three", "C"))]

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "10.0.0.5":
            self.requests.append(request)
            return httpx.Response(200, content=b"ma-img", headers={"content-type": "image/jpeg"})
        if request.url.path == "/core/api/template" and request.headers.get("authorization") == f"Bearer {TOKEN}":
            assert "integration_entities('sonos')" in json.loads(request.content)["template"]
            return httpx.Response(200, text=json.dumps([SONOS, LIVING_SONOS]))
        if request.method == "POST" and request.url.path.startswith("/core/api/services/"):
            domain, service = request.url.path.split("/")[-2:]
            data = json.loads(request.content)
            resp = None
            if (domain, service) == ("sonos", "get_queue"):
                resp = {data["entity_id"]: self.sonos_queue}
            elif (domain, service) == ("music_assistant", "get_queue"):
                resp = {data["entity_id"]: {"queue_id": KITCHEN, "items": 9, "current_index": 4, "current_item": {
                    "queue_item_id": "q4", "name": "Blue Hour", "duration": 241, "media_item": {
                        "name": "Blue Hour", "artists": [{"name": "The Paper Kites"}], "image": MA_IMG}},
                    "next_item": {"queue_item_id": "q5", "name": "Bloom", "duration": 200, "media_item": {
                        "name": "Bloom", "artists": [{"name": "The Paper Kites"}], "album": {"name": "Woodland"},
                        "image": MA_IMG}}}}
            elif (domain, service) == ("music_assistant", "search"):
                resp = {"albums": [{"media_type": "album", "uri": "spotify://album/1", "name": "Woodland",
                                    "artists": [{"name": "The Paper Kites"}], "image": MA_IMG}],
                        "tracks": [{"media_type": "track", "uri": "spotify://track/2", "name": "Bloom"}],
                        "podcasts": [{"media_type": "podcast", "uri": "library://podcast/3", "name": "Kids' Stories"}]}
            if resp is not None:
                self.requests.append(request)
                self.calls.append((domain, service, data))
                return httpx.Response(200, json={"changed_states": [], "service_response": resp})
        return super().handler(request)


class FakeWS:
    """One WebSocket conversation: HA's auth, then answers from `answer(cmd)`."""

    def __init__(self, answer, greeting=None, auth_ok=True):
        self.answer = answer
        self.out = [greeting or {"type": "auth_required"}]
        self.auth_ok = auth_ok
        self.sent: list[dict] = []

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        if msg.get("type") == "auth":
            self.out.append({"type": "auth_ok" if self.auth_ok else "auth_invalid"})
        else:
            self.out.extend(self.answer(msg))

    async def recv(self):
        return json.dumps(self.out.pop(0))

    async def close(self):
        pass


def ws_factory(answer, log, **kw):
    @contextlib.asynccontextmanager
    async def connect(url):
        ws = FakeWS(answer, **kw)
        log.append((url, ws))
        yield ws
    return connect


def ha_browse(msg):
    cid = msg.get("media_content_id")
    if cid is None:
        children = [
            {"title": "Albums", "media_class": "directory", "media_content_type": "music_assistant",
             "media_content_id": "albums", "can_play": False, "can_expand": True, "thumbnail": None},
            {"title": "Camera", "media_class": "app", "media_content_type": "app",
             "media_content_id": "media-source://camera", "can_play": False, "can_expand": True,
             "thumbnail": "/api/brands/integration/camera/logo.png"},
        ]
        result = {"title": "Music Assistant", "media_class": "directory", "media_content_type": "music_assistant",
                  "media_content_id": "", "can_play": False, "can_expand": True, "children": children}
    elif cid == "albums":
        result = {"title": "Albums", "media_class": "directory", "media_content_type": "album", "media_content_id": "albums",
                  "can_play": False, "can_expand": True, "children": [
                      {"title": "Woodland", "media_class": "album", "media_content_type": "album",
                       "media_content_id": "library://album/1", "can_play": True, "can_expand": True, "thumbnail": MA_IMG}]}
    else:
        return [{"id": msg["id"], "type": "result", "success": False, "error": {"message": "Media not found"}}]
    return [{"id": msg["id"], "type": "result", "success": True, "result": result}]


@pytest.fixture
def fake():
    return MusicHA()


@pytest.fixture
def ws_log():
    return []


@pytest.fixture
def client(tmp_path, fake, ws_log, monkeypatch):
    monkeypatch.setenv("MOONLIGHT_MEDIA_ENTITY", KITCHEN)
    media.reset()
    music._detected.clear()
    media.set_service(media.MediaService("http://supervisor/core/api", TOKEN, transport=httpx.MockTransport(fake.handler),
                                         ws_connect=ws_factory(ha_browse, ws_log)))
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, auth_enabled=False)
    c = TestClient(app)
    c.patch("/api/settings", json={"pin": PIN})
    yield c
    media.reset()
    music.set_ma_connect(None)
    music._detected.clear()


def use_speaker(client, entity):
    assert client.patch("/api/settings", json={"pin": PIN, "media_players": {"compact": entity}}).status_code == 200


# ---------------------------------------------------------------- library

def test_browse_hides_home_assistant_apps_and_proxies_thumbnails(client, fake, ws_log):
    root = client.get("/api/media/browse").json()
    assert [i["title"] for i in root["items"]] == ["Albums"]
    assert ws_log[-1][1].sent[-1] == {"id": 1, "type": "media_player/browse_media", "entity_id": KITCHEN}
    albums = client.get("/api/media/browse", params={"id": "albums", "type": "music_assistant"}).json()
    item = albums["items"][0]
    assert (item["id"], item["type"], item["can_play"], item["can_expand"]) == ("library://album/1", "album", True, True)
    assert item["thumb"].startswith("/api/media/thumb?k=") and "10.0.0.5" not in json.dumps(albums)
    r = client.get(item["thumb"])
    assert r.status_code == 200 and r.content == b"ma-img"
    got = [q for q in fake.requests if q.url.host == "10.0.0.5"][-1]
    assert got.url.params["size"] == "300" and "authorization" not in got.headers  # no HA token to other hosts
    assert client.get("/api/media/thumb?k=nothing-handed-out").status_code == 404
    assert client.get("/api/media/browse", params={"id": "nope", "type": "x"}).status_code == 400


def test_search_needs_music_assistant(client, fake):
    found = client.get("/api/media/search", params={"q": "paper kites"}).json()
    assert [(f["title"], f["type"], f["subtitle"], f["can_expand"]) for f in found] == [
        ("Woodland", "album", "The Paper Kites", True), ("Kids' Stories", "podcast", None, True),
        ("Bloom", "track", None, False)]
    call = [c for c in fake.calls if c[1] == "search"][0][2]
    assert call["name"] == "paper kites" and "podcast" in call["media_type"]
    use_speaker(client, SONOS)
    assert client.get("/api/media/search", params={"q": "x"}).status_code == 409


@pytest.mark.parametrize("enqueue", ["replace", "next", "add"])
def test_play_now_next_or_add(client, fake, enqueue):
    r = client.post("/api/media/play", json={"id": "library://album/1", "type": "album", "enqueue": enqueue})
    assert r.status_code == 200 and r.json()["entity"] == KITCHEN
    assert ("music_assistant", "play_media", {"entity_id": KITCHEN, "media_id": "library://album/1",
                                              "media_type": "album", "enqueue": enqueue}) in fake.calls


def test_play_on_a_plain_player_uses_media_player(client, fake):
    use_speaker(client, SONOS)
    client.post("/api/media/play", json={"id": "FV:2/5", "type": "favorite_item_id", "enqueue": "add"})
    assert ("media_player", "play_media", {"entity_id": SONOS, "media_content_id": "FV:2/5",
                                           "media_content_type": "favorite_item_id", "enqueue": "add"}) in fake.calls
    assert client.post("/api/media/play", json={"id": "x", "enqueue": "later"}).status_code == 400


# ---------------------------------------------------------------- queue

def test_sonos_queue_whole_list_and_actions(client, fake):
    use_speaker(client, SONOS)
    q = client.get("/api/media/queue").json()
    assert q["source"] == "sonos" and q["full"] and q["total"] == 3 and q["current"] == 1
    assert [(i["index"], i["title"], i["current"]) for i in q["items"]] == [(1, "Two", True), (2, "Three", False)]
    assert q["items"][0]["thumb"] is None or q["items"][0]["thumb"].startswith("/api/media/")
    fake.calls.clear()
    assert client.post("/api/media/queue", json={"action": "play", "key": "2"}).status_code == 200
    assert client.post("/api/media/queue", json={"action": "remove", "key": 2}).status_code == 200
    assert fake.calls == [("sonos", "play_queue", {"entity_id": SONOS, "queue_position": 2}),
                          ("sonos", "remove_from_queue", {"entity_id": SONOS, "queue_position": 2})]
    assert client.post("/api/media/queue", json={"action": "next", "key": "2"}).status_code == 400


def test_sonos_queue_when_not_playing_from_it(client, fake):
    fake.states[SONOS] = sonos_state(media_title="Radio 2", queue_position=None)
    use_speaker(client, SONOS)
    q = client.get("/api/media/queue").json()
    assert q["current"] is None and [i["title"] for i in q["items"]] == ["One", "Two", "Three"]


def test_music_assistant_queue_through_home_assistant_is_up_next_only(client, fake):
    q = client.get("/api/media/queue").json()
    assert q["source"] == "music_assistant" and q["full"] is False and q["total"] == 9 and q["current"] == 4
    assert [(i["title"], i["artist"], i["current"], i["index"]) for i in q["items"]] == [
        ("Blue Hour", "The Paper Kites", True, 4), ("Bloom", "The Paper Kites", False, 5)]
    assert q["items"][0]["thumb"].startswith("/api/media/art")  # the now playing art
    assert q["items"][1]["album"] == "Woodland" and q["items"][1]["thumb"].startswith("/api/media/thumb")
    assert client.post("/api/media/queue", json={"action": "play", "key": "q5"}).status_code == 409


def test_queue_needs_a_speaker(client):
    use_speaker(client, "")
    assert client.get("/api/media/queue").status_code == 409


# ---------------------------------------------------------------- Music Assistant's own API (optional)

def ma_answer(store):
    def answer(msg):
        cmd, args = msg["command"], msg["args"]
        store.append((cmd, args))
        if cmd == "auth":
            ok = args["token"] == "ma-token"
            return [{"message_id": msg["message_id"], "result": {"user": "me"}} if ok else
                    {"message_id": msg["message_id"], "error_code": 20, "details": "Invalid token"}]
        if cmd == "player_queues/get":
            return [{"event": "queue_updated"}, {"message_id": msg["message_id"], "result": {
                "queue_id": args["queue_id"], "items": 3, "current_index": 1}}]
        if cmd == "player_queues/items":
            items = [{"queue_item_id": f"q{i}", "name": f"Song {i}", "duration": 100 + i,
                      "image": {"type": "thumb", "path": "/x.jpg", "provider": "file", "proxy_id": f"p{i}"},
                      "media_item": {"name": f"Song {i}", "artists": [{"name": "Band"}]}}
                     for i in range(args["offset"], 3)]
            return [{"message_id": msg["message_id"], "result": items[:1], "partial": True},
                    {"message_id": msg["message_id"], "result": items[1:]}]
        return [{"message_id": msg["message_id"], "result": None}]
    return answer


GREETING = {"server_id": "x", "server_version": "2.10.7", "schema_version": 33, "min_supported_schema_version": 24,
            "base_url": "http://10.0.0.5:8095"}


def test_music_assistant_connection_full_queue_and_actions(client, fake):
    store: list = []
    log: list = []
    music.set_ma_connect(ws_factory(ma_answer(store), log, greeting=GREETING))
    assert client.get("/api/media/music-assistant").json() == {"url": "", "detected_url": None, "token_set": False}
    # No address given: learnt from the image URLs Music Assistant gives Home Assistant.
    fake_lib = {"items": [{"media_type": "playlist", "uri": "library://playlist/1", "name": "P", "image": MA_IMG}]}
    orig = fake.handler

    def handler(request):
        if request.url.path.endswith("/services/music_assistant/get_library"):
            return httpx.Response(200, json={"service_response": {**fake_lib, "limit": 3, "offset": 0}})
        return orig(request)
    fake.handler = handler
    media.service().transport = httpx.MockTransport(handler)
    assert client.put("/api/media/music-assistant", json={"pin": PIN, "token": "wrong"}).status_code == 400
    assert client.put("/api/media/music-assistant", json={"pin": "0000", "token": "ma-token"}).status_code == 403
    r = client.put("/api/media/music-assistant", json={"pin": PIN, "token": "ma-token"})
    assert r.status_code == 200 and r.json() == {"url": "", "detected_url": "http://10.0.0.5:8095", "token_set": True}
    assert log[-1][0] == "ws://10.0.0.5:8095/ws"
    assert "ma-token" not in json.dumps(client.get("/api/settings").json())

    q = client.get("/api/media/queue").json()
    assert q["full"] and q["can_move"] and q["current"] == 1 and q["total"] == 3
    assert [(i["key"], i["title"], i["artist"], i["current"]) for i in q["items"]] == [
        ("q1", "Song 1", "Band", True), ("q2", "Song 2", "Band", False)]
    assert q["items"][1]["thumb"].startswith("/api/media/thumb")
    assert ("player_queues/items", {"queue_id": KITCHEN, "limit": music.QUEUE_AHEAD + 1, "offset": 1}) in store
    store.clear()
    for action in ("play", "remove", "next"):
        assert client.post("/api/media/queue", json={"action": action, "key": "q2"}).status_code == 200
    assert [s for s in store if s[0] != "auth"] == [
        ("player_queues/play_index", {"queue_id": KITCHEN, "index": "q2"}),
        ("player_queues/delete_item", {"queue_id": KITCHEN, "item_id_or_index": "q2"}),
        ("player_queues/move_item", {"queue_id": KITCHEN, "queue_item_id": "q2", "pos_shift": 0})]
    assert client.request("DELETE", "/api/media/music-assistant", json={"pin": PIN}).json()["token_set"] is False


def test_music_assistant_unreachable_falls_back_to_home_assistant(client, fake):
    @contextlib.asynccontextmanager
    async def down(url):
        raise OSError("connection refused")
        yield  # pragma: no cover
    music.set_ma_connect(down)
    from moonlight import db
    with db.connect() as c:
        db.set_setting(c, music.SETTINGS_KEY, {"url": "http://10.0.0.5:8095", "token": "ma-token"})
    q = client.get("/api/media/queue").json()
    assert q["source"] == "music_assistant" and q["full"] is False and len(q["items"]) == 2


# ---------------------------------------------------------------- rooms

def test_rooms_offer_same_kind_of_speaker(client, fake):
    r = client.get("/api/media/rooms").json()
    assert r["can_group"] and [(x["entity_id"], x["this"], x["grouped"]) for x in r["rooms"]] == [
        (KITCHEN, True, True), (LIVING, False, False)]  # Music Assistant players only
    use_speaker(client, SONOS)
    r = client.get("/api/media/rooms").json()
    assert [x["entity_id"] for x in r["rooms"]] == [SONOS, LIVING_SONOS]


def test_join_unjoin_and_room_volume(client, fake):
    fake.calls.clear()
    assert client.post("/api/media/rooms", json={"room": LIVING, "action": "join"}).status_code == 200
    assert client.post("/api/media/rooms", json={"room": LIVING, "action": "volume", "value": 0.4}).status_code == 200
    assert client.post("/api/media/rooms", json={"room": LIVING, "action": "mute", "value": True}).status_code == 200
    assert client.post("/api/media/rooms", json={"room": LIVING, "action": "unjoin"}).status_code == 200
    assert fake.calls == [
        ("media_player", "join", {"entity_id": KITCHEN, "group_members": [LIVING]}),
        ("media_player", "volume_set", {"entity_id": LIVING, "volume_level": 0.4}),
        ("media_player", "volume_mute", {"entity_id": LIVING, "is_volume_muted": True}),
        ("media_player", "unjoin", {"entity_id": LIVING})]
    # Only speakers it can group with; never any other entity.
    assert client.post("/api/media/rooms", json={"room": "media_player.lounge", "action": "volume", "value": 1}).status_code == 404
    assert client.post("/api/media/rooms", json={"room": "light.kitchen", "action": "join"}).status_code == 400
    assert client.post("/api/media/rooms", json={"room": KITCHEN, "action": "join"}).status_code == 400


# ---------------------------------------------------------------- a Music Assistant speaker fronting a Sonos one

def test_idle_music_assistant_speaker_hands_over_to_the_sonos_it_fronts(client, fake):
    fake.states[KITCHEN] = kitchen_state(state="idle", media_title=None, entity_picture=None, active_queue=SONOS)
    fake.states[SONOS] = sonos_state(state="paused")
    np = client.get("/api/media/now-playing").json()
    assert np["entity"] == KITCHEN and np["via"] == SONOS and np["title"] == "Two" and np["state"] == "paused"
    assert np["music_assistant"] is True and np["name"] == "Kitchen"
    fake.calls.clear()
    client.post("/api/media/command", json={"action": "play_pause"})
    assert fake.calls[0] == ("media_player", "media_play_pause", {"entity_id": SONOS})
    assert client.get("/api/media/queue").json()["source"] == "sonos"
    assert SONOS in media.watched_entities()
    # Once Music Assistant itself plays, it's shown again.
    fake.states[KITCHEN] = kitchen_state(active_queue=SONOS)
    media.service().states.clear()
    assert client.get("/api/media/now-playing").json()["via"] is None


def test_paired_screens_own_speaker_is_watched(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("MOONLIGHT_MEDIA_ENTITY", KITCHEN)
    media.reset()
    media.set_service(media.MediaService("http://supervisor/core/api", TOKEN, transport=httpx.MockTransport(fake.handler)))
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, auth_enabled=True)
    ha = TestClient(app, client=("172.30.32.2", 1), headers={"X-Ingress-Path": "/x"})
    ha.patch("/api/settings", json={"pin": PIN})
    screen = TestClient(app, client=("192.168.1.9", 1))
    start = screen.post("/api/pair/start", json={"layout": "compact"}).json()
    d = ha.post("/api/displays/approve", json={"code": start["code"], "pin": PIN}).json()
    ha.patch(f"/api/displays/{d['id']}", json={"pin": PIN, "setup": {"speaker": LIVING}})
    assert LIVING in media.watched_entities() and LIVING in media.service().watched
    media.reset()
