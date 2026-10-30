"""Assist (Home Assistant's voice assistant) on the screens; see voice.py."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import Response, StreamingResponse

from .. import auth, db, media, voice
from ..common import layout_name

router = APIRouter(prefix="/api/voice")


@router.get("")
async def status(layout: str = "compact"):
    """What this style of screen can do: {available, reason?, pipelines, preferred, pipeline, wake_engine, wake,
    replies}. `pipeline` is the one screens use (Settings, else Home Assistant's preferred one)."""
    layout = layout_name(layout or "compact")
    with db.connect() as c:
        conf = voice.saved(c)
    out = {"available": False, "pipelines": [], "preferred": "", "pipeline": conf["pipeline"], "wake_engine": False,
           "wake": conf["wake"].get(layout, False), "wake_by_layout": conf["wake"], "replies": conf["replies"]}
    svc = media.service()
    if svc is None:
        return {**out, "reason": "Moonlight isn't connected to Home Assistant"}
    try:
        got = await voice.pipelines(svc)
    except voice.VoiceError as e:
        return {**out, "reason": str(e)}
    ids = {p["id"] for p in got["pipelines"]}
    chosen = conf["pipeline"] if conf["pipeline"] in ids else got["preferred"]
    out.update(got, available=bool(got["pipelines"]), pipeline=chosen)
    if not got["pipelines"]:
        out["reason"] = "Home Assistant has no Assist pipeline yet"
    return out


@router.post("/sample")
async def start_sample(seconds: float = 20):
    """Record what the screens listening for the wake word hear for the next `seconds` (at most 60)."""
    voice.record_sample(seconds)
    return {"recording": min(max(seconds, 1), voice.SAMPLE_MAX_SECONDS)}


@router.get("/sample.wav")
async def sample():
    """The last recording made by POST /api/voice/sample (empty if none)."""
    return Response(voice.sample_wav(), media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.get("/sample.json")
async def sample_json(start: float = 0, seconds: float = 0):
    """Part of the last recording (at most 10 s from `start`) as base64 16-bit PCM, with its loudness every 100 ms."""
    return voice.sample_part(start, seconds)


@router.websocket("/ws")
async def voice_socket(ws: WebSocket, layout: str = "compact"):
    await ws.accept()
    svc = media.service()
    if svc is None:
        await ws.send_json({"type": "error", "code": "unreachable", "message": "Moonlight isn't connected to Home Assistant"})
        await ws.close()
        return
    layout = layout_name(layout or "compact")
    with db.connect() as c:
        conf = voice.saved(c)
    replies, speaker = conf["replies"], ""
    display = auth.current(ws)["display"]
    if replies == "speaker":
        speaker = media.entity_for(layout, display)
        replies = "speaker" if speaker else "screen"  # a screen with no speaker answers out loud itself
    await voice.relay(ws, svc, pipeline=conf["pipeline"], replies=replies, speaker=speaker, display=display,
                      layout=layout)
    try:
        await ws.close()
    except RuntimeError:
        pass  # already closed by the screen


@router.get("/audio/{key}")
async def audio(key: str, request: Request):
    """A spoken reply, streamed from Home Assistant (only replies the voice relay has handed out)."""
    svc = media.service()
    if svc is None or voice.audio_path(key) is None:
        raise HTTPException(status_code=404, detail="That reply has gone")
    cm = voice.fetch_audio(svc, key)
    try:
        status, ctype, body = await cm.__aenter__()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Couldn't fetch the reply from Home Assistant: {e}")
    if status != 200:
        await cm.__aexit__(None, None, None)
        raise HTTPException(status_code=502, detail=f"Home Assistant answered {status} for the reply")

    async def stream():
        try:
            async for chunk in body:
                yield chunk
        finally:
            await cm.__aexit__(None, None, None)

    return StreamingResponse(stream(), media_type=ctype if ctype.startswith("audio/") else "audio/mpeg",
                             headers={"Cache-Control": "no-store"})
