"""Free/busy status of a VEVENT (used by ICS subscriptions, see ics_feed.py)."""
from __future__ import annotations

# Placeholder summaries that free/busy-only publishing uses instead of titles (lower-case).
PLACEHOLDERS = {
    "busy": "busy", "tentative": "tentative", "free": "free",
    "away": "away", "out of office": "away", "oof": "away", "out of the office": "away",
    "working elsewhere": "elsewhere",
}
CDO_STATUS = {"BUSY": "busy", "TENTATIVE": "tentative", "OOF": "away", "FREE": "free",
              "WORKINGELSEWHERE": "elsewhere"}


def busy_status(comp) -> str:
    """busy | tentative | away | elsewhere | free for one VEVENT."""
    cdo = str(comp.get("X-MICROSOFT-CDO-BUSYSTATUS", "")).strip().upper()
    if cdo in CDO_STATUS:
        return CDO_STATUS[cdo]
    summary = str(comp.get("SUMMARY", "")).strip().lower()
    if summary in PLACEHOLDERS:
        return PLACEHOLDERS[summary]
    if str(comp.get("STATUS", "")).strip().upper() == "TENTATIVE":
        return "tentative"
    if str(comp.get("TRANSP", "")).strip().upper() == "TRANSPARENT":
        return "free"
    return "busy"


def is_placeholder(comp) -> bool:
    return str(comp.get("SUMMARY", "")).strip().lower() in PLACEHOLDERS
