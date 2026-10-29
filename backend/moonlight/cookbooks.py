"""Cookbooks found by the barcode on the back: the ISBN is looked up in Open Library (then Google Books) for the
title, author, publisher, year and cover, so a cookbook scan can file every recipe under that book."""
from __future__ import annotations

import json
import logging
import re

from . import recipe_import

log = logging.getLogger(__name__)

OPEN_LIBRARY = "https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
GOOGLE_BOOKS = "https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
MAX_ANSWER_BYTES = 1_000_000


def isbn13(value: str) -> str | None:
    """The ISBN-13 for a barcode or typed ISBN (10 or 13 digits, dashes and spaces allowed), or None if the check
    digit is wrong. Book barcodes are EAN-13 numbers starting 978 or 979. Ported to frontend/src/recipes/barcode.ts:
    change both together."""
    s = re.sub(r"[\s-]", "", value or "").upper()
    if re.fullmatch(r"\d{9}[\dX]", s):
        if sum((10 - i) * (10 if ch == "X" else int(ch)) for i, ch in enumerate(s)) % 11:
            return None
        s = "978" + s[:9]
        return s + str((10 - sum(int(ch) * (3 if i % 2 else 1) for i, ch in enumerate(s)) % 10) % 10)
    if re.fullmatch(r"97[89]\d{10}", s):
        if sum(int(ch) * (3 if i % 2 else 1) for i, ch in enumerate(s)) % 10:
            return None
        return s
    return None


def _year(text) -> int | None:
    m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", str(text or ""))
    return int(m.group(1)) if m else None


def _title(title, subtitle) -> str:
    title, subtitle = str(title or "").strip(), str(subtitle or "").strip()
    return f"{title}: {subtitle}" if title and subtitle else title


async def _json(url: str):
    data, _ = await recipe_import.fetch(url, MAX_ANSWER_BYTES)
    return json.loads(data)


async def _open_library(isbn: str) -> dict | None:
    book = (await _json(OPEN_LIBRARY.format(isbn=isbn))).get(f"ISBN:{isbn}")
    if not isinstance(book, dict) or not book.get("title"):
        return None
    cover = book.get("cover") or {}
    return {
        "title": _title(book.get("title"), book.get("subtitle")),
        "authors": ", ".join(a["name"] for a in book.get("authors") or [] if isinstance(a, dict) and a.get("name")),
        "publisher": next((p["name"] for p in book.get("publishers") or [] if isinstance(p, dict) and p.get("name")), ""),
        "year": _year(book.get("publish_date")),
        "cover_url": cover.get("large") or cover.get("medium"),
    }


async def _google_books(isbn: str) -> dict | None:
    items = (await _json(GOOGLE_BOOKS.format(isbn=isbn))).get("items") or []
    info = items[0].get("volumeInfo") if items and isinstance(items[0], dict) else None
    if not isinstance(info, dict) or not info.get("title"):
        return None
    pics = info.get("imageLinks") or {}
    cover = pics.get("thumbnail") or pics.get("smallThumbnail")
    return {
        "title": _title(info.get("title"), info.get("subtitle")),
        "authors": ", ".join(a for a in info.get("authors") or [] if isinstance(a, str)),
        "publisher": str(info.get("publisher") or ""),
        "year": _year(info.get("publishedDate")),
        "cover_url": cover.replace("http://", "https://", 1) if isinstance(cover, str) else None,
    }


async def lookup(isbn: str) -> dict | None:
    """{title, authors, publisher, year, cover_url} for an ISBN-13, or None when neither service knows the book."""
    for source in (_open_library, _google_books):
        try:
            found = await source(isbn)
        except (recipe_import.ImportError_, ValueError, AttributeError, TypeError) as e:
            log.info("Looking up ISBN %s in %s failed: %s", isbn, source.__name__, e)
            continue
        if found:
            found["title"] = found["title"][:200]
            found["authors"] = found["authors"][:200]
            found["publisher"] = found["publisher"][:200]
            return found
    return None
