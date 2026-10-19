"""SQLite storage (stdlib sqlite3, no ORM) plus small shared helpers."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator
from zoneinfo import ZoneInfo

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS people (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL,
    color TEXT NOT NULL,
    role  TEXT NOT NULL,
    sort  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    person_ids TEXT NOT NULL DEFAULT '[]',
    start      TEXT NOT NULL,
    "end"      TEXT NOT NULL,
    all_day    INTEGER NOT NULL DEFAULT 0,
    location   TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    repeat     TEXT
);
CREATE TABLE IF NOT EXISTS chores (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    emoji       TEXT NOT NULL DEFAULT '',
    person_id   TEXT NOT NULL,
    points      INTEGER NOT NULL DEFAULT 0,
    time_of_day TEXT NOT NULL DEFAULT 'anytime',
    schedule    TEXT NOT NULL,
    sort        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS completions (
    chore_id     TEXT NOT NULL,
    date         TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY (chore_id, date)
);
CREATE TABLE IF NOT EXISTS ledger (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    id        TEXT NOT NULL UNIQUE,
    person_id TEXT NOT NULL,
    change    INTEGER NOT NULL,
    reason    TEXT NOT NULL DEFAULT '',
    at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ledger_person ON ledger(person_id);
CREATE TABLE IF NOT EXISTS rewards (
    id        TEXT PRIMARY KEY,
    title     TEXT NOT NULL,
    emoji     TEXT NOT NULL DEFAULT '',
    cost      INTEGER NOT NULL,
    person_id TEXT
);
CREATE TABLE IF NOT EXISTS lists (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    kind  TEXT NOT NULL,
    sort  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS items (
    id         TEXT PRIMARY KEY,
    list_id    TEXT NOT NULL,
    title      TEXT NOT NULL,
    done       INTEGER NOT NULL DEFAULT 0,
    person_id  TEXT,
    due        TEXT,
    created_at TEXT NOT NULL,
    done_at    TEXT,
    sort       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS items_list ON items(list_id);
CREATE TABLE IF NOT EXISTS meals (
    id        TEXT PRIMARY KEY,
    date      TEXT NOT NULL,
    slot      TEXT NOT NULL,
    title     TEXT NOT NULL,
    notes     TEXT NOT NULL DEFAULT '',
    recipe_id TEXT
);
CREATE INDEX IF NOT EXISTS meals_date ON meals(date);
CREATE TABLE IF NOT EXISTS displays (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    layout     TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_seen  TEXT,
    revoked    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS recipes (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    emoji       TEXT NOT NULL DEFAULT '',
    minutes     INTEGER,
    ingredients TEXT NOT NULL DEFAULT '[]',
    url         TEXT
);
"""

# Added to recipes after the first release (see routes/recipes.py). `ingredients` holds lines of text, `steps` JSON
# [{text, minutes, photo}], photos are ids in the images table.
RECIPE_EXTRA_COLUMNS = {
    "description": "TEXT NOT NULL DEFAULT ''",
    "photo": "TEXT",
    "rating": "INTEGER NOT NULL DEFAULT 0",
    "favourite": "INTEGER NOT NULL DEFAULT 0",
    "servings": "INTEGER",
    "prep_minutes": "INTEGER",
    "cook_minutes": "INTEGER",
    "steps": "TEXT NOT NULL DEFAULT '[]'",
    "tags": "TEXT NOT NULL DEFAULT '[]'",
    "notes": "TEXT NOT NULL DEFAULT ''",
    "cooked_count": "INTEGER NOT NULL DEFAULT 0",
    "course": "TEXT",                     # a key of recipe_text.COURSES, or null
    "book": "TEXT NOT NULL DEFAULT ''",   # the cookbook it came from
    "book_page": "INTEGER",
    "last_cooked": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}
# Scanning a whole cookbook (recipe_batch.py): the pages of a scan, each read by Claude on its own, and the recipes
# found in them waiting for the family to check and save. Rows go once a scan has been read and gone through.
BATCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS recipe_batches (
    id           TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    cheaper      INTEGER NOT NULL DEFAULT 0,  -- sent as an Anthropic Message Batch: half price, within a day
    anthropic_id TEXT,                        -- that batch, while Anthropic is reading it
    book         TEXT NOT NULL DEFAULT ''     -- the cookbook's name, given to every recipe found
);
CREATE TABLE IF NOT EXISTS recipe_batch_pages (
    batch_id TEXT NOT NULL,
    page     INTEGER NOT NULL,
    image    TEXT NOT NULL,
    status   TEXT NOT NULL DEFAULT 'waiting',
    result   TEXT,
    error    TEXT,
    PRIMARY KEY (batch_id, page)
);
CREATE TABLE IF NOT EXISTS recipe_drafts (
    id       TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    piece    TEXT NOT NULL,
    pages    TEXT NOT NULL,
    draft    TEXT NOT NULL,
    status   TEXT NOT NULL DEFAULT 'ready',
    UNIQUE (batch_id, piece)
);
"""

# Pictures uploaded from the screens and apps (recipe and step photos). Kept in the database so a backup has them.
IMAGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id         TEXT PRIMARY KEY,
    mime       TEXT NOT NULL,
    data       BLOB NOT NULL,
    created_at TEXT NOT NULL
);
"""

# Calendar sync (see caldav_sync.py). Credentials live only in this database file.
SYNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,              -- icloud | caldav | ics (published calendar link)
    label      TEXT NOT NULL DEFAULT '',
    username   TEXT NOT NULL,
    password   TEXT NOT NULL,              -- never returned by the API (for ics: the full feed URL)
    server_url TEXT NOT NULL,              -- for ics: a masked form of the URL, safe to show
    home_url   TEXT,                       -- discovered calendar-home-set
    status     TEXT NOT NULL DEFAULT 'ok', -- ok | auth_failed | error
    last_error TEXT,
    last_sync  TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calendars (
    id         TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    url        TEXT NOT NULL,
    name       TEXT NOT NULL,
    color      TEXT NOT NULL DEFAULT '#8A94A6',
    ctag       TEXT,                       -- getctag (or sync-token) seen at the last full pull;
                                           -- for ics: JSON {etag, last_modified, sha} of the last fetch
    person_ids TEXT NOT NULL DEFAULT '[]',
    visible    INTEGER NOT NULL DEFAULT 1,
    read_only  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(account_id, url)
);
"""
# Photo screensaver source (see immich.py): one row; the API key lives only in this database file.
IMMICH_SCHEMA = """
CREATE TABLE IF NOT EXISTS immich (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    server_url   TEXT NOT NULL,
    api_key      TEXT NOT NULL,             -- never returned by the API
    album_ids    TEXT NOT NULL DEFAULT '[]',
    favorites    INTEGER NOT NULL DEFAULT 0,
    memories     INTEGER NOT NULL DEFAULT 0,
    skip_cert_check INTEGER NOT NULL DEFAULT 0,  -- HTTPS without checking the certificate (self-signed, by IP)
    mode         TEXT NOT NULL DEFAULT 'albums',  -- albums = the chosen ones; all = whole library minus excluded
    excluded_album_ids TEXT NOT NULL DEFAULT '[]',
    festive      INTEGER NOT NULL DEFAULT 1,     -- Christmas albums only in December, see immich.py
    updated_at   TEXT NOT NULL
);
"""
# Nursery updates from Tapestry (see tapestry.py): the family's login (one row; the password never leaves this file)
# and a copy of the newest updates. Their photos are files in a "nursery" folder beside this database.
TAPESTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS tapestry (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    email       TEXT NOT NULL,
    password    TEXT NOT NULL,              -- never returned by the API
    school      TEXT NOT NULL DEFAULT '',   -- which setting to open, for accounts at more than one ('' = the first)
    school_name TEXT,                       -- the one opened at the last check
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | ok | auth_failed | error
    last_error  TEXT,
    last_sync   TEXT,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nursery_updates (
    id         TEXT PRIMARY KEY,            -- Tapestry's observation id
    title      TEXT NOT NULL,
    notes      TEXT NOT NULL DEFAULT '',
    author     TEXT NOT NULL DEFAULT '',
    date       TEXT NOT NULL,               -- YYYY-MM-DDTHH:MM:SS, when the nursery wrote it
    children   TEXT NOT NULL DEFAULT '[]',  -- names as Tapestry has them
    photos     TEXT NOT NULL DEFAULT '[]',  -- [{mime, video}], file n in the nursery folder
    comments   TEXT NOT NULL DEFAULT '[]',  -- [{author, date, text}]
    signature  TEXT NOT NULL,               -- of Tapestry's list entry: read again when it changes
    fetched_at TEXT NOT NULL
);
"""
IMMICH_EXTRA_COLUMNS = {
    "skip_cert_check": "INTEGER NOT NULL DEFAULT 0",
    "mode": "TEXT NOT NULL DEFAULT 'albums'",
    "excluded_album_ids": "TEXT NOT NULL DEFAULT '[]'",
    "festive": "INTEGER NOT NULL DEFAULT 1",  # replaced 0.5.3's per-album date ranges ("seasons", now unused)
}
# Nullable source columns on events; NULL calendar_id = local-only event.
EVENT_SOURCE_COLUMNS = {
    "calendar_id": "TEXT", "uid": "TEXT", "href": "TEXT", "etag": "TEXT", "raw_ics": "TEXT",
    "custom_repeat": "INTEGER NOT NULL DEFAULT 0",  # 1 = expand from raw_ics (EXDATE, overrides, COUNT...)
    "busy": "TEXT",  # free/busy status of a synced event: busy | tentative | away | elsewhere | free
}
# Added to calendars after the first release (see ics_feed.py).
CALENDAR_EXTRA_COLUMNS = {
    "busy_auto": "INTEGER NOT NULL DEFAULT 0",  # every summary looks like a free/busy placeholder
    "busy_blocks": "INTEGER",                   # household's choice; NULL = follow busy_auto
    "display_name": "TEXT",                     # household's name for it; NULL = the source's name
}

DEFAULT_SETTINGS = {
    "family_name": "Our Family",
    "week_start": "monday",
    "temp_unit": "C",
    "theme": "auto",  # light, dark, or auto (match each device's own light/dark setting)
    "chore_approval": False,
    # Photo screensaver (photos come from Immich, see immich.py): seconds per photo, idle minutes per layout (0 = never).
    "screensaver_seconds": 10,
    "photo_details": True,  # when and where each photo was taken, small at the top right
    "idle_minutes": {"large": 5, "compact": 3, "phone": 0},
    # Per style of screen: which sections the menu shows (Settings is always there) and which one it opens on.
    # Used where there is no paired screen (the Home Assistant app and sidebar) and to start a new screen's setup.
    "screens": {
        "large": {"start": "calendar", "sections": ["calendar", "chores", "rewards", "meals", "recipes", "lists", "nursery",
                                                    "security"]},
        "compact": {"start": "today", "sections": ["today", "calendar", "chores", "rewards", "meals", "recipes", "lists",
                                                   "security"]},
        "phone": {"start": "today", "sections": ["today", "calendar", "chores", "rewards", "meals", "recipes", "lists"]},
    },
    "timezone": "Europe/London",  # overridden by MOONLIGHT_TIMEZONE, see default_settings()
}

FALLBACK_TIMEZONE = "Europe/London"


def default_timezone() -> str:
    """Household timezone when none is saved: MOONLIGHT_TIMEZONE (the add-on passes Home Assistant's zone)
    if it is a valid IANA name, else Europe/London."""
    name = os.environ.get("MOONLIGHT_TIMEZONE", "").strip()
    if name:
        try:
            ZoneInfo(name)
            return name
        except Exception:
            pass
    return FALLBACK_TIMEZONE


def default_settings() -> dict[str, Any]:
    """DEFAULT_SETTINGS with the timezone resolved from the environment."""
    return {**DEFAULT_SETTINGS, "timezone": default_timezone()}

_db_path: str = os.environ.get("MOONLIGHT_DB", "./moonlight.db")


def configure(path: str) -> None:
    global _db_path
    _db_path = path


def db_path() -> str:
    return _db_path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, roll back on error, always close."""
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    parent = os.path.dirname(os.path.abspath(_db_path))
    os.makedirs(parent, exist_ok=True)
    with connect() as c:
        c.executescript(SCHEMA)
        c.executescript(SYNC_SCHEMA)
        c.executescript(IMMICH_SCHEMA)
        c.executescript(IMAGES_SCHEMA)
        c.executescript(BATCH_SCHEMA)
        c.executescript(TAPESTRY_SCHEMA)
        have = {r[1] for r in c.execute("PRAGMA table_info(recipe_batches)")}
        for col, decl in (("cheaper", "INTEGER NOT NULL DEFAULT 0"), ("anthropic_id", "TEXT"),
                          ("book", "TEXT NOT NULL DEFAULT ''")):
            if col not in have:
                c.execute(f"ALTER TABLE recipe_batches ADD COLUMN {col} {decl}")
        have = {r[1] for r in c.execute("PRAGMA table_info(recipes)")}
        for col, decl in RECIPE_EXTRA_COLUMNS.items():
            if col not in have:
                c.execute(f"ALTER TABLE recipes ADD COLUMN {col} {decl}")
        if "course" not in have:  # a first guess at each recipe's course, from its tags
            from .recipe_text import course_from

            for r in c.execute("SELECT id, tags FROM recipes").fetchall():
                try:
                    course = course_from(json.loads(r[1] or "[]"))
                except ValueError:
                    continue
                if course:
                    c.execute("UPDATE recipes SET course = ? WHERE id = ?", (course, r[0]))
        have = {r[1] for r in c.execute("PRAGMA table_info(events)")}
        for col, decl in EVENT_SOURCE_COLUMNS.items():
            if col not in have:
                c.execute(f"ALTER TABLE events ADD COLUMN {col} {decl}")
        have = {r[1] for r in c.execute("PRAGMA table_info(calendars)")}
        for col, decl in CALENDAR_EXTRA_COLUMNS.items():
            if col not in have:
                c.execute(f"ALTER TABLE calendars ADD COLUMN {col} {decl}")
        c.execute("CREATE INDEX IF NOT EXISTS events_calendar ON events(calendar_id)")
        have = {r[1] for r in c.execute("PRAGMA table_info(displays)")}
        if "setup" not in have:
            c.execute("ALTER TABLE displays ADD COLUMN setup TEXT")  # JSON, see routes/displays.py
        have = {r[1] for r in c.execute("PRAGMA table_info(immich)")}
        for col, decl in IMMICH_EXTRA_COLUMNS.items():
            if col not in have:
                c.execute(f"ALTER TABLE immich ADD COLUMN {col} {decl}")
        _rename_layouts(c)
        _add_recipes_section(c)
        _add_security_section(c)
        _add_nursery_section(c)


# Screen styles were named after rooms until 0.3.8.
OLD_LAYOUTS = {"hallway": "large", "kitchen": "compact"}


def _rename_layouts(c: sqlite3.Connection) -> None:
    for old, new in OLD_LAYOUTS.items():
        c.execute("UPDATE displays SET layout = ? WHERE layout = ?", (new, old))
    for key in ("screens", "idle_minutes", "media_players"):
        val = get_setting(c, key)
        if isinstance(val, dict) and any(k in val for k in OLD_LAYOUTS):
            set_setting(c, key, {OLD_LAYOUTS.get(k, k): v for k, v in val.items()})


# Recipes became their own menu section in 0.5.1 (they were inside Meals). Once, give every menu that shows Meals
# Recipes too, right after it; the marker keeps a later choice to hide Recipes.
RECIPES_MARKER = "recipes_section_added"


def _with_recipes(secs: Any) -> Any:
    if isinstance(secs, list) and "meals" in secs and "recipes" not in secs:
        i = secs.index("meals") + 1
        return secs[:i] + ["recipes"] + secs[i:]
    return secs


def _add_recipes_section(c: sqlite3.Connection) -> None:
    if get_setting(c, RECIPES_MARKER):
        return
    screens = get_setting(c, "screens")
    if isinstance(screens, dict):
        for conf in screens.values():
            if isinstance(conf, dict) and "sections" in conf:
                conf["sections"] = _with_recipes(conf["sections"])
        set_setting(c, "screens", screens)
    for d in c.execute("SELECT id, setup FROM displays WHERE setup IS NOT NULL").fetchall():
        try:
            setup = json.loads(d["setup"])
        except ValueError:
            continue
        if isinstance(setup, dict) and "sections" in setup:
            setup["sections"] = _with_recipes(setup["sections"])
            c.execute("UPDATE displays SET setup = ? WHERE id = ?", (json.dumps(setup), d["id"]))
    set_setting(c, RECIPES_MARKER, True)


# Security (the alarm and cameras from Home Assistant) arrived in 0.6.0. Once, add it to the wall screens' menus
# (large and compact; not phones); the marker keeps a later choice to hide it.
SECURITY_MARKER = "security_section_added"


def _with_security(secs: Any) -> Any:
    return secs + ["security"] if isinstance(secs, list) and secs and "security" not in secs else secs


def _add_security_section(c: sqlite3.Connection) -> None:
    if get_setting(c, SECURITY_MARKER):
        return
    screens = get_setting(c, "screens")
    if isinstance(screens, dict):
        for layout, conf in screens.items():
            if layout in ("large", "compact") and isinstance(conf, dict) and "sections" in conf:
                conf["sections"] = _with_security(conf["sections"])
        set_setting(c, "screens", screens)
    rows = c.execute("SELECT id, setup FROM displays WHERE setup IS NOT NULL AND layout IN ('large', 'compact')")
    for d in rows.fetchall():
        try:
            setup = json.loads(d["setup"])
        except ValueError:
            continue
        if isinstance(setup, dict) and "sections" in setup:
            setup["sections"] = _with_security(setup["sections"])
            c.execute("UPDATE displays SET setup = ? WHERE id = ?", (json.dumps(setup), d["id"]))
    set_setting(c, SECURITY_MARKER, True)


# Nursery (Tapestry updates) became a menu section in 0.6.2. Once, add it to the large screens' menus (it only shows
# once Tapestry is connected); the marker keeps a later choice to hide it.
NURSERY_MARKER = "nursery_section_added"


def _add_nursery_section(c: sqlite3.Connection) -> None:
    if get_setting(c, NURSERY_MARKER):
        return
    screens = get_setting(c, "screens")
    if isinstance(screens, dict) and isinstance(screens.get("large"), dict):
        secs = screens["large"].get("sections")
        if isinstance(secs, list) and "nursery" not in secs:
            screens["large"]["sections"] = secs + ["nursery"]
            set_setting(c, "screens", screens)
    for d in c.execute("SELECT id, setup FROM displays WHERE setup IS NOT NULL AND layout = 'large'").fetchall():
        try:
            setup = json.loads(d["setup"])
        except ValueError:
            continue
        if isinstance(setup, dict) and isinstance(setup.get("sections"), list) and "nursery" not in setup["sections"]:
            setup["sections"].append("nursery")
            c.execute("UPDATE displays SET setup = ? WHERE id = ?", (json.dumps(setup), d["id"]))
    set_setting(c, NURSERY_MARKER, True)


def is_empty() -> bool:
    with connect() as c:
        n = c.execute(
            "SELECT (SELECT COUNT(*) FROM people) + (SELECT COUNT(*) FROM settings "
            "WHERE key NOT IN ('instance_id', ?, ?, ?))",
            (RECIPES_MARKER, SECURITY_MARKER, NURSERY_MARKER),
        ).fetchone()[0]
    return n == 0


# ---------------------------------------------------------------- helpers

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def now_precise() -> str:
    """Microsecond timestamp for ordering (e.g. item done time); not exposed in the API."""
    return datetime.now().isoformat()


def rows(c: sqlite3.Connection, sql: str, args: tuple | list = ()) -> list[dict]:
    return [dict(r) for r in c.execute(sql, args).fetchall()]


def row(c: sqlite3.Connection, sql: str, args: tuple | list = ()) -> dict | None:
    r = c.execute(sql, args).fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------- settings

def get_setting(c: sqlite3.Connection, key: str, default: Any = None) -> Any:
    r = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def instance_id() -> str:
    """A random id for this Moonlight, so apps that find it under several names list it once."""
    with connect() as c:
        val = get_setting(c, "instance_id")
        if not val:
            val = secrets.token_hex(8)
            set_setting(c, "instance_id", val)
    return val


def set_setting(c: sqlite3.Connection, key: str, value: Any) -> None:
    c.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )


# ---------------------------------------------------------------- PIN

_PBKDF2_ROUNDS = 100_000


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def check_pin_hash(pin: str, stored: str) -> bool:
    try:
        _, rounds, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


def set_pin(c: sqlite3.Connection, pin: str) -> None:
    set_setting(c, "pin_hash", hash_pin(pin))


def verify_pin(c: sqlite3.Connection, pin: Any) -> bool:
    stored = get_setting(c, "pin_hash")
    if not stored:
        return True  # no PIN configured: nothing to protect
    if pin is None:
        return False
    return check_pin_hash(str(pin), stored)


# ---------------------------------------------------------------- points

def balance(c: sqlite3.Connection, person_id: str) -> int:
    return c.execute(
        "SELECT COALESCE(SUM(change), 0) FROM ledger WHERE person_id = ?", (person_id,)
    ).fetchone()[0]


def add_ledger(c: sqlite3.Connection, person_id: str, change: int, reason: str, at: str | None = None) -> None:
    c.execute(
        "INSERT INTO ledger(id, person_id, change, reason, at) VALUES(?, ?, ?, ?, ?)",
        (new_id("lg"), person_id, int(change), reason, at or now_iso()),
    )
