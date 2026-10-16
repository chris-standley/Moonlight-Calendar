"""Reading recipe text: ingredient lines (quantity, unit, name), cooking times in steps, metric conversions, and
whole recipes pasted or photographed as plain text. Pure functions, no database.

Quantities stay in the units they were written in; `metric` is an extra, converted figure for cups, ounces, pounds,
pints and the like (teaspoons and tablespoons are left alone, they're the same everywhere). Step text gets the
converted temperature, length or amount added in brackets ("350°F (175°C)")."""
from __future__ import annotations

import re
from fractions import Fraction

# ---------------------------------------------------------------- numbers

UNICODE_FRACTIONS = {
    "½": Fraction(1, 2), "⅓": Fraction(1, 3), "⅔": Fraction(2, 3), "¼": Fraction(1, 4), "¾": Fraction(3, 4),
    "⅕": Fraction(1, 5), "⅖": Fraction(2, 5), "⅗": Fraction(3, 5), "⅘": Fraction(4, 5), "⅙": Fraction(1, 6),
    "⅚": Fraction(5, 6), "⅛": Fraction(1, 8), "⅜": Fraction(3, 8), "⅝": Fraction(5, 8), "⅞": Fraction(7, 8),
}
_UF = "".join(UNICODE_FRACTIONS)
NUM = rf"(?:\d+\s*[{_UF}]|\d+\s+\d+\s*/\s*\d+|\d+\s*/\s*\d+|\d+(?:[.,]\d+)?|[{_UF}])"
RANGE_SEP = r"\s*(?:-|–|—|to|or)\s*"


def to_number(s: str) -> float | None:
    """'1 1/2', '1½', '1,5', '¾' -> 1.5 / 0.75 (None if unreadable)."""
    s = s.strip()
    try:
        total = Fraction(0)
        for ch, val in UNICODE_FRACTIONS.items():
            if ch in s:
                total += val
                s = s.replace(ch, " ")
        parts = s.split()
        rest = " ".join(parts)
        m = re.fullmatch(r"(?:(\d+)\s+)?(\d+)\s*/\s*(\d+)", rest)
        if m:
            if int(m.group(3)) == 0:
                return None
            total += Fraction(int(m.group(1) or 0)) + Fraction(int(m.group(2)), int(m.group(3)))
        elif rest:
            total += Fraction(rest.replace(",", "."))
        return round(float(total), 4)
    except (ValueError, ZeroDivisionError):
        return None


# ---------------------------------------------------------------- units

# canonical unit -> spellings (matched case-insensitively, longest first, as whole words)
UNIT_ALIASES: dict[str, list[str]] = {
    "g": ["g", "gr", "grs", "gram", "grams", "gramme", "grammes"],
    "kg": ["kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"],
    "mg": ["mg"],
    "ml": ["ml", "mls", "millilitre", "millilitres", "milliliter", "milliliters"],
    "cl": ["cl"],
    "dl": ["dl"],
    "l": ["l", "ltr", "litre", "litres", "liter", "liters"],
    "tsp": ["tsp", "tsps", "teaspoon", "teaspoons", "tspn"],
    "tbsp": ["tbsp", "tbsps", "tbs", "tbl", "tbls", "tablespoon", "tablespoons", "tblsp"],
    "cup": ["cup", "cups"],
    "fl oz": ["fl oz", "fl. oz", "fl.oz", "floz", "fluid ounce", "fluid ounces"],
    "oz": ["oz", "ozs", "ounce", "ounces"],
    "lb": ["lb", "lbs", "pound", "pounds"],
    "pint": ["pint", "pints", "pt", "pts"],
    "quart": ["quart", "quarts", "qt", "qts"],
    "gallon": ["gallon", "gallons", "gal"],
    "stick": ["stick", "sticks"],
    "pinch": ["pinch", "pinches"],
    "dash": ["dash", "dashes"],
    "clove": ["clove", "cloves"],
    "can": ["can", "cans"],
    "tin": ["tin", "tins"],
    "jar": ["jar", "jars"],
    "pack": ["pack", "packs", "packet", "packets"],
    "slice": ["slice", "slices"],
    "bunch": ["bunch", "bunches"],
    "handful": ["handful", "handfuls"],
    "sprig": ["sprig", "sprigs"],
    "piece": ["piece", "pieces"],
}
_ALIAS_TO_UNIT = {a: u for u, aliases in UNIT_ALIASES.items() for a in aliases}
_UNIT_RE = "|".join(re.escape(a).replace(r"\ ", r"\s*") for a in sorted(_ALIAS_TO_UNIT, key=len, reverse=True))

# Non-metric measures -> (metric unit, factor). Cups are US cups (240 ml); pints are British (568 ml).
METRIC = {
    "cup": ("ml", 240.0), "fl oz": ("ml", 29.57), "pint": ("ml", 568.0), "quart": ("ml", 946.0),
    "gallon": ("ml", 3785.0), "oz": ("g", 28.35), "lb": ("g", 453.6), "stick": ("g", 113.0),
}

INGREDIENT_RE = re.compile(
    rf"^\s*(?:[-•*·▪●]\s*)?(?P<q>{NUM})(?:{RANGE_SEP}(?P<q2>{NUM}))?\s*"
    rf"(?:\((?P<paren>[^)]{{1,40}})\)\s*)?"
    rf"(?:(?P<unit>{_UNIT_RE})\.?(?![\w]))?\s*(?:of\s+)?(?P<rest>.*)$",
    re.IGNORECASE,
)


def _canon_unit(raw: str) -> str:
    key = re.sub(r"[\s.]+", " ", raw.lower()).strip()
    if key in _ALIAS_TO_UNIT:
        return _ALIAS_TO_UNIT[key]
    return _ALIAS_TO_UNIT.get(key.replace(" ", ""), key)


def metric_of(quantity: float | None, quantity_max: float | None, unit: str) -> dict | None:
    if unit not in METRIC or quantity is None:
        return None
    to, f = METRIC[unit]
    return {"quantity": round(quantity * f, 1), "quantity_max": None if quantity_max is None else round(quantity_max * f, 1),
            "unit": to}


HEADING_RE = re.compile(r"^(?:for\s+(?:the\s+)?[\w\s,&'-]{2,40}|[\w\s,&'-]{2,40}):\s*$", re.IGNORECASE)


def parse_ingredient(text: str) -> dict:
    """One ingredient line -> {text, quantity, quantity_max, unit, name, note, heading, metric}."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    out = {"text": text, "quantity": None, "quantity_max": None, "unit": "", "name": text, "note": "",
           "heading": False, "metric": None}
    if not text:
        return out
    if HEADING_RE.match(text) and not re.match(rf"^\s*{NUM}", text):
        out["heading"] = True
        out["name"] = text.rstrip(":").strip()
        return out
    m = INGREDIENT_RE.match(text)
    rest = text
    if m:
        q = to_number(m.group("q"))
        q2 = to_number(m.group("q2")) if m.group("q2") else None
        if q is not None:
            out["quantity"] = q
            out["quantity_max"] = q2 if q2 is not None and q2 > q else None
            out["unit"] = _canon_unit(m.group("unit")) if m.group("unit") else ""
            rest = m.group("rest").strip()
            if m.group("paren"):
                out["note"] = m.group("paren").strip()
    name, _, note = rest.partition(",")
    name = name.strip()
    if note.strip():
        out["note"] = ", ".join(x for x in (out["note"], note.strip()) if x)
    out["name"] = name or rest or text
    out["metric"] = metric_of(out["quantity"], out["quantity_max"], out["unit"])
    return out


# ---------------------------------------------------------------- times in steps

_WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "sixty": 60}
_DUR_NUM = rf"(?:{NUM}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty|sixty)"
DURATION_RE = re.compile(
    rf"(?<![\w/])(?:(?P<half>half\s+an?\s+hour)|(?P<n>{_DUR_NUM})(?:{RANGE_SEP}(?P<n2>{NUM}))?\s*"
    rf"(?P<u>hours?|hrs?\b|h\b|minutes?|mins?\b|m\b|seconds?|secs?\b|s\b)"
    rf"(?:\s*(?:and\s+)?(?P<extra>{NUM})\s*(?:minutes?|mins?\b|m\b))?)",
    re.IGNORECASE,
)


def _seconds(n: str, unit: str) -> int | None:
    v = _WORD_NUM.get(n.lower().strip()) if n.strip().isalpha() else to_number(n)
    if v is None:
        return None
    u = unit.lower()
    mult = 3600 if u.startswith("h") else 60 if u.startswith("m") else 1
    return int(round(v * mult))


def fmt_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m} min" if m else f"{h} h"
    if m:
        return f"{m} min {s} s" if s else f"{m} min"
    return f"{s} s"


def find_durations(text: str) -> list[int]:
    """Cooking times mentioned in a step, in seconds ('simmer for 10-15 minutes' -> [600], the shorter end, to check)."""
    found: list[int] = []
    for m in DURATION_RE.finditer(text or ""):
        if m.group("half"):
            secs = 1800
        else:
            n, u = m.group("n"), m.group("u")
            # Bare 'm'/'s'/'h' only straight after a number ("10m"), never "2 s" read from "2 slices".
            if len(u) == 1 and m.group(0)[len(n):len(n) + 1].isspace():
                continue
            secs = _seconds(n, u)
            if secs is None:
                continue
            if m.group("extra") and u.lower().startswith("h"):
                extra = to_number(m.group("extra"))
                secs += int(round((extra or 0) * 60))
        if 5 <= secs <= 24 * 3600 and secs not in found:
            found.append(secs)
    return found


def step_timers(text: str, minutes: float | None) -> list[dict]:
    secs = find_durations(text)
    if minutes:
        own = int(round(minutes * 60))
        if own not in secs:
            secs.insert(0, own)
    return [{"seconds": s, "label": fmt_duration(s)} for s in secs]


# ---------------------------------------------------------------- metric notes in step text

def _nice(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}".rstrip("0").rstrip(".")


def round_metric(v: float, unit: str) -> tuple[float, str]:
    """Kitchen-friendly rounding: 7.5 g, 45 g, 225 g, 1.2 kg."""
    if unit in ("g", "ml") and v >= 1000:
        return round(v / 1000, 2 if v < 10000 else 1), "kg" if unit == "g" else "l"
    if v < 10:
        return round(v * 2) / 2, unit
    if v < 100:
        return float(round(v)), unit
    return float(round(v / 5) * 5), unit


TEMP_RE = re.compile(r"(?P<n>\d{2,3})\s*(?:°|º|˚|degrees?\s*)\s*F(?:ahrenheit)?\b|(?P<n2>\d{3})\s*F\b")
INCH_RE = re.compile(r"(?P<a>\d+(?:\.\d+)?)(?:\s*[x×]\s*(?P<b>\d+(?:\.\d+)?))?(?:\s*-\s*|\s*)(?:inch(?:es)?\b|in\.(?!\w)|″|\")")
AMOUNT_RE = re.compile(rf"(?P<q>{NUM})\s*(?P<u>cups?|fl\.?\s*oz|fluid\s+ounces?|oz|ounces?|lbs?|pounds?|pints?|quarts?)\b(?!\s*\()",
                       re.IGNORECASE)


def metric_note(text: str) -> str | None:
    """`text` with metric figures added in brackets, or None when nothing needed converting."""
    changed = False

    def temp(m: re.Match) -> str:
        nonlocal changed
        f = int(m.group("n") or m.group("n2"))
        if not 150 <= f <= 550:
            return m.group(0)
        changed = True
        return f"{m.group(0)} ({int(round((f - 32) * 5 / 9 / 5) * 5)}°C)"

    def inch(m: re.Match) -> str:
        nonlocal changed
        a, b = float(m.group("a")), m.group("b")
        if a > 40:
            return m.group(0)
        changed = True
        cm = lambda x: _nice(round(x * 2.54 * 2) / 2)  # noqa: E731
        return f"{m.group(0)} ({cm(a)} x {cm(float(b))} cm)" if b else f"{m.group(0)} ({cm(a)} cm)"

    def amount(m: re.Match) -> str:
        nonlocal changed
        q = to_number(m.group("q"))
        met = metric_of(q, None, _canon_unit(m.group("u")))
        if not met:
            return m.group(0)
        changed = True
        v, u = round_metric(met["quantity"], met["unit"])
        return f"{m.group(0)} ({_nice(v)} {u})"

    out = TEMP_RE.sub(temp, text or "")
    out = INCH_RE.sub(inch, out)
    out = AMOUNT_RE.sub(amount, out)
    return out if changed else None


# ---------------------------------------------------------------- whole recipes from plain text

ING_HEAD = re.compile(r"^\s*(ingredients?|you(?:'ll)? need|what you need|shopping list)\s*:?\s*$", re.IGNORECASE)
STEP_HEAD = re.compile(r"^\s*(method|directions?|instructions?|preparation|steps?|how to make(?: it)?|to make)\s*:?\s*$",
                       re.IGNORECASE)
NOTES_HEAD = re.compile(r"^\s*(notes?|tips?|cook'?s notes?)\s*:?\s*$", re.IGNORECASE)
SERVES_RE = re.compile(r"\b(?:serves|servings|portions|makes|yield|feeds)\s*:?\s*(?:about\s+)?(\d+)", re.IGNORECASE)
TIME_LINE_RE = re.compile(r"\b(prep(?:aration)?|cook(?:ing)?|total|ready in)(?:\s*time)?\s*:?\s*(.+)", re.IGNORECASE)
STEP_NUM_RE = re.compile(r"^\s*(?:step\s*)?(\d{1,2})\s*[.):]?\s+(?=\S)", re.IGNORECASE)


def minutes_in(text: str) -> int | None:
    secs = find_durations(text)
    if not secs:
        return None
    # "1 hour 20 minutes" is one duration; "Prep 10 mins Cook 20 mins" was split into lines before this.
    return int(round(secs[0] / 60)) or None


def _looks_like_ingredient(line: str) -> bool:
    return bool(re.match(rf"^\s*(?:[-•*·▪●]\s*)?{NUM}", line)) and len(line) < 90


def parse_text(text: str) -> dict:
    """A recipe typed, pasted or read from a photo -> draft fields {title, description, servings, prep_minutes,
    cook_minutes, minutes, ingredients: [str], steps: [{text, minutes}], notes}. Best effort: everything stays editable."""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in (text or "").replace("\r", "\n").split("\n")]
    out: dict = {"title": "", "description": "", "servings": None, "prep_minutes": None, "cook_minutes": None,
                 "minutes": None, "ingredients": [], "steps": [], "notes": ""}
    section = "intro"
    intro: list[str] = []
    ings: list[str] = []
    step_lines: list[tuple[str, bool]] = []  # (text, starts a new step)
    notes: list[str] = []
    blank_before = False
    for ln in lines:
        if not ln:
            blank_before = True
            continue
        if ING_HEAD.match(ln):
            section = "ingredients"
        elif STEP_HEAD.match(ln):
            section = "steps"
        elif NOTES_HEAD.match(ln) and section == "steps":
            section = "notes"
        else:
            meta = False
            if section in ("intro", "ingredients"):
                if (sv := SERVES_RE.search(ln)) and len(ln) < 60:
                    out["servings"] = out["servings"] or int(sv.group(1))
                    meta = True
                for part in re.split(r"(?=\b(?:prep|cook|total)\b)", ln, flags=re.IGNORECASE):
                    tm = TIME_LINE_RE.search(part)
                    if tm and len(ln) < 80 and (mins := minutes_in(tm.group(2))):
                        key = tm.group(1).lower()
                        field = "prep_minutes" if key.startswith("prep") else "cook_minutes" if key.startswith("cook") else "minutes"
                        out[field] = out[field] or mins
                        meta = True
            if not meta:
                if section == "intro":
                    if not out["title"]:
                        out["title"] = ln[:120]
                    elif _looks_like_ingredient(ln) and not ings:
                        section = "ingredients"
                        ings.append(ln)
                    else:
                        intro.append(ln)
                elif section == "ingredients":
                    # A wrapped line carries on the one before ("...finely" / "chopped").
                    if ings and not _looks_like_ingredient(ln) and (ln[:1].islower() or ings[-1].endswith((",", "-", "and", "or"))):
                        ings[-1] += " " + ln
                    elif len(ln) > 110 and not _looks_like_ingredient(ln):
                        section = "steps"
                        step_lines.append((ln, True))
                    else:
                        ings.append(ln)
                elif section == "steps":
                    step_lines.append((ln, bool(STEP_NUM_RE.match(ln)) or blank_before))
                else:
                    notes.append(ln)
        blank_before = False
    # No "Method" heading: long sentences at the end of the ingredients are the steps.
    if not step_lines and ings:
        while ings and len(ings[-1]) > 70 and not _looks_like_ingredient(ings[-1]):
            step_lines.insert(0, (ings.pop(), True))
    # Numbered steps: lines only start a new step at a number (OCR wraps every line).
    numbered = any(STEP_NUM_RE.match(t) for t, _ in step_lines)
    steps: list[str] = []
    for t, new in step_lines:
        starts = bool(STEP_NUM_RE.match(t)) if numbered else (new or (steps and steps[-1].endswith((".", "!", ")"))))
        t = STEP_NUM_RE.sub("", t, count=1) if numbered else t
        if starts or not steps:
            steps.append(t)
        else:
            steps[-1] += " " + t
    out["description"] = " ".join(intro)[:1000]
    out["ingredients"] = [i.lstrip("-•*·▪● ").strip() for i in ings if i.strip()]
    out["steps"] = [{"text": s.strip(), "minutes": None} for s in steps if s.strip()]
    out["notes"] = "\n".join(notes)
    return out


ISO_DURATION_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$", re.I)


def iso_minutes(value) -> int | None:
    """schema.org durations: PT1H30M -> 90."""
    if not isinstance(value, str):
        return None
    m = ISO_DURATION_RE.match(value.strip())
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (float(x) if x else 0 for x in m.groups())
    total = int(round(d * 1440 + h * 60 + mi + s / 60))
    return total or None
