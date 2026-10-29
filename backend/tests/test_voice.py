"""Assist on the screens (voice.py): settings, the pipeline list, and the relay to a fake Home Assistant pipeline.
Run from backend/ with `python -m pytest`."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import media, voice  # noqa: E402
from moonlight.main import create_app  # noqa: E402

TOKEN = "supervisor-secret"
PIN = "1234"
KITCHEN = "media_player.kitchen"
PIPELINES = {"pipelines": [
    {"id": "p1", "name": "Home Assistant", "language": "en", "stt_engine": None, "tts_engine": "tts.piper",
     "conversation_engine": "conversation.home_assistant", "wake_word_entity": None, "wake_word_id": None},
    {"id": "p2", "name": "Moonlight", "language": "en", "stt_engine": "stt.whisper", "tts_engine": "tts.piper",
     "conversation_engine": "conversation.claude_conversation", "wake_word_entity": "wake_word.openwakeword",
     "wake_word_id": "ok_nabu"},
], "preferred_pipeline": "p1"}
MP3 = b"ID3fake-mp3" * 50


class FakePipelineHA:
    """HA's WebSocket API, enough for auth, the pipeline list and assist_pipeline/run. A run that starts at stt
    'hears' how many audio bytes came before the end-of-audio marker."""

    def __init__(self):
        self.sent: list = []  # everything Moonlight sent, after auth
        self.runs: list[dict] = []
        self.calls: list = []

    def connect(self, url):
        return FakeSocket(self)

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        if request.url.path == "/core/api/template":
            return httpx.Response(200, text="1")
        if request.url.path.startswith("/core/api/tts_proxy/"):
            return httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"})
        if request.url.path == "/core/api/services/media_player/play_media":
            self.calls.append(json.loads(request.content))
            return httpx.Response(200, json=[])
        return httpx.Response(404)


class FakeSocket:
    def __init__(self, ha: FakePipelineHA):
        self.ha = ha
        self.out: asyncio.Queue = asyncio.Queue()
        self.authed = False
        self.audio: dict[int, int] = {}
        self.handlers: dict[int, int] = {}  # handler id -> message id
        self.next_handler = 0
        self.out.put_nowait(json.dumps({"type": "auth_required"}))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def recv(self):
        item = await self.out.get()
        if item is None:
            raise ConnectionError("closed")
        return item

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.out.get()
        if item is None:
            raise StopAsyncIteration
        return item

    def event(self, mid, kind, data=None):
        self.out.put_nowait(json.dumps({"id": mid, "type": "event", "event": {"type": kind, "data": data or {}}}))

    async def send(self, raw):
        if isinstance(raw, bytes):
            mid = self.handlers.get(raw[0])
            if mid is None:
                return
            if len(raw) == 1:  # end of audio
                del self.handlers[raw[0]]
                self.finish(mid, f"heard {self.audio.get(mid, 0)} bytes")
            else:
                self.audio[mid] = self.audio.get(mid, 0) + len(raw) - 1
            return
        msg = json.loads(raw)
        if not self.authed:
            assert msg == {"type": "auth", "access_token": TOKEN}
            self.authed = True
            self.out.put_nowait(json.dumps({"type": "auth_ok"}))
            return
        self.ha.sent.append(msg)
        mid = msg.get("id")
        if msg["type"] == "assist_pipeline/pipeline/list":
            self.out.put_nowait(json.dumps({"id": mid, "type": "result", "success": True, "result": PIPELINES}))
        elif msg["type"] == "assist_pipeline/run":
            self.ha.runs.append(msg)
            if msg.get("pipeline") == "missing":
                self.out.put_nowait(json.dumps({"id": mid, "type": "result", "success": False,
                                                "error": {"code": "pipeline-not-found", "message": "Pipeline not found"}}))
                return
            self.out.put_nowait(json.dumps({"id": mid, "type": "result", "success": True, "result": None}))
            handler = None
            if msg["start_stage"] in ("stt", "wake_word"):
                self.next_handler += 1
                handler = self.next_handler
                self.handlers[handler] = mid
            self.event(mid, "run-start", {"pipeline": "p2", "runner_data": {"stt_binary_handler_id": handler}})
            if msg["start_stage"] == "wake_word":
                self.event(mid, "wake_word-start")
                self.event(mid, "wake_word-end", {"wake_word_output": {"wake_word_id": "ok_nabu",
                                                                       "wake_word_phrase": "Okay Nabu"}})
            if handler:
                self.event(mid, "stt-start")
            else:
                self.finish(mid, None, msg["input"]["text"])
        elif msg["type"] == "unsubscribe_events":
            self.handlers = {h: m for h, m in self.handlers.items() if m != msg["subscription"]}
            self.out.put_nowait(json.dumps({"id": mid, "type": "result", "success": True, "result": None}))

    def finish(self, mid, heard, text=None):
        if heard is not None:
            self.event(mid, "stt-vad-end")
            self.event(mid, "stt-end", {"stt_output": {"text": heard}})
        self.event(mid, "intent-start")
        said = heard or text
        self.event(mid, "intent-end", {"intent_output": {
            "response": {"speech": {"plain": {"speech": f"You said {said}"}}, "response_type": "action_done"},
            "conversation_id": "conv-1", "continue_conversation": said.endswith("?")}})
        if self.ha.runs[-1]["end_stage"] == "tts":
            self.event(mid, "tts-start")
            self.event(mid, "tts-end", {"tts_output": {"media_id": "media-source://tts/tts.piper?message=x",
                                                       "url": "/api/tts_proxy/abc.mp3", "mime_type": "audio/mpeg"}})
        self.event(mid, "run-end")


@pytest.fixture
def ha():
    return FakePipelineHA()


@pytest.fixture
def client(tmp_path, ha, monkeypatch):
    monkeypatch.setenv("MOONLIGHT_MEDIA_ENTITY", KITCHEN)
    media.reset()
    media.set_service(media.MediaService("http://supervisor/core/api", TOKEN, ws_connect=ha.connect,
                                         transport=httpx.MockTransport(ha.handler)))
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, auth_enabled=False)
    c = TestClient(app)
    c.patch("/api/settings", json={"pin": PIN})
    yield c
    media.reset()


def until(ws, kind):
    """Messages up to and including the first of `kind`."""
    got = []
    while True:
        m = ws.receive_json()
        got.append(m)
        if m["type"] == kind:
            return got


def test_settings_defaults_and_validation(client):
    s = client.get("/api/settings").json()["voice"]
    assert s == {"pipeline": "", "wake": {"large": False, "compact": False, "phone": False}, "replies": "screen"}
    r = client.patch("/api/settings", json={"pin": PIN, "voice": {"wake": {"large": True}, "replies": "speaker",
                                                                  "pipeline": "p2"}})
    assert r.status_code == 200
    assert r.json()["voice"] == {"pipeline": "p2", "wake": {"large": True, "compact": False, "phone": False},
                                 "replies": "speaker"}
    for bad in ({"replies": "loud"}, {"wake": {"tv": True}}, {"wake": {"large": "yes"}}, {"colour": 1}, "on"):
        assert client.patch("/api/settings", json={"pin": PIN, "voice": bad}).status_code == 400


def test_status_lists_pipelines_and_picks_one(client):
    st = client.get("/api/voice?layout=large").json()
    assert st["available"] is True and st["wake_engine"] is True
    assert [p["id"] for p in st["pipelines"]] == ["p1", "p2"]
    assert st["pipelines"][0]["stt"] is False and st["pipelines"][1]["stt"] is True
    assert st["pipeline"] == "p1"  # nothing chosen: HA's preferred one
    client.patch("/api/settings", json={"pin": PIN, "voice": {"pipeline": "p2", "wake": {"large": True}}})
    st = client.get("/api/voice?layout=large").json()
    assert st["pipeline"] == "p2" and st["wake"] is True
    assert client.get("/api/voice?layout=compact").json()["wake"] is False
    client.patch("/api/settings", json={"pin": PIN, "voice": {"pipeline": "gone"}})
    assert client.get("/api/voice").json()["pipeline"] == "p1"  # a deleted pipeline falls back


def test_status_without_home_assistant(client):
    media.set_service(None)
    st = client.get("/api/voice").json()
    assert st["available"] is False and "Home Assistant" in st["reason"]


def test_listen_streams_audio_and_plays_reply_here(client, ha):
    client.patch("/api/settings", json={"pin": PIN, "voice": {"pipeline": "p2"}})
    with client.websocket_connect("/api/voice/ws?layout=compact") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "start", "mode": "listen"})
        assert ws.receive_json() == {"type": "listening"}
        ws.send_bytes(b"\x00\x01" * 800)
        ws.send_bytes(b"\x00\x01" * 800)
        ws.send_json({"type": "stop"})
        got = until(ws, "done")
    kinds = [m["type"] for m in got]
    assert kinds == ["speech_end", "heard", "thinking", "reply", "audio", "done"]
    assert got[1]["text"] == "heard 3200 bytes"
    assert got[3] == {"type": "reply", "text": "You said heard 3200 bytes", "kind": "action_done", "continue": False,
                      "conversation_id": "conv-1"}
    run = ha.runs[0]
    assert run["start_stage"] == "stt" and run["end_stage"] == "tts" and run["pipeline"] == "p2"
    assert run["input"] == {"sample_rate": 16000}
    # The reply's audio comes through Moonlight; made-up keys don't.
    r = client.get(got[4]["url"])
    assert r.status_code == 200 and r.content == MP3 and r.headers["content-type"] == "audio/mpeg"
    assert client.get("/api/voice/audio/nope").status_code == 404


def test_text_follow_up_keeps_the_conversation(client, ha):
    with client.websocket_connect("/api/voice/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "mode": "text", "text": "what's on today?", "conversation_id": "conv-1"})
        got = until(ws, "done")
    reply = next(m for m in got if m["type"] == "reply")
    assert reply["continue"] is True  # a question back: the screen listens again
    run = ha.runs[0]
    assert run["start_stage"] == "intent" and run["input"] == {"text": "what's on today?"}
    assert run["conversation_id"] == "conv-1" and "pipeline" not in run  # HA's preferred one


def test_wake_word_run(client, ha):
    with client.websocket_connect("/api/voice/ws?layout=large") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "mode": "wake"})
        assert [m["type"] for m in until(ws, "listening")] == ["waiting", "woke", "listening"]
        ws.send_bytes(b"\x00" * 640)
        ws.send_json({"type": "stop"})
        until(ws, "done")
    run = ha.runs[0]
    assert run["start_stage"] == "wake_word" and run["input"]["timeout"] == voice.WAKE_SECONDS
    assert run["timeout"] > voice.WAKE_SECONDS


def test_replies_on_the_speaker_or_not_at_all(client, ha):
    client.patch("/api/settings", json={"pin": PIN, "voice": {"replies": "speaker"}})
    with client.websocket_connect("/api/voice/ws?layout=compact") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "mode": "text", "text": "lights on"})
        got = until(ws, "done")
    assert {"type": "spoken", "entity": KITCHEN} in got and not any(m["type"] == "audio" for m in got)
    client.patch("/api/settings", json={"pin": PIN, "voice": {"replies": "none"}})
    with client.websocket_connect("/api/voice/ws?layout=compact") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "mode": "text", "text": "lights on"})
        got = until(ws, "done")
    assert ha.runs[-1]["end_stage"] == "intent" and not any(m["type"] in ("audio", "spoken") for m in got)
    for _ in range(50):
        if ha.calls:
            break
        asyncio.run(asyncio.sleep(0.02))
    assert ha.calls and ha.calls[0]["entity_id"] == KITCHEN and ha.calls[0]["announce"] is True
    assert ha.calls[0]["media_content_id"].startswith("media-source://tts/")


def test_a_new_start_drops_the_old_run_and_errors_reach_the_screen(client, ha):
    client.patch("/api/settings", json={"pin": PIN, "voice": {"pipeline": "missing"}})
    with client.websocket_connect("/api/voice/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "mode": "text", "text": "hi"})
        got = until(ws, "done")
        assert got[0]["type"] == "error" and got[0]["code"] == "pipeline-not-found"
        ws.send_json({"type": "start", "mode": "text", "text": "   "})
        got = until(ws, "done")
        assert got[0]["code"] == "bad-request"
    client.patch("/api/settings", json={"pin": PIN, "voice": {"pipeline": ""}})
    with client.websocket_connect("/api/voice/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "mode": "listen"})
        assert ws.receive_json() == {"type": "listening"}
        ws.send_json({"type": "start", "mode": "text", "text": "never mind"})
        got = until(ws, "done")
    assert any(m["type"] == "unsubscribe_events" and m["subscription"] == ha.runs[0]["id"] for m in ha.sent)
    assert next(m for m in got if m["type"] == "reply")["text"] == "You said never mind"


def test_translate_ignores_what_screens_dont_need():
    assert voice.translate({"type": "intent-progress", "data": {}}) is None
    assert voice.translate({"type": "error", "data": {"code": "stt-no-text-recognized", "message": "No text"}}) == {
        "type": "error", "code": "stt-no-text-recognized", "message": "No text"}
