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
import math
import re
import secrets
import time
from array import array
from collections import OrderedDict
from typing import Any, AsyncIterator

import httpx

from . import db, voice_commands
from .media import AuthFailed, MediaError, MediaService, _describe

log = logging.getLogger("moonlight.voice")

KEY = "voice"
SAMPLE_RATE = 16000
REPLIES = ("screen", "speaker", "none")
DEFAULT = {"pipeline": "", "wake": {"large": False, "compact": False, "phone": False}, "replies": "screen",
           "mic": {"echo": True, "noise": False, "auto_gain": True, "target_db": -22, "gain_max_db": 18}}
# How screens capture their microphone (the browser's processing, and the screen's own gain towards target_db):
# tablets' microphones differ, and this is what to change when a wake word won't wake.
MIC_RANGES = {"target_db": (-40, -6), "gain_max_db": (0, 40)}
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
    out = {**DEFAULT, "wake": dict(DEFAULT["wake"]), "mic": dict(DEFAULT["mic"])}
    if isinstance(val.get("pipeline"), str):
        out["pipeline"] = val["pipeline"]
    if isinstance(val.get("wake"), dict):
        out["wake"].update({k: v for k, v in val["wake"].items() if k in out["wake"] and isinstance(v, bool)})
    if val.get("replies") in REPLIES:
        out["replies"] = val["replies"]
    if isinstance(val.get("mic"), dict):
        out["mic"].update({k: v for k, v in val["mic"].items() if _mic_ok(k, v)})
    return out


def _mic_ok(k: str, v: Any) -> bool:
    if k in MIC_RANGES:
        lo, hi = MIC_RANGES[k]
        return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi
    return k in DEFAULT["mic"] and isinstance(v, bool)


def apply_settings(c, body: dict) -> bool:
    """PATCH /api/settings `voice`: {pipeline?: id or "" for HA's preferred one, wake?: {layout: bool},
    replies?: screen | speaker | none, mic?: {echo?, noise?, auto_gain?, target_db?, gain_max_db?}}. Returns True if it was present."""
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
        elif k == "mic":
            if not isinstance(v, dict) or not all(_mic_ok(x, y) for x, y in v.items()):
                raise bad("voice.mic takes echo/noise/auto_gain (true or false), target_db (-40 to -6) and "
                          "gain_max_db (0 to 40)")
            out["mic"].update(v)
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
        asked = time.monotonic()
        async with client.stream("GET", svc.origin + path, headers={"Authorization": f"Bearer {svc.token}"}) as r:
            ctype = r.headers.get("content-type", "audio/mpeg").split(";")[0].strip()

            async def body() -> AsyncIterator[bytes]:
                sent, first = 0, None
                async for chunk in r.aiter_bytes():
                    if first is None:
                        first = time.monotonic() - asked
                    sent += len(chunk)
                    if sent > AUDIO_MAX_BYTES:
                        return
                    yield chunk
                # How long the voice takes to start talking, for comparing voices and engines.
                log.info("Spoken reply: first sound after %.2f s, all %d bytes after %.2f s",
                         first or 0, sent, time.monotonic() - asked)

            yield r.status_code, ctype, body()


# ---------------------------------------------------------------- the relay

def run_message(msg_id: int, cmd: dict, pipeline: str, speak: bool) -> dict:
    """The `assist_pipeline/run` for a screen's `start`. Speech runs stop once it's written down: the relay then
    answers it itself (voice_commands.py) or sends the words on to the conversation agent in a second run."""
    mode = cmd.get("mode")
    end = "stt" if mode in ("listen", "wake") else "tts" if speak else "intent"
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


MARKDOWN = re.compile(r"\*\*|__|`|^#+\s*|^\s*[-*]\s+(?=\S)", re.MULTILINE)


def say_message(msg_id: int, text: str, pipeline: str) -> dict:
    """A text-to-speech run: Moonlight's own answer, in the assistant's voice."""
    out: dict[str, Any] = {"id": msg_id, "type": "assist_pipeline/run", "start_stage": "tts", "end_stage": "tts",
                           "input": {"text": text}}
    if pipeline:
        out["pipeline"] = pipeline
    return out


def speech_of(intent_output: dict) -> str:
    """The answer to show. LLM agents often answer in Markdown (**9:48 PM**), which a screen would show as is."""
    speech = ((intent_output or {}).get("response") or {}).get("speech") or {}
    text = str((speech.get("plain") or {}).get("speech") or (speech.get("ssml") or {}).get("speech") or "")
    return MARKDOWN.sub("", text).strip()


def translate(ev: dict) -> dict | None:
    """One of Home Assistant's pipeline events as the screen sees it (None for the ones it doesn't need).
    tts-end is handled by the relay (where the reply is spoken)."""
    kind, data = ev.get("type"), ev.get("data") or {}
    if kind == "wake_word-start":
        return {"type": "waiting"}
    if kind == "wake_word-end":
        out = data.get("wake_word_output") or {}
        if not out.get("wake_word_id"):
            # It ended without hearing the word: the wake word engine went away (restarting, say).
            return {"type": "error", "code": "wake-word-lost", "message": "The wake word engine stopped listening"}
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


async def relay(client, svc: MediaService, *, pipeline: str, replies: str, speaker: str,
                display: dict | None = None, layout: str = "compact") -> None:
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
        await _relay(client, ha, svc, pipeline=pipeline, replies=replies, speaker=speaker, display=display,
                     layout=layout)
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


# A short recording of what a wake word run hears, made only when asked for (POST /api/voice/sample), to check a
# screen's microphone by ear or against the wake word engine. Kept in memory until the next one.
SAMPLE_MAX_SECONDS = 60
_sample: dict[str, Any] = {"until": 0.0, "pcm": bytearray()}


def record_sample(seconds: float) -> None:
    _sample.update(until=time.monotonic() + max(1.0, min(float(seconds), SAMPLE_MAX_SECONDS)), pcm=bytearray())


def _keep_sample(pcm: bytes) -> None:
    if time.monotonic() < _sample["until"]:
        _sample["pcm"] += pcm


def sample_wav() -> bytes:
    """The last recording as a 16 kHz mono WAV."""
    import io
    import wave
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(_sample["pcm"]))
    return out.getvalue()


def sample_part(start: float, seconds: float) -> dict:
    """Part of the last recording as base64 PCM, plus its loudness every 100 ms, for tools that can't take binary."""
    import base64
    pcm = bytes(_sample["pcm"])
    a, b = int(max(0.0, start) * SAMPLE_RATE) * 2, int(max(0.0, start + min(seconds, 10.0)) * SAMPLE_RATE) * 2
    loud = []
    for i in range(0, len(pcm) - 3199, 3200):
        x = array("h")
        x.frombytes(pcm[i:i + 3200])
        loud.append(round(20 * math.log10(max(abs(v) for v in x) / 32768 + 1e-6)))
    return {"rate": SAMPLE_RATE, "seconds": len(pcm) / 2 / SAMPLE_RATE, "peak_dbfs_per_100ms": loud,
            "speech_spectrum_db": _spectrum(pcm), "start": a / 2 / SAMPLE_RATE,
            "pcm16_b64": base64.b64encode(pcm[a:b]).decode()}


REPLAY_SPEEDS = (1.0, 48000 / 44100, 44100 / 48000)


def stretch(pcm: bytes, speed: float) -> bytes:
    """`pcm` played `speed` times slower (longer and lower for speed > 1), by linear interpolation: what a screen
    would have sent had it got its microphone's sample rate wrong."""
    x = array("h")
    x.frombytes(pcm[: len(pcm) // 2 * 2])
    if speed == 1.0 or len(x) < 2:
        return x.tobytes()
    out = array("h", bytes(2 * (1 + int((len(x) - 1) * speed))))
    for i in range(len(out)):
        p = i / speed
        j = int(p)
        f = p - j
        out[i] = int(x[j] + (x[min(j + 1, len(x) - 1)] - x[j]) * f)
    return out.tobytes()


async def replay_sample(svc: MediaService, pipeline: str, speeds: tuple[float, ...] = REPLAY_SPEEDS) -> dict:
    """Play the last recording to Home Assistant's wake word engine, as it was and as if the screen had got its
    sample rate wrong (44.1 kHz taken for 48 kHz and the other way round): which of them wakes it tells a
    microphone that can't be made out from audio that is being garbled on the way."""
    pcm = bytes(_sample["pcm"])
    if not pcm:
        raise VoiceError("Nothing recorded yet: POST /api/voice/sample first, then say the wake word", 409)
    tries = []
    async with svc.ws_connect(svc.ws_url) as ha:
        msg = json.loads(await ha.recv())
        if msg.get("type") != "auth_required":
            raise VoiceError(f"unexpected greeting {msg.get('type')!r}")
        await ha.send(json.dumps({"type": "auth", "access_token": svc.token}))
        if json.loads(await ha.recv()).get("type") != "auth_ok":
            raise VoiceError("Home Assistant refused Moonlight's token")
        for n, speed in enumerate(speeds, 1):
            audio = await asyncio.to_thread(stretch, pcm, speed)
            tries.append({"speed": round(speed, 3), **await _replay_one(ha, n, audio, pipeline)})
    return {"seconds": len(pcm) / 2 / SAMPLE_RATE, "tries": tries}


async def _replay_one(ha, msg_id: int, pcm: bytes, pipeline: str) -> dict:
    run: dict[str, Any] = {"id": msg_id, "type": "assist_pipeline/run", "start_stage": "wake_word",
                           "end_stage": "wake_word", "input": {"sample_rate": SAMPLE_RATE, "timeout": 120}}
    if pipeline:
        run["pipeline"] = pipeline
    await ha.send(json.dumps(run))
    pcm += bytes(2 * SAMPLE_RATE * 2)  # two seconds of quiet after the last word
    sent = False

    async def events():
        nonlocal sent
        async for raw in ha:
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            if msg.get("id") != msg_id:
                continue
            if msg.get("type") == "result" and not msg.get("success"):
                return {"woke": None, "error": (msg.get("error") or {}).get("message") or "refused"}
            ev = msg.get("event") or {}
            kind, data = ev.get("type"), ev.get("data") or {}
            if kind == "run-start" and not sent:
                sent = True
                handler = (data.get("runner_data") or {}).get("stt_binary_handler_id")
                for i in range(0, len(pcm), CHUNK_BYTES):
                    await ha.send(bytes([handler]) + pcm[i:i + CHUNK_BYTES])
                    await asyncio.sleep(0.002)
                await ha.send(bytes([handler]))
            elif kind == "wake_word-end":
                out = data.get("wake_word_output") or {}
                return {"woke": out.get("wake_word_id") or None,
                        "at_s": round((out.get("timestamp") or 0) / 1000, 1) if out.get("timestamp") else None}
            elif kind == "error":
                return {"woke": None, "error": data.get("code") or data.get("message") or "error"}
            elif kind == "run-end":
                return {"woke": None}
        return {"woke": None, "error": "Home Assistant went away"}
    try:
        return await asyncio.wait_for(events(), 120)
    except asyncio.TimeoutError:
        return {"woke": None, "error": "no answer in 2 minutes"}


CHUNK_BYTES = 2560  # 80 ms


def _spectrum(pcm: bytes) -> list[list[float]]:
    """[hz, dB relative to the strongest] every 250 Hz, averaged over the recording's loud 32 ms windows (speech):
    a microphone that loses the high frequencies, or a screen that resamples badly, shows here."""
    x = array("h")
    x.frombytes(pcm[: len(pcm) // 2 * 2])
    n, hzs = 512, range(125, 8000, 250)
    win = [0.5 - 0.5 * math.cos(2 * math.pi * i / n) for i in range(n)]
    tw = {hz: [(math.cos(2 * math.pi * hz * i / SAMPLE_RATE), math.sin(2 * math.pi * hz * i / SAMPLE_RATE))
               for i in range(n)] for hz in hzs}
    power = {hz: 0.0 for hz in hzs}
    used = 0
    for start in range(0, len(x) - n, n):
        frame = x[start:start + n]
        if max(abs(v) for v in frame) < 32768 * 10 ** (-30 / 20) or used >= 40:
            continue
        used += 1
        f = [frame[i] * win[i] for i in range(n)]
        for hz in hzs:
            re_ = sum(f[i] * tw[hz][i][0] for i in range(n))
            im = sum(f[i] * tw[hz][i][1] for i in range(n))
            power[hz] += re_ * re_ + im * im
    if not used:
        return []
    top = max(power.values()) or 1.0
    return [[hz, round(10 * math.log10(power[hz] / top + 1e-12), 1)] for hz in hzs]


class SoundMeter:
    """How much sound a wake word run is getting, for the log: a screen whose microphone sends silence (or barely a
    whisper) never wakes, and nothing else says so."""
    EVERY = 60.0  # seconds of audio between log lines

    def __init__(self, layout: str):
        self.layout = layout
        self.reset()

    def reset(self) -> None:
        self.samples = 0
        self.loud = 0.0  # the loudest 80 ms, as RMS 0..1
        self.sum = 0.0  # of each chunk's RMS, for the typical level

    def add(self, pcm: bytes) -> None:
        a = array("h")
        a.frombytes(pcm[: len(pcm) // 2 * 2])
        if not a:
            return
        rms = math.sqrt(sum(x * x for x in a) / len(a)) / 32768
        self.samples += len(a)
        self.sum += rms * len(a)
        self.loud = max(self.loud, rms)
        if self.samples >= self.EVERY * SAMPLE_RATE:
            self.report()

    def report(self, woke: str = "") -> None:
        if not self.samples:
            return
        def db_(v: float) -> str:
            return "silence" if v <= 1e-5 else f"{20 * math.log10(v):.0f} dBFS"
        secs = self.samples / SAMPLE_RATE
        log.info("Wake word on a %s screen: %.0f s of sound, typically %s, loudest %s%s", self.layout, secs,
                 db_(self.sum / self.samples), db_(self.loud), f" (woke: {woke})" if woke else "")
        self.reset()


async def _relay(client, ha, svc: MediaService, *, pipeline: str, replies: str, speaker: str,
                 display: dict | None = None, layout: str = "compact") -> None:
    # The run going: its message id, HA's handler for its audio, and for a speech run (which stops at
    # speech-to-text) what was heard, so the run after it can answer.
    # A run that answers out loud on the screen hands the screen its audio as soon as Home Assistant names it
    # (`early`), so speech can start while a streaming agent is still writing a long answer.
    run: dict[str, Any] = {"id": 0, "handler": None, "speech": False, "heard": "", "conv": None,
                           "early": False, "tts": False}
    next_id = 0
    speak = replies != "none"
    speak_on = speaker if replies == "speaker" else ""
    meter = SoundMeter(layout)

    async def send_run(msg: dict) -> None:
        run.update(id=msg["id"], handler=None, speech=msg["end_stage"] == "stt", heard="", early=False, tts=False,
                   wake=msg.get("start_stage") == "wake_word")
        await ha.send(json.dumps(msg))

    def new_id() -> int:
        nonlocal next_id
        next_id += 1
        return next_id

    async def answer(text: str) -> bool:
        """Moonlight's own answer to `text` (a timer, the music, a list); False when it's one for Home Assistant."""
        cmd = voice_commands.parse(text)
        if cmd is None:
            return False
        await client.send_json({"type": "thinking"})
        try:
            done = await voice_commands.run(cmd, {"display": display, "layout": layout})
        except Exception as e:  # e.g. too many timers already
            log.info("Voice command %s failed: %s", cmd.get("do"), _describe(e))
            done = {"say": getattr(e, "detail", None) or "Sorry, I couldn't do that."}
        if done is None:
            return False  # not Moonlight's after all (no list by that name, say)
        if done.get("go"):
            await client.send_json({"type": "go", "tab": done["go"]})
        said = str(done["say"])
        await client.send_json({"type": "reply", "text": said, "kind": "action_done", "continue": False,
                                "conversation_id": run["conv"]})
        if speak:
            await send_run(say_message(new_id(), said, pipeline))
        else:
            run["id"] = 0
            await client.send_json({"type": "done"})
        return True

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
            kind = ev.get("type")
            if kind == "run-start":
                data = ev.get("data") or {}
                run["handler"] = (data.get("runner_data") or {}).get("stt_binary_handler_id")
                early = data.get("tts_output") or {}
                if replies == "screen" and early.get("stream_response") and str(early.get("url") or "").startswith("/api/"):
                    run["early"] = True
                    await client.send_json({"type": "audio", "url": f"/api/voice/audio/{remember_audio(early['url'])}"})
                continue
            if kind == "wake_word-end":
                meter.report(woke=((ev.get("data") or {}).get("wake_word_output") or {}).get("wake_word_id") or "?")
                run["wake"] = False
            if kind in ("stt-end", "error", "run-end"):
                run["handler"] = None  # no more audio wanted
            if kind == "tts-start":
                run["tts"] = True
            if kind == "run-end" and run["early"] and not run["tts"]:
                await client.send_json({"type": "silent"})  # it ended (an error, say) without saying anything
            if kind == "tts-end":
                if run["early"]:
                    continue  # the screen has it already
                out = (ev.get("data") or {}).get("tts_output") or {}
                if speak_on and out.get("media_id"):
                    asyncio.create_task(_announce(svc, speak_on, out["media_id"]))
                    await client.send_json({"type": "spoken", "entity": speak_on})
                elif replies == "screen" and str(out.get("url") or "").startswith("/api/"):
                    await client.send_json({"type": "audio", "url": f"/api/voice/audio/{remember_audio(out['url'])}"})
                continue
            if kind == "run-end" and run["speech"]:
                heard = run["heard"]
                run["id"] = 0
                if heard and not await answer(heard):
                    # On to the conversation agent with the words, as one conversation.
                    await send_run(run_message(new_id(), {"mode": "text", "text": heard, "conversation_id": run["conv"]},
                                               pipeline, speak))
                elif not heard:
                    await client.send_json({"type": "done"})
                continue
            out = translate(ev)
            if out is not None:
                if out["type"] == "heard":
                    run["heard"] = out["text"]
                await client.send_json(out)
            if kind == "run-end":
                run["id"] = 0  # finished: nothing to cancel

    async def from_screen() -> None:
        logged_mic = ""
        while True:
            m = await client.receive()
            if m.get("type") == "websocket.disconnect":
                return
            if m.get("bytes") is not None:
                if run["handler"] is not None and m["bytes"]:
                    if run.get("wake"):
                        meter.add(m["bytes"])
                        _keep_sample(m["bytes"])
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
                await ha.send(json.dumps({"id": new_id(), "type": "unsubscribe_events", "subscription": old}))
            if kind == "start":
                info = cmd.get("mic")
                if cmd.get("mode") == "wake" and isinstance(info, str) and info and info != logged_mic:
                    logged_mic = info
                    log.info("Wake word microphone on a %s screen: %s", layout, info[:300])
                conv = cmd.get("conversation_id")
                run["conv"] = conv if isinstance(conv, str) and conv else None
                try:
                    out = run_message(new_id(), cmd, pipeline, speak)
                except ValueError as e:
                    await client.send_json({"type": "error", "code": "bad-request", "message": str(e)})
                    await client.send_json({"type": "done"})
                    continue
                if cmd.get("mode") == "text" and await answer(out["input"]["text"]):
                    continue
                await send_run(out)
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
