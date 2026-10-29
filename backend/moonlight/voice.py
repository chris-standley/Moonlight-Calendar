"""Talking to Home Assistant's Assist from a screen.

A screen opens /api/voice/ws and Moonlight relays it to one of Home Assistant's Assist pipelines over HA's WebSocket
(`assist_pipeline/run`), so a screen never needs a Home Assistant login of its own. The screen sends raw 16 kHz,
16-bit mono PCM from its microphone as binary messages; Home Assistant does the rest (wake word, speech-to-text, the
conversation agent, text-to-speech), and the screen is told what happened in plain terms:

    screen -> {"type": "start", "mode": "listen" | "wake" | "text", "text"?, "conversation_id"?}
              then binary audio (listen, wake), {"type": "stop"} when the person stops talking (optional: Home
              Assistant hears the silence itself), {"type": "cancel"} to drop the run.
    screen <- {"type": "ready"} once Home Assistant answers, then per run:
              waiting (listening for the wake word) · woke {phrase} · listening · heard {text} · thinking ·
              reply {text, kind, continue, conversation_id} · audio {url} (spoken reply to play here) ·
              spoken {entity} (played on a speaker instead) · error {code, message} · done

Spoken replies play on the screen itself, on the screen's speaker (its Music speaker, as an announcement), or not at
all (Settings `voice.replies`). The audio comes through Moonlight (/api/voice/audio/<key>) since a screen can't
always reach Home Assistant, and only for replies this relay has seen.

Wake word: with `voice.wake` on for a style of screen, the screen streams its microphone all the time and Home
Assistant listens for the wake word (openWakeWord, or whatever the pipeline is set to), so nothing extra runs on the
screen. A run that hears nothing ends after an hour and the screen starts another.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
from collections import OrderedDict
from typing import Any, AsyncIterator

import httpx

from . import db
from .media import AuthFailed, MediaError, MediaService, _describe

log = logging.getLogger("moonlight.voice")

KEY = "voice"
SAMPLE_RATE = 16000
REPLIES = ("screen", "speaker", "none")
DEFAULT = {"pipeline": "", "wake": {"large": False, "compact": False, "phone": False}, "replies": "screen"}
WAKE_SECONDS = 3600  # one wake word run; the screen starts another when it ends
RUN_SECONDS = 300  # a run once it's awake (HA's own default)
AUDIO_KEEP = 32  # spoken replies whose audio can still be fetched
AUDIO_MAX_BYTES = 16 * 1024 * 1024


class VoiceError(Exception):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- settings

def saved(c) -> dict:
    val = db.get_setting(c, KEY, {}) or {}
    out = {**DEFAULT, "wake": dict(DEFAULT["wake"])}
    if isinstance(val.get("pipeline"), str):
        out["pipeline"] = val["pipeline"]
    if isinstance(val.get("wake"), dict):
        out["wake"].update({k: v for k, v in val["wake"].items() if k in out["wake"] and isinstance(v, bool)})
    if val.get("replies") in REPLIES:
        out["replies"] = val["replies"]
    return out


def apply_settings(c, body: dict) -> bool:
    """PATCH /api/settings `voice`: {pipeline?: id or "" for HA's preferred one, wake?: {layout: bool},
    replies?: screen | speaker | none}. Returns True if it was present."""
    if KEY not in body:
        return False
    from .common import bad  # local import: keep this module importable on its own

    val = body[KEY]
    if not isinstance(val, dict):
        raise bad("voice must be an object like {\"replies\": \"screen\"}")
    out = saved(c)
    for k, v in val.items():
        if k == "pipeline":
            if not isinstance(v, str) or len(v) > 100:
                raise bad("voice.pipeline must be an Assist pipeline id, or \"\" for Home Assistant's preferred one")
            out["pipeline"] = v.strip()
        elif k == "wake":
            if not isinstance(v, dict) or any(x not in DEFAULT["wake"] or not isinstance(y, bool) for x, y in v.items()):
                raise bad("voice.wake must map large/compact/phone to true or false")
            out["wake"].update(v)
        elif k == "replies":
            if v not in REPLIES:
                raise bad("voice.replies must be one of " + ", ".join(REPLIES))
            out["replies"] = v
        else:
            raise bad(f"Unknown voice field {k}")
    db.set_setting(c, KEY, out)
    return True


# ---------------------------------------------------------------- pipelines

def pipeline_out(p: dict) -> dict:
    return {"id": p.get("id"), "name": p.get("name") or "Assist", "language": p.get("language") or "",
            "stt": bool(p.get("stt_engine")), "tts": bool(p.get("tts_engine")),
            "wake_word": p.get("wake_word_id") or "", "agent": p.get("conversation_engine") or ""}


async def pipelines(svc: MediaService) -> dict:
    """Home Assistant's Assist pipelines: {pipelines: [...], preferred: id}. Raises VoiceError when HA can't say."""
    errors: list[str] = []
    try:
        listed, = await svc._ws_commands({"type": "assist_pipeline/pipeline/list"}, errors=errors)
    except AuthFailed as e:
        raise VoiceError(f"Home Assistant refused Moonlight's token: {e}")
    except (MediaError, OSError, asyncio.TimeoutError) as e:
        raise VoiceError(f"Couldn't reach Home Assistant: {_describe(e)}")
    if listed is None:
        raise VoiceError("Home Assistant has no Assist (" + (errors[0] if errors else "no answer") + ")")
    return {"pipelines": [pipeline_out(p) for p in listed.get("pipelines") or []],
            "preferred": listed.get("preferred_pipeline") or "", "wake_engine": await _has_wake_engine(svc)}


async def _has_wake_engine(svc: MediaService) -> bool:
    """A wake word needs a wake word engine (openWakeWord, say) somewhere in Home Assistant."""
    try:
        async with httpx.AsyncClient(timeout=10, transport=svc.transport) as client:
            r = await client.post(svc.base_url + "/template", headers={"Authorization": f"Bearer {svc.token}"},
                                  json={"template": "{{ states.wake_word | count }}"})
        return r.status_code == 200 and r.text.strip() not in ("", "0")
    except httpx.HTTPError:
        return False


# ---------------------------------------------------------------- spoken replies

_audio: OrderedDict[str, str] = OrderedDict()  # key -> HA path (/api/tts_proxy/...)


def remember_audio(path: str) -> str:
    key = secrets.token_urlsafe(12)
    _audio[key] = path
    while len(_audio) > AUDIO_KEEP:
        _audio.popitem(last=False)
    return key


def audio_path(key: str) -> str | None:
    return _audio.get(key)


@contextlib.asynccontextmanager
async def fetch_audio(svc: MediaService, key: str) -> AsyncIterator[tuple[int, str, AsyncIterator[bytes]]]:
    """(status, content type, body chunks) of a spoken reply, streamed from Home Assistant as it speaks."""
    path = audio_path(key)
    if path is None:
        raise VoiceError("That reply has gone", 404)
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=60), transport=svc.transport) as client:
        async with client.stream("GET", svc.origin + path, headers={"Authorization": f"Bearer {svc.token}"}) as r:
            ctype = r.headers.get("content-type", "audio/mpeg").split(";")[0].strip()

            async def body() -> AsyncIterator[bytes]:
                sent = 0
                async for chunk in r.aiter_bytes():
                    sent += len(chunk)
                    if sent > AUDIO_MAX_BYTES:
                        return
                    yield chunk

            yield r.status_code, ctype, body()


# ---------------------------------------------------------------- the relay

def run_message(msg_id: int, cmd: dict, pipeline: str, speak: bool) -> dict:
    """The `assist_pipeline/run` for a screen's `start`."""
    mode = cmd.get("mode")
    end = "tts" if speak else "intent"
    out: dict[str, Any] = {"id": msg_id, "type": "assist_pipeline/run", "end_stage": end}
    if mode == "text":
        text = cmd.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Say or type something first")
        out.update(start_stage="intent", input={"text": text.strip()[:1000]})
    elif mode == "wake":
        out.update(start_stage="wake_word", input={"sample_rate": SAMPLE_RATE, "timeout": WAKE_SECONDS},
                   timeout=WAKE_SECONDS + RUN_SECONDS)
    elif mode == "listen":
        out.update(start_stage="stt", input={"sample_rate": SAMPLE_RATE})
    else:
        raise ValueError("mode must be listen, wake or text")
    if pipeline:
        out["pipeline"] = pipeline
    conv = cmd.get("conversation_id")
    if isinstance(conv, str) and conv:
        out["conversation_id"] = conv
    return out


def speech_of(intent_output: dict) -> str:
    speech = ((intent_output or {}).get("response") or {}).get("speech") or {}
    return str((speech.get("plain") or {}).get("speech") or (speech.get("ssml") or {}).get("speech") or "")


def translate(ev: dict) -> dict | None:
    """One of Home Assistant's pipeline events as the screen sees it (None for the ones it doesn't need).
    tts-end is handled by the relay (where the reply is spoken)."""
    kind, data = ev.get("type"), ev.get("data") or {}
    if kind == "wake_word-start":
        return {"type": "waiting"}
    if kind == "wake_word-end":
        out = data.get("wake_word_output") or {}
        return {"type": "woke", "phrase": out.get("wake_word_phrase") or out.get("wake_word_id") or ""}
    if kind == "stt-start":
        return {"type": "listening"}
    if kind == "stt-vad-end":
        return {"type": "speech_end"}
    if kind == "stt-end":
        return {"type": "heard", "text": str(((data.get("stt_output") or {}).get("text")) or "").strip()}
    if kind == "intent-start":
        return {"type": "thinking"}
    if kind == "intent-end":
        out = data.get("intent_output") or {}
        resp = out.get("response") or {}
        return {"type": "reply", "text": speech_of(out), "kind": resp.get("response_type") or "action_done",
                "continue": bool(out.get("continue_conversation")), "conversation_id": out.get("conversation_id")}
    if kind == "error":
        return {"type": "error", "code": data.get("code") or "error", "message": data.get("message") or ""}
    if kind == "run-end":
        return {"type": "done"}
    return None


async def relay(client, svc: MediaService, *, pipeline: str, replies: str, speaker: str) -> None:
    """Relay one screen's voice socket (a Starlette WebSocket, already accepted) to Home Assistant until either
    side goes away. One pipeline run at a time; a new `start` replaces the one going."""
    try:
        ha_cm = svc.ws_connect(svc.ws_url)
        ha = await ha_cm.__aenter__()
    except Exception as e:
        await client.send_json({"type": "error", "code": "unreachable", "message": f"Couldn't reach Home Assistant: {_describe(e)}"})
        return
    try:
        msg = json.loads(await ha.recv())
        if msg.get("type") != "auth_required":
            raise VoiceError(f"unexpected greeting {msg.get('type')!r}")
        await ha.send(json.dumps({"type": "auth", "access_token": svc.token}))
        msg = json.loads(await ha.recv())
        if msg.get("type") != "auth_ok":
            raise VoiceError("Home Assistant refused Moonlight's token")
        await client.send_json({"type": "ready"})
        await _relay(client, ha, svc, pipeline=pipeline, replies=replies, speaker=speaker)
    except VoiceError as e:
        with contextlib.suppress(Exception):
            await client.send_json({"type": "error", "code": "unreachable", "message": str(e)})
    except Exception as e:  # HA went away mid-run, or the screen did
        log.info("Voice relay ended: %s", _describe(e))
        with contextlib.suppress(Exception):
            await client.send_json({"type": "error", "code": "unreachable", "message": "Lost Home Assistant"})
    finally:
        with contextlib.suppress(Exception):
            await ha_cm.__aexit__(None, None, None)


async def _relay(client, ha, svc: MediaService, *, pipeline: str, replies: str, speaker: str) -> None:
    run = {"id": 0, "handler": None}  # the run going: its message id, and HA's handler for its audio
    next_id = 0
    speak_on = speaker if replies == "speaker" else ""

    async def from_ha() -> None:
        async for raw in ha:
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            if msg.get("id") != run["id"] or not run["id"]:
                continue  # an old run's leftovers
            if msg.get("type") == "result":
                if not msg.get("success"):
                    err = msg.get("error") or {}
                    run["handler"] = None
                    await client.send_json({"type": "error", "code": err.get("code") or "error",
                                            "message": err.get("message") or "Home Assistant said no"})
                    await client.send_json({"type": "done"})
                    run["id"] = 0
                continue
            if msg.get("type") != "event":
                continue
            ev = msg.get("event") or {}
            if ev.get("type") == "run-start":
                run["handler"] = ((ev.get("data") or {}).get("runner_data") or {}).get("stt_binary_handler_id")
                continue
            if ev.get("type") in ("stt-end", "error", "run-end"):
                run["handler"] = None  # no more audio wanted
            if ev.get("type") == "tts-end":
                out = (ev.get("data") or {}).get("tts_output") or {}
                if speak_on and out.get("media_id"):
                    asyncio.create_task(_announce(svc, speak_on, out["media_id"]))
                    await client.send_json({"type": "spoken", "entity": speak_on})
                elif replies == "screen" and str(out.get("url") or "").startswith("/api/"):
                    await client.send_json({"type": "audio", "url": f"/api/voice/audio/{remember_audio(out['url'])}"})
                continue
            out = translate(ev)
            if out is not None:
                await client.send_json(out)
            if ev.get("type") == "run-end":
                run["id"] = 0  # finished: nothing to cancel

    async def from_screen() -> None:
        nonlocal next_id
        while True:
            m = await client.receive()
            if m.get("type") == "websocket.disconnect":
                return
            if m.get("bytes") is not None:
                if run["handler"] is not None and m["bytes"]:
                    await ha.send(bytes([run["handler"]]) + m["bytes"])
                continue
            try:
                cmd = json.loads(m.get("text") or "")
            except ValueError:
                continue
            if not isinstance(cmd, dict):
                continue
            kind = cmd.get("type")
            if kind in ("start", "cancel") and run["id"]:
                old = run["id"]
                run.update(id=0, handler=None)
                await ha.send(json.dumps({"id": (next_id := next_id + 1), "type": "unsubscribe_events",
                                          "subscription": old}))
            if kind == "start":
                next_id += 1
                try:
                    out = run_message(next_id, cmd, pipeline, replies != "none")
                except ValueError as e:
                    await client.send_json({"type": "error", "code": "bad-request", "message": str(e)})
                    await client.send_json({"type": "done"})
                    continue
                run.update(id=next_id, handler=None)
                await ha.send(json.dumps(out))
            elif kind == "stop" and run["handler"] is not None:
                handler, run["handler"] = run["handler"], None
                await ha.send(bytes([handler]))  # end of audio

    tasks = [asyncio.create_task(from_ha()), asyncio.create_task(from_screen())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if tasks[0] in done:
            raise VoiceError("Lost Home Assistant")  # it went away (restarting, say): tell the screen
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(BaseException):
                await t


async def _announce(svc: MediaService, entity: str, media_id: str) -> None:
    try:
        await svc.call_service("media_player", "play_media", {
            "entity_id": entity, "media_content_id": media_id, "media_content_type": "music", "announce": True})
    except Exception as e:
        log.info("Couldn't speak the reply on %s: %s", entity, _describe(e))
