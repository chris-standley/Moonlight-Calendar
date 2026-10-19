"""Nursery updates from Tapestry (tapestryjournal.com), the early years learning journal.

Tapestry has no public API for parents. Moonlight signs in with the family's own email and password the way the
website does, then reads the JSON endpoints Tapestry's own web app uses. Unofficial, so it may need adjusting if
Tapestry changes its site:

- `GET  /login`   -> the sign-in page: a form with `_token` (Laravel's CSRF token), email and password
- `POST /login`   -> redirects into the journal, or to `/select-school` for accounts at more than one setting,
                     which links to each one (`/s/<slug>/...` or `/visit-school/<id>`)
- `GET  /api/4/observations/list?perPage=N` -> {observations: [...], nextCursor}   (newest first)
- `GET  /api/4/observations/get/{id}`       -> {observation: {...}}  full notes, every photo, comments
  Both need `X-Requested-With: XMLHttpRequest`, `X-CSRF-TOKEN` and `X-TAPESTRY-VERSION: 3`; a lapsed session
  answers 401/419 or redirects to /login, and Moonlight signs in again once.

Accounts that sign in with Google or Microsoft, or with a 2FA code, can't be used.

The newest updates are copied into the database, and their photos into files beside it (Tapestry's photo links are
signed and expire), so the screens never talk to Tapestry and still show the updates when it can't be reached. The
journal is checked every SYNC_SECONDS; a rejected password stops the checks until the login is changed, so the
account isn't locked.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import re
import shutil
import time
from contextlib import asynccontextmanager
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from . import db
from .common import hub, log

BASE_URL = "https://tapestryjournal.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
SYNC_SECONDS = float(os.environ.get("MOONLIGHT_TAPESTRY_SECONDS", "1800"))
RETRY_SECONDS = 600.0  # after Tapestry couldn't be reached
KEEP = 40  # newest updates kept; older ones and their photos are deleted
PAGE = 20  # updates read per check (new ones appear at the top)
MAX_PHOTOS = 12  # per update
MAX_BYTES = 15 * 1024 * 1024  # per photo
API_HEADERS = {"X-Requested-With": "XMLHttpRequest", "X-TAPESTRY-VERSION": "3", "Accept": "application/json"}

# Tests swap in an httpx.MockTransport; None = real network.
transport: httpx.AsyncBaseTransport | None = None


class TapestryError(Exception):
    """Tapestry couldn't be reached or answered unexpectedly. The message is safe to show (never has the password)."""


class AuthFailed(TapestryError):
    """The email and password (or the account's way of signing in) didn't work: don't retry until they change."""


# ---------------------------------------------------------------- pages and text

class _Page(HTMLParser):
    """The forms, links, CSRF token and title of an HTML page (stdlib only)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[dict] = []
        self.links: list[dict] = []
        self.meta_csrf = ""
        self.title = ""
        self._form: dict | None = None
        self._link: dict | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "form":
            self._form = {"action": a.get("action", ""), "method": (a.get("method") or "get").upper(), "inputs": []}
            self.forms.append(self._form)
        elif tag == "input" and self._form is not None:
            self._form["inputs"].append({"name": a.get("name", ""), "type": a.get("type", "text").lower(),
                                         "value": a.get("value", "")})
        elif tag == "a" and a.get("href"):
            self._link = {"href": a["href"], "text": ""}
            self.links.append(self._link)
        elif tag == "meta" and a.get("name") == "csrf-token":
            self.meta_csrf = a.get("content", "")
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._form = None
        elif tag == "a":
            self._link = None
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._link is not None:
            self._link["text"] += data
        if self._in_title:
            self.title += data


def parse_page(text: str) -> _Page:
    p = _Page()
    try:
        p.feed(text)
        p.close()
    except Exception:  # half a page still has what we need
        pass
    return p


def csrf_token(text: str, page: _Page | None = None) -> str:
    """Tapestry puts it in a JSON config (`"csrfToken"` / `"csrf_token"`), a meta tag and the login form."""
    m = re.search(r'"csrf_?[tT]oken"\s*:\s*"([^"]+)"', text) or re.search(r"&quot;csrf_?[tT]oken&quot;:&quot;(.+?)&quot;", text)
    if m:
        return m.group(1)
    page = page or parse_page(text)
    if page.meta_csrf:
        return page.meta_csrf
    for f in page.forms:
        for i in f["inputs"]:
            if i["name"] == "_token" and i["value"]:
                return i["value"]
    return ""


class _Text(HTMLParser):
    BLOCK = {"p", "div", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.out.append("\n")
        elif tag == "li":
            self.out.append("\n• ")

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        self.out.append(data)


def plain_text(value: Any) -> str:
    """Tapestry's notes are HTML from a rich text editor: plain text with line breaks."""
    if not value:
        return ""
    s = str(value)
    if re.search(r"<[a-zA-Z/][^>]*>", s):
        p = _Text()
        try:
            p.feed(s)
            p.close()
        except Exception:
            pass
        s = "".join(p.out)
    else:
        s = html.unescape(s)
    s = s.replace("\xa0", " ").replace("\r", "")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n[ \t]+(?!• )", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


# ---------------------------------------------------------------- observations

DATE_KEYS = ("observationDate", "observation_date", "observation_time", "date", "createdAt", "created_at",
             "page_added", "publishedAt", "scheduledAt")


def _name(p: Any) -> str:
    if isinstance(p, dict):
        full = p.get("fullName") or p.get("full_name") or p.get("name") or p.get("displayName")
        if not full:
            full = " ".join(str(p[k]) for k in ("firstName", "first_name", "lastName", "last_name") if p.get(k))
        return str(full or "").strip()
    return str(p or "").strip()


def iso_time(value: Any) -> str | None:
    """Tapestry's dates as `YYYY-MM-DDTHH:MM:SS` (or a bare date), else None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 1e9:
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value).strftime("%Y-%m-%dT%H:%M:%S")
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%d %b %Y %I:%M %p", "%d %b %Y"):
            try:
                d = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if d.tzinfo is not None:
        d = d.astimezone()  # the add-on runs in the household's timezone
    if len(s) == 10:
        return d.strftime("%Y-%m-%d")
    return d.strftime("%Y-%m-%dT%H:%M:%S")


def _when(o: dict) -> str | None:
    for k in DATE_KEYS:
        t = iso_time(o.get(k))
        if t:
            return t
    return None


def _is_video(m: dict, url: str) -> bool:
    kind = str(m.get("type") or m.get("mimeType") or m.get("mime_type") or m.get("mediaType") or "").lower()
    return "video" in kind or bool(re.search(r"\.(mp4|mov|m4v|webm|3gp)(\?|$)", url, re.I))


def media_of(o: dict) -> list[dict]:
    """Photos (and videos, shown by their still) attached to an observation: [{url, video}]; `url` is what to download."""
    out: list[dict] = []
    seen: set[str] = set()
    for key in ("media", "images", "photos", "videos", "attachments"):
        for m in o.get(key) or []:
            if not isinstance(m, dict):
                continue
            full = m.get("original_url") or m.get("originalUrl") or m.get("url") or m.get("src")
            thumb = m.get("thumbnailUrl") or m.get("thumbnail_url") or m.get("thumbnail")
            # A large rendition when there is one: originals from a phone are several megabytes.
            large = m.get("largeUrl") or m.get("large_url") or m.get("previewUrl") or m.get("preview_url")
            video = _is_video(m, str(full or ""))
            url = (thumb or large) if video else (large or full or thumb)
            if isinstance(url, str) and url and url not in seen:
                seen.add(url)
                out.append({"url": url, "video": video})
    return out


def comments_of(o: dict) -> list[dict]:
    out = []
    for c in o.get("comments") or []:
        if isinstance(c, dict):
            body = plain_text(c.get("body") or c.get("text") or c.get("comment") or c.get("content"))
            if body:
                out.append({"author": _name(c.get("author") or c.get("user") or c.get("createdBy")), "date": _when(c),
                            "text": body})
    return out


def normalise(o: dict) -> dict:
    """What Moonlight keeps of one observation."""
    kids = o.get("children")
    if isinstance(kids, list):
        children = [n for n in (_name(k) for k in kids) if n]
    else:
        one = _name(o.get("child")) or str(o.get("child_name") or "").strip()
        children = [one] if one else []
    notes = plain_text(o.get("notes") or o.get("body") or o.get("text") or o.get("description"))
    extra = plain_text(o.get("additionalInformation") or o.get("additional_information"))
    if extra and extra not in notes:
        notes = f"{notes}\n\n{extra}" if notes else extra
    return {
        "id": str(o.get("id")),
        "title": plain_text(o.get("title")) or "Nursery update",
        "notes": notes,
        "author": _name(o.get("author") or o.get("createdBy") or o.get("staff") or o.get("addedBy")),
        "date": _when(o),
        "children": children,
        "media": media_of(o),
        "media_count": o.get("mediaCount") if isinstance(o.get("mediaCount"), int) else None,
        "comments": comments_of(o),
    }


def signature(o: dict) -> str:
    """Changes when an observation in the list was edited, got photos or comments: then it's read again."""
    parts = [o.get("title"), o.get("notes") or o.get("body"), o.get("mediaCount"), len(o.get("media") or []),
             o.get("commentCount") or o.get("commentsCount") or len(o.get("comments") or []),
             o.get("updatedAt") or o.get("updated_at") or o.get("modifiedAt")]
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- client

class Client:
    def __init__(self, email: str, password: str, school: str = "", base_url: str = BASE_URL) -> None:
        self.email, self._password, self.school = email.strip(), password, school.strip()
        self.base = base_url.rstrip("/")
        self.csrf = ""
        self.school_name = ""
        self.cookies = httpx.Cookies()  # the signed-in session, kept between checks

    def key(self) -> tuple[str, str, str]:
        return self.email, self._password, self.school

    @asynccontextmanager
    async def http(self) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(base_url=self.base, timeout=TIMEOUT, transport=transport, follow_redirects=True,
                                     cookies=self.cookies,
                                     headers={"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"}) as http:
            try:
                yield http
            finally:
                self.cookies = http.cookies

    def _unreachable(self, e: httpx.HTTPError) -> TapestryError:
        if isinstance(e, httpx.TimeoutException):
            return TapestryError("Tapestry didn't answer in time. Moonlight will try again later")
        return TapestryError(f"Couldn't reach Tapestry ({type(e).__name__}). Check the add-on can reach the internet")

    async def _get(self, http: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
        try:
            return await http.get(url, **kw)
        except httpx.HTTPError as e:
            raise self._unreachable(e) from None

    async def login(self, http: httpx.AsyncClient) -> None:
        http.cookies.clear()
        r = await self._get(http, "/login")
        if r.status_code != 200:
            raise TapestryError(f"Tapestry's sign-in page answered {r.status_code}")
        page = parse_page(r.text)
        token = csrf_token(r.text, page)
        if not token:
            raise TapestryError("Tapestry's sign-in page has changed (no sign-in token found)")
        form = next((f for f in page.forms if any(i["type"] == "password" for i in f["inputs"])), None)
        fields: dict[str, str] = {}
        for i in (form or {}).get("inputs", []):
            name, kind = i["name"], i["type"]
            if not name:
                continue
            if name == "_token":
                fields[name] = token
            elif kind == "email" or name in ("email", "username", "login"):
                fields[name] = self.email
            elif kind == "password":
                fields[name] = self._password
            elif kind in ("hidden",) or (kind in ("checkbox", "radio") and name.startswith("remember")):
                fields[name] = i["value"] or "1"
        fields.setdefault("_token", token)
        if not any(v == self.email for v in fields.values()):
            fields["email"] = self.email
        if not any(v == self._password for v in fields.values()):
            fields["password"] = self._password
        action = str(r.url.join((form or {}).get("action") or "/login"))
        if httpx.URL(action).host != httpx.URL(self.base).host:
            raise TapestryError("Tapestry's sign-in form points somewhere unexpected, so Moonlight didn't send the password")
        try:
            r = await http.post(action, data=fields, headers={"Referer": str(r.url), "Origin": self.base})
        except httpx.HTTPError as e:
            raise self._unreachable(e) from None
        if r.status_code == 419:
            raise TapestryError("Tapestry turned the sign-in down (the page expired). Moonlight will try again")
        if r.status_code == 429:
            raise TapestryError("Tapestry has had too many sign-in attempts. Wait a while before trying again")
        if r.status_code >= 400:
            raise TapestryError(f"Tapestry answered {r.status_code} when signing in")
        body = r.text
        path = r.url.path.rstrip("/")
        if re.search(r"two[- ]factor|verification code|authenticator app|one[- ]time code", body, re.I):
            raise AuthFailed("This Tapestry account asks for a verification code when signing in, which Moonlight "
                             "can't do. Turn off two-step sign-in for this account, or use another carer's login")
        landed = parse_page(body)
        if path == "/login" or any(i["type"] == "password" for f in landed.forms for i in f["inputs"]):
            raise AuthFailed("Tapestry didn't accept that email and password. Check they work at tapestryjournal.com "
                             "(accounts that sign in with Google or Microsoft can't be used)")
        if "select-school" in path:
            r = await self._choose_school(http, r, landed)
            body = r.text
        self.csrf = csrf_token(body) or token

    async def _choose_school(self, http: httpx.AsyncClient, r: httpx.Response, page: _Page) -> httpx.Response:
        """Accounts at more than one setting pick one after signing in: the one named in Settings, else the first."""
        choices: list[dict] = []
        for link in page.links:
            url = r.url.join(link["href"])
            if url.host != r.url.host:
                continue
            slug = re.match(r"^/s/([^/]+)", url.path)
            if slug or re.search(r"/(visit|select)-school/[^/]+", url.path):
                name = " ".join(link["text"].split()) or (slug.group(1) if slug else url.path)
                if not any(c["url"] == str(url) for c in choices):
                    choices.append({"name": name, "slug": slug.group(1) if slug else "", "url": str(url)})
        if not choices:
            raise TapestryError("Tapestry asked which nursery or school to open, but Moonlight couldn't read the choices")
        want = self.school.lower()
        pick = next((c for c in choices if want and (c["slug"].lower() == want or want in c["name"].lower())), None)
        if want and not pick:
            raise AuthFailed(f"None of this account's settings match \"{self.school}\". It has: "
                             + ", ".join(c["name"] for c in choices))
        pick = pick or choices[0]
        self.school_name = pick["name"]
        out = await self._get(http, pick["url"])
        if out.status_code >= 400 or "select-school" in out.url.path:
            raise TapestryError(f"Couldn't open {pick['name']} on Tapestry ({out.status_code})")
        return out

    async def api(self, http: httpx.AsyncClient, path: str, params: dict | None = None, retry: bool = True) -> Any:
        if not self.csrf:
            await self.login(http)
        try:
            r = await http.get(path, params=params, headers={**API_HEADERS, "X-CSRF-TOKEN": self.csrf},
                               follow_redirects=False)
        except httpx.HTTPError as e:
            raise self._unreachable(e) from None
        lapsed = r.status_code in (401, 419) or (r.is_redirect and "login" in r.headers.get("location", ""))
        data: Any = None
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                lapsed = True  # a web page instead of JSON: the session went
        if lapsed:
            if not retry:
                raise TapestryError("Tapestry signed Moonlight out straight after signing in. Its site may have changed")
            self.csrf = ""
            return await self.api(http, path, params, retry=False)
        if r.status_code != 200:
            raise TapestryError(f"Tapestry answered {r.status_code} when asked for {path}")
        return data

    async def observations(self, http: httpx.AsyncClient, count: int = PAGE) -> list[dict]:
        """The newest observations across every child on the account (list previews)."""
        out: list[dict] = []
        cursor = None
        while len(out) < count:
            params = {"perPage": min(50, count)}
            if cursor:
                params["cursor"] = cursor
            d = await self.api(http, "/api/4/observations/list", params)
            items = d if isinstance(d, list) else (d or {}).get("observations") or (d or {}).get("data") or []
            items = [o for o in items if isinstance(o, dict) and o.get("id") is not None]
            out.extend(items)
            cursor = None if isinstance(d, list) else (d or {}).get("nextCursor")
            if not cursor or not items:
                break
        return out[:count]

    async def observation(self, http: httpx.AsyncClient, obs_id: str) -> dict:
        d = await self.api(http, f"/api/4/observations/get/{obs_id}")
        if isinstance(d, dict) and isinstance(d.get("observation"), dict):
            return d["observation"]
        return d if isinstance(d, dict) else {}

    async def download(self, http: httpx.AsyncClient, url: str) -> tuple[str, bytes] | None:
        """A photo: (mime, bytes), or None if it isn't an image Moonlight can show. The sign-in cookies only go to
        Tapestry itself; photos on its storage host are fetched with their signed link alone."""
        full = httpx.URL(self.base).join(url)
        own = full.host == httpx.URL(self.base).host
        if full.scheme != "https" and not own:
            return None
        plain = None if own else httpx.AsyncClient(timeout=TIMEOUT, transport=transport, follow_redirects=True,
                                                   headers={"User-Agent": UA})
        try:
            async with (http if own else plain).stream("GET", full) as r:
                mime = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if r.status_code != 200 or not mime.startswith("image/") or mime == "image/svg+xml":
                    return None
                data = bytearray()
                async for chunk in r.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        return None
                return mime, bytes(data)
        except httpx.HTTPError as e:
            log.info("Tapestry photo skipped: %s", type(e).__name__)
            return None
        finally:
            if plain:
                await plain.aclose()


# ---------------------------------------------------------------- storage

def load_config(c) -> dict | None:
    return db.row(c, "SELECT * FROM tapestry WHERE id = 1")


def save_config(c, email: str, password: str, school: str) -> None:
    c.execute("INSERT INTO tapestry(id, email, password, school, status, updated_at) VALUES(1, ?, ?, ?, 'pending', ?) "
              "ON CONFLICT(id) DO UPDATE SET email=excluded.email, password=excluded.password, school=excluded.school, "
              "status='pending', last_error=NULL, updated_at=excluded.updated_at",
              (email, password, school, db.now_iso()))


def set_status(c, status: str, error: str | None = None, synced: bool = False, school_name: str | None = None) -> None:
    c.execute("UPDATE tapestry SET status = ?, last_error = ? WHERE id = 1", (status, error))
    if synced:
        c.execute("UPDATE tapestry SET last_sync = ? WHERE id = 1", (db.now_iso(),))
    if school_name:
        c.execute("UPDATE tapestry SET school_name = ? WHERE id = 1", (school_name,))


def media_dir() -> Path:
    return Path(os.path.abspath(db.db_path())).parent / "nursery"


def _folder(obs_id: str) -> Path:
    safe = obs_id if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", obs_id) else hashlib.sha256(obs_id.encode()).hexdigest()[:32]
    return media_dir() / safe


EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "image/heic": "heic"}


def photo_path(obs_id: str, n: int) -> tuple[Path, str] | None:
    with db.connect() as c:
        r = db.row(c, "SELECT photos FROM nursery_updates WHERE id = ?", (obs_id,))
    if not r:
        return None
    photos = json.loads(r["photos"])
    if not 0 <= n < len(photos):
        return None
    mime = photos[n]["mime"]
    path = _folder(obs_id) / f"{n}.{EXT.get(mime, 'img')}"
    return (path, mime) if path.is_file() else None


def forget_session() -> None:
    global _client
    _client = None


def forget_all(c) -> None:
    forget_session()
    c.execute("DELETE FROM tapestry")
    c.execute("DELETE FROM nursery_updates")
    shutil.rmtree(media_dir(), ignore_errors=True)


def _match_people(c, names: list[str]) -> list[dict]:
    """Tapestry's children, with the Moonlight person of the same first name (children first)."""
    people = db.rows(c, "SELECT id, name, color, role FROM people ORDER BY role = 'child' DESC, sort")
    out = []
    for n in names:
        first = n.split()[0].lower() if n.split() else ""
        p = next((p for p in people if p["name"].split() and p["name"].split()[0].lower() == first), None)
        out.append({"name": n, "person_id": p["id"] if p else None, "color": p["color"] if p else None})
    return out


def updates_out(c, limit: int = KEEP) -> list[dict]:
    out = []
    for r in db.rows(c, "SELECT * FROM nursery_updates ORDER BY date DESC, id DESC LIMIT ?", (limit,)):
        photos = json.loads(r["photos"])
        out.append({
            "id": r["id"], "title": r["title"], "notes": r["notes"], "author": r["author"], "date": r["date"],
            "children": _match_people(c, json.loads(r["children"])),
            "photos": [{"url": f"/api/nursery/photos/{r['id']}/{i}?v={r['signature']}", "video": p.get("video", False)}
                       for i, p in enumerate(photos)],
            "comments": json.loads(r["comments"]),
            "added_at": r["fetched_at"],
        })
    return out


def config_out(c) -> dict:
    cfg = load_config(c)
    count = c.execute("SELECT COUNT(*) FROM nursery_updates").fetchone()[0]
    if not cfg:
        return {"configured": False, "email": "", "school": "", "school_name": None, "status": "unconfigured",
                "last_error": None, "last_sync": None, "count": count}
    return {"configured": True, "email": cfg["email"], "school": cfg["school"], "school_name": cfg.get("school_name"),
            "status": cfg["status"], "last_error": cfg["last_error"], "last_sync": cfg["last_sync"], "count": count}


# ---------------------------------------------------------------- sync

async def _store(client: Client, http: httpx.AsyncClient, raw: dict, sig: str) -> None:
    obs = normalise(raw)
    folder = _folder(obs["id"])
    photos: list[dict] = []
    tmp = folder.with_name(folder.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    for m in obs["media"][:MAX_PHOTOS]:
        got = await client.download(http, m["url"])
        if not got:
            continue
        mime, data = got
        tmp.mkdir(parents=True, exist_ok=True)
        (tmp / f"{len(photos)}.{EXT.get(mime, 'img')}").write_bytes(data)
        photos.append({"mime": mime, "video": m["video"]})
    shutil.rmtree(folder, ignore_errors=True)
    if photos:
        tmp.rename(folder)
    with db.connect() as c:
        c.execute(
            "INSERT INTO nursery_updates(id, title, notes, author, date, children, photos, comments, signature, fetched_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET title=excluded.title, notes=excluded.notes, "
            "author=excluded.author, date=excluded.date, children=excluded.children, photos=excluded.photos, "
            "comments=excluded.comments, signature=excluded.signature",
            (obs["id"], obs["title"], obs["notes"], obs["author"], obs["date"] or db.now_iso()[:19],
             json.dumps(obs["children"]), json.dumps(photos), json.dumps(obs["comments"]), sig, db.now_iso()))


def _prune() -> None:
    with db.connect() as c:
        old = [r["id"] for r in db.rows(c, "SELECT id FROM nursery_updates ORDER BY date DESC, id DESC LIMIT -1 OFFSET ?",
                                        (KEEP,))]
        for obs_id in old:
            c.execute("DELETE FROM nursery_updates WHERE id = ?", (obs_id,))
    for obs_id in old:
        shutil.rmtree(_folder(obs_id), ignore_errors=True)


_client: Client | None = None  # signed in at the last check: the next one carries on with its session


async def sync_now(client: Client | None = None) -> int:
    """Read the newest updates; returns how many were new or changed. Raises TapestryError (status saved)."""
    with db.connect() as c:
        cfg = load_config(c)
        have = {r["id"]: r["signature"] for r in db.rows(c, "SELECT id, signature FROM nursery_updates")}
    if not cfg:
        return 0
    global _client
    if client is None:
        fresh = Client(cfg["email"], cfg["password"], cfg["school"])
        client = _client if _client and _client.key() == fresh.key() else fresh
    _client = client
    changed = 0
    try:
        async with client.http() as http:
            for raw in await client.observations(http, PAGE):
                obs_id, sig = str(raw["id"]), signature(raw)
                if have.get(obs_id) == sig:
                    continue
                full = await client.observation(http, obs_id) or {}
                await _store(client, http, {**raw, **{k: v for k, v in full.items() if v not in (None, "", [])}}, sig)
                changed += 1
    except TapestryError as e:
        with db.connect() as c:
            set_status(c, "auth_failed" if isinstance(e, AuthFailed) else "error", str(e))
        await hub.broadcast("nursery")
        raise
    _prune()
    with db.connect() as c:
        set_status(c, "ok", synced=True, school_name=client.school_name or None)
    if changed:
        log.info("Tapestry: %d new or changed nursery updates", changed)
    await hub.broadcast("nursery")
    return changed


class Syncer:
    """Checks Tapestry every SYNC_SECONDS (sooner after a network error). A rejected login waits for a new one."""

    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.wake: asyncio.Event | None = None

    def start(self) -> None:
        self.wake = asyncio.Event()
        self.task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
            self.task = None

    def poke(self) -> None:
        if self.wake:
            self.wake.set()

    async def _run(self) -> None:
        while True:
            wait = SYNC_SECONDS
            with db.connect() as c:
                cfg = load_config(c)
            if cfg and cfg["status"] != "auth_failed":
                started = time.monotonic()
                try:
                    await sync_now()
                except TapestryError as e:
                    log.warning("Tapestry check failed: %s", e)
                    wait = RETRY_SECONDS
                except Exception:
                    log.exception("Tapestry check failed")
                    wait = RETRY_SECONDS
                wait = max(60.0, wait - (time.monotonic() - started))
            assert self.wake is not None
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass


syncer: Syncer | None = None
