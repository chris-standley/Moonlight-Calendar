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

from moonlight import alerts, media, voice, voice_commands  # noqa: E402
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
        self.heard: str | None = None  # what speech-to-text "hears" (default: how many bytes came)
        self.streaming = False  # name the spoken reply's stream in run-start, as HA does for streaming TTS
        self.fail_intent = False  # the agent fails, so nothing is said

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
                self.finish(mid, self.ha.heard or f"heard {self.audio.get(mid, 0)} bytes")
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
            start = {"pipeline": "p2", "runner_data": {"stt_binary_handler_id": handler}}
            if self.ha.streaming and msg["end_stage"] == "tts":
                start["tts_output"] = {"token": "early.mp3", "url": "/api/tts_proxy/early.mp3",
                                       "mime_type": "audio/mpeg", "stream_response": True}
            self.event(mid, "run-start", start)
            if msg["start_stage"] == "wake_word":
                self.event(mid, "wake_word-start")
                self.event(mid, "wake_word-end", {"wake_word_output": {"wake_word_id": "ok_nabu",
                                                                       "wake_word_phrase": "Okay Nabu"}})
            if handler:
                self.event(mid, "stt-start")
            elif msg["start_stage"] == "tts":
                self.event(mid, "tts-start")
                self.event(mid, "tts-end", {"tts_output": {"media_id": "media-source://tts/said",
                                                           "url": "/api/tts_proxy/said.mp3", "mime_type": "audio/mpeg"}})
                self.event(mid, "run-end")
            else:
                self.finish(mid, None, msg["input"]["text"])
        elif msg["type"] == "unsubscribe_events":
            self.handlers = {h: m for h, m in self.handlers.items() if m != msg["subscription"]}
            self.out.put_nowait(json.dumps({"id": mid, "type": "result", "success": True, "result": None}))

    def finish(self, mid, heard, text=None):
        run = next(r for r in self.ha.runs if r["id"] == mid)
        if heard is not None:
            self.event(mid, "stt-vad-end")
            self.event(mid, "stt-end", {"stt_output": {"text": heard}})
            if run["end_stage"] == "stt":
                self.event(mid, "run-end")
                return
        self.event(mid, "intent-start")
        if self.ha.fail_intent:
            self.event(mid, "error", {"code": "intent-failed", "message": "The agent went away"})
            self.event(mid, "run-end")
            return
        said = heard or text
        self.event(mid, "intent-end", {"intent_output": {
            "response": {"speech": {"plain": {"speech": f"You said {said}"}}, "response_type": "action_done"},
            "conversation_id": "conv-1", "continue_conversation": said.endswith("?")}})
        if run["end_stage"] == "tts":
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
    run, then = ha.runs
    assert run["start_stage"] == "stt" and run["end_stage"] == "stt" and run["pipeline"] == "p2"
    assert run["input"] == {"sample_rate": 16000}
    # What was heard goes on to the agent in a second run, in the same conversation.
    assert then["start_stage"] == "intent" and then["end_stage"] == "tts" and then["input"] == {"text": "heard 3200 bytes"}
    # The reply's audio comes through Moonlight; made-up keys don't.
    r = client.get(got[4]["url"])
    assert r.status_code == 200 and r.content == MP3 and r.headers["content-type"] == "audio/mpeg"
    assert client.get("/api/voice/audio/nope").status_code == 404


def test_streamed_reply_reaches_the_screen_before_the_answer_is_written(client, ha):
    ha.streaming = True
    with client.websocket_connect("/api/voice/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "mode": "text", "text": "tell me a story"})
        got = until(ws, "done")
    # The audio comes at run-start, so it can play while the agent is still writing; not again at tts-end.
    assert [m["type"] for m in got] == ["audio", "thinking", "reply", "done"]
    assert client.get(got[0]["url"]).content == MP3


def test_streamed_reply_that_never_comes_is_dropped(client, ha):
    ha.streaming, ha.fail_intent = True, True
    with client.websocket_connect("/api/voice/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "mode": "text", "text": "tell me a story"})
        got = until(ws, "done")
    assert [m["type"] for m in got] == ["audio", "thinking", "error", "silent", "done"]


def test_text_follow_up_keeps_the_conversation(client, ha):
    with client.websocket_connect("/api/voice/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "mode": "text", "text": "should I take a coat?", "conversation_id": "conv-1"})
        got = until(ws, "done")
    reply = next(m for m in got if m["type"] == "reply")
    assert reply["continue"] is True  # a question back: the screen listens again
    run = ha.runs[0]
    assert run["start_stage"] == "intent" and run["input"] == {"text": "should I take a coat?"}
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


def test_markdown_from_llm_agents_is_dropped():
    out = {"response": {"speech": {"plain": {"speech": "It's **9:48 PM**.\n- Bins: `recycling`\n## Done"}}}}
    assert voice.speech_of(out) == "It's 9:48 PM.\nBins: recycling\nDone"


@pytest.mark.parametrize("said, seconds, label, full", [
    ("Set a 30 minute timer.", 1800, "", False),
    ("Set a 30 minute full screen timer", 1800, "", True),
    ("Pasta timer for 1 hour and 15 minutes", 4500, "Pasta", False),
    ("Set a timer for an hour and a half for the cake", 5400, "Cake", False),
    ("Timer for half an hour", 1800, "", False),
    ("Set a timer for twenty-five minutes", 1500, "", False),
    ("Start a 2 minute big timer for tea", 120, "Tea", True),
    ("set a timer for 90 seconds", 90, "", False),
])
def test_timer_requests_are_understood(said, seconds, label, full):
    assert voice_commands.parse(said) == {"do": "start", "seconds": seconds, "label": label, "full": full}


def test_other_requests_go_to_home_assistant():
    assert voice_commands.parse("Turn on the kitchen lights") is None
    assert voice_commands.parse("What's the timer app called") is None
    assert voice_commands.parse("Cancel the timer") == {"do": "cancel"}
    assert voice_commands.parse("How long is left on the timer?") == {"do": "left"}
    assert voice_commands.spoken_duration(4500) == "1 hour and 15 minutes"


def test_spoken_timer_goes_on_this_screen_full_screen(client, ha):
    ha.heard = "Set a 30 minute full screen timer"
    with client.websocket_connect("/api/voice/ws?layout=compact") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "mode": "listen"})
        ws.receive_json()
        ws.send_bytes(b"\x00" * 640)
        ws.send_json({"type": "stop"})
        got = until(ws, "done")
    assert [m["type"] for m in got] == ["speech_end", "heard", "thinking", "reply", "audio", "done"]
    assert got[3]["text"] == "Timer set for 30 minutes."
    # Never reached the conversation agent; the answer is spoken in the assistant's voice.
    assert [r["start_stage"] for r in ha.runs] == ["stt", "tts"]
    assert ha.runs[1]["input"] == {"text": "Timer set for 30 minutes."}
    timers = client.get("/api/alerts").json()["alerts"]
    assert len(timers) == 1 and timers[0]["kind"] == "timer" and timers[0]["style"] == "fullscreen"
    assert timers[0]["ends_at"] - timers[0]["started_at"] == 1800 * 1000 and timers[0]["label"] == "Timer"


def test_typed_timer_cancel_and_time_left(client, ha):
    with client.websocket_connect("/api/voice/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "start", "mode": "text", "text": "pasta timer for 10 minutes"})
        assert next(m for m in until(ws, "done") if m["type"] == "reply")["text"] == "Pasta timer set for 10 minutes."
        ws.send_json({"type": "start", "mode": "text", "text": "how long is left on the timer"})
        left = next(m for m in until(ws, "done") if m["type"] == "reply")["text"]
        assert left.startswith("Pasta has 10 minutes left") or left.startswith("Pasta has 9 minutes")
        ws.send_json({"type": "start", "mode": "text", "text": "cancel the timer"})
        assert next(m for m in until(ws, "done") if m["type"] == "reply")["text"] == "Timer cancelled."
    assert client.get("/api/alerts").json()["alerts"] == []
    assert all(r["start_stage"] == "tts" for r in ha.runs)  # Home Assistant only lent its voice


def test_timer_targets_the_asking_screen(client):
    import asyncio as aio
    screen = {"id": "d1", "name": "Kitchen", "layout": "compact"}
    with mock_screen(screen):
        done = aio.run(voice_commands.run({"do": "start", "seconds": 60, "label": "", "full": False},
                                          {"display": screen, "layout": "compact"}))
        assert done == {"say": "Timer set for 1 minute."}
        a = next(iter(alerts._alerts.values()))
        assert a["display_ids"] == ["d1"] and alerts.shown_on(a, screen)
        assert not alerts.shown_on(a, {"id": "d2", "name": "Hall", "layout": "large"})


class mock_screen:
    """Pretend `screen` is paired (alerts check names and ids against the paired screens)."""

    def __init__(self, screen):
        self.screen = screen

    def __enter__(self):
        self.old = alerts._screens
        alerts._screens = lambda c: [self.screen]

    def __exit__(self, *a):
        alerts._screens = self.old
