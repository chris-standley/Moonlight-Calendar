"""Bringing recipes in from elsewhere: a web page (its schema.org Recipe data) or, with an Anthropic API key saved in
Settings › Recipes, photos of a cookbook page or a page without that data, read by Claude.

Everything here returns draft fields for the editor; nothing is saved until the family taps Save."""
from __future__ import annotations

import base64
import html
import json
import logging
import re
from html.parser import HTMLParser

import httpx

from . import recipe_text

log = logging.getLogger("moonlight.recipes")

READER_MODEL = "claude-opus-5-5"
MAX_PAGE_BYTES = 4_000_000
USER_AGENT = "Mozilla/5.0 (compatible; Moonlight family calendar; recipe import)"


class ImportError_(Exception):
    """Shown to the family as is."""


# ---------------------------------------------------------------- web pages

class _PageParser(HTMLParser):
    """Collects JSON-LD blocks, the og:image and the visible text of a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ld: list[str] = []
        self.text: list[str] = []
        self.og_image: str | None = None
        self.title = ""
        self._in_ld = False
        self._skip = 0
        self._in_title = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").lower().startswith("application/ld+json"):
            self._in_ld, self._buf = True, []
        elif tag in ("script", "style", "noscript", "svg", "nav", "footer", "header"):
            self._skip += 1
        elif tag == "meta" and (a.get("property") or a.get("name")) in ("og:image", "twitter:image") and not self.og_image:
            self.og_image = a.get("content")
        elif tag == "title":
            self._in_title = True
        elif tag in ("p", "li", "br", "h1", "h2", "h3", "h4", "div", "tr"):
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self._in_ld = False
            self.ld.append("".join(self._buf))
        elif tag in ("script", "style", "noscript", "svg", "nav", "footer", "header") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)
        elif self._in_title:
            self.title += data
        elif not self._skip:
            self.text.append(data)


def _walk(node):
    if isinstance(node, list):
        for x in node:
            yield from _walk(x)
    elif isinstance(node, dict):
        yield node
        for k in ("@graph", "mainEntity", "itemListElement"):
            if k in node:
                yield from _walk(node[k])


def _is_recipe(node: dict) -> bool:
    t = node.get("@type")
    return t == "Recipe" or (isinstance(t, list) and "Recipe" in t)


def _clean(s) -> str:
    if not isinstance(s, str):
        return ""
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"\s+", " ", s).strip()


def _image_url(img) -> str | None:
    if isinstance(img, str):
        return img
    if isinstance(img, list) and img:
        return _image_url(img[-1] if isinstance(img[-1], (dict, str)) else img[0])
    if isinstance(img, dict):
        return img.get("url") or img.get("contentUrl")
    return None


def _steps(instr) -> list[dict]:
    out: list[dict] = []
    if isinstance(instr, str):
        text = _clean(instr)
        parts = [p for p in re.split(r"(?:\n|(?<=\.)\s+(?=\d+[.)]\s))", instr) if _clean(p)]
        return [{"text": _clean(p), "minutes": None, "image_url": None} for p in parts] if len(parts) > 1 else (
            [{"text": text, "minutes": None, "image_url": None}] if text else [])
    if isinstance(instr, list):
        for x in instr:
            if isinstance(x, str):
                out += _steps(x)
            elif isinstance(x, dict):
                if "itemListElement" in x:  # HowToSection
                    out += _steps(x["itemListElement"])
                else:
                    text = _clean(x.get("text") or x.get("name") or "")
                    if text:
                        out.append({"text": text, "minutes": None, "image_url": _image_url(x.get("image"))})
    return out


def _servings(y) -> int | None:
    if isinstance(y, list):
        for v in y:
            if (n := _servings(v)) is not None:
                return n
        return None
    if isinstance(y, (int, float)):
        return int(y) if 0 < y <= 200 else None
    m = re.search(r"\d+", str(y or ""))
    return int(m.group(0)) if m and 0 < int(m.group(0)) <= 200 else None


def _tags(node: dict) -> list[str]:
    tags: list[str] = []
    for k in ("recipeCategory", "recipeCuisine", "keywords"):
        v = node.get(k)
        vals = v if isinstance(v, list) else str(v or "").split(",")
        tags += [_clean(t).lower() for t in vals if _clean(t) and len(_clean(t)) <= 30]
    return list(dict.fromkeys(tags))[:12]


def from_schema(node: dict, url: str) -> dict:
    prep = recipe_text.iso_minutes(node.get("prepTime"))
    cook = recipe_text.iso_minutes(node.get("cookTime"))
    total = recipe_text.iso_minutes(node.get("totalTime"))
    return {
        "title": _clean(node.get("name"))[:120],
        "description": _clean(node.get("description"))[:1000],
        "servings": _servings(node.get("recipeYield")),
        "prep_minutes": prep, "cook_minutes": cook, "minutes": total,
        "ingredients": [_clean(i) for i in (node.get("recipeIngredient") or node.get("ingredients") or []) if _clean(i)],
        "steps": _steps(node.get("recipeInstructions")),
        "tags": _tags(node),
        "notes": "",
        "url": url,
        "image_url": _image_url(node.get("image")),
    }


async def fetch(url: str, limit: int = MAX_PAGE_BYTES) -> tuple[bytes, str]:
    if not re.match(r"^https?://", url, re.I):
        raise ImportError_("Paste a link that starts with http:// or https://")
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20, headers={"User-Agent": USER_AGENT}) as client:
            async with client.stream("GET", url) as r:
                if r.status_code >= 400:
                    raise ImportError_(f"That page answered with error {r.status_code}.")
                chunks, size = [], 0
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ImportError_("That page is too big to read.")
                    chunks.append(chunk)
                return b"".join(chunks), r.headers.get("content-type", "")
    except httpx.HTTPError as e:
        raise ImportError_(f"Couldn't open that page ({e.__class__.__name__}).")


def read_page(page: str, url: str) -> tuple[dict | None, str]:
    """(schema.org recipe draft or None, visible text of the page)."""
    p = _PageParser()
    try:
        p.feed(page)
    except Exception:  # broken markup: use what was read
        pass
    for block in p.ld:
        try:
            data = json.loads(block.strip().rstrip(";"))
        except ValueError:
            continue
        for node in _walk(data):
            if _is_recipe(node):
                draft = from_schema(node, url)
                if not draft["image_url"] and p.og_image:
                    draft["image_url"] = p.og_image
                if draft["title"] and (draft["ingredients"] or draft["steps"]):
                    return draft, ""
    text = re.sub(r"\n\s*\n+", "\n", "".join(p.text))
    text = re.sub(r"[ \t]+", " ", text).strip()
    return None, f"{p.title.strip()}\n{text}"[:60_000]


# ---------------------------------------------------------------- Claude (photos and pages without recipe data)

READER_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean", "description": "False when there is no recipe to read."},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "servings": {"type": ["integer", "null"]},
        "prep_minutes": {"type": ["integer", "null"]},
        "cook_minutes": {"type": ["integer", "null"]},
        "ingredients": {"type": "array", "items": {"type": "string"}},
        "steps": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "minutes": {"type": ["number", "null"]}},
            "required": ["text", "minutes"], "additionalProperties": False}},
        "tags": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["found", "title", "description", "servings", "prep_minutes", "cook_minutes", "ingredients", "steps",
                 "tags", "notes"],
    "additionalProperties": False,
}

READER_PROMPT = """Read the recipe in this {what} and return it as JSON.

- ingredients: one string per line, exactly as written, keeping the original quantities and units (do not convert \
cups, ounces or Fahrenheit). Sub-headings such as "For the sauce:" are their own line ending in a colon.
- steps: one per instruction, in order, in the recipe's words. minutes: the main cooking or waiting time the step \
states, if any, else null.
- servings, prep_minutes, cook_minutes: only when the recipe says them, else null.
- tags: up to five short lower-case words (cuisine, course, main ingredient).
- description: the recipe's own introduction, shortened to two sentences at most; empty if there is none.
- notes: tips or variations printed with the recipe; empty if none.
If several pages are given they are one recipe, in order. If there is no recipe, set found to false."""


async def read_with_claude(api_key: str, model: str, *, images: list[tuple[str, bytes]] | None = None,
                           text: str | None = None) -> dict:
    """Ask Claude to read a recipe from photos (mime, bytes) or a page's text. Returns draft fields."""
    import anthropic

    content: list[dict] = []
    for mime, data in images or []:
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime,
                                                     "data": base64.standard_b64encode(data).decode()}})
    what = "photo" if images and len(images) == 1 else "photos" if images else "web page text"
    if text:
        content.append({"type": "text", "text": f"<page>\n{text}\n</page>"})
    content.append({"type": "text", "text": READER_PROMPT.format(what=what)})
    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=120, max_retries=1)
    try:
        resp = await client.beta.messages.create(
            model=model or READER_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": READER_SCHEMA}},
            messages=[{"role": "user", "content": content}],
            extra_body={"fallbacks": "default"},
        )
    except anthropic.AuthenticationError:
        raise ImportError_("The Anthropic API key in Settings › Recipes was turned down. Check it or paste a new one.")
    except anthropic.PermissionDeniedError as e:
        raise ImportError_(f"Anthropic refused the request: {_api_message(e)}")
    except anthropic.RateLimitError:
        raise ImportError_("Anthropic is busy or the account's limit was reached. Try again in a minute.")
    except anthropic.BadRequestError as e:
        raise ImportError_(f"Anthropic couldn't read that: {_api_message(e)}")
    except anthropic.APIStatusError as e:
        raise ImportError_(f"Anthropic answered with error {e.status_code}. Try again in a minute.")
    except anthropic.APIConnectionError:
        raise ImportError_("Couldn't reach Anthropic from Home Assistant. Check the internet connection.")
    if resp.stop_reason == "refusal":
        raise ImportError_("Claude declined to read that. Try another photo, or type the recipe in.")
    if resp.stop_reason == "max_tokens":
        raise ImportError_("That recipe was too long to read in one go. Try fewer pages at a time.")
    raw = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    try:
        data = json.loads(raw)
    except ValueError:
        log.warning("Recipe reader returned unreadable JSON")
        raise ImportError_("Claude's answer couldn't be read. Try again.")
    if not data.get("found") or not (data.get("ingredients") or data.get("steps")):
        raise ImportError_("No recipe found there. Try a clearer photo with the ingredients and method in view.")
    return {
        "title": str(data.get("title") or "")[:120], "description": str(data.get("description") or "")[:1000],
        "servings": _servings(data.get("servings")),
        "prep_minutes": _int_or_none(data.get("prep_minutes")), "cook_minutes": _int_or_none(data.get("cook_minutes")),
        "minutes": None,
        "ingredients": [str(i).strip() for i in data.get("ingredients") or [] if str(i).strip()],
        "steps": [{"text": str(s.get("text") or "").strip(), "minutes": s.get("minutes")}
                  for s in data.get("steps") or [] if isinstance(s, dict) and str(s.get("text") or "").strip()],
        "tags": [str(t).strip().lower() for t in data.get("tags") or [] if str(t).strip()][:8],
        "notes": str(data.get("notes") or ""),
    }


def _int_or_none(v) -> int | None:
    try:
        n = int(round(float(v)))
        return n if 0 < n < 10000 else None
    except (TypeError, ValueError):
        return None


def _api_message(e) -> str:
    try:
        return e.body["error"]["message"]  # type: ignore[index]
    except Exception:
        return str(e)[:200]
