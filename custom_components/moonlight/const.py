"""Constants for the Moonlight integration."""
from __future__ import annotations

import logging
from datetime import timedelta

DOMAIN = "moonlight"
LOGGER = logging.getLogger(__package__)

DEFAULT_PORT = 8091
DEFAULT_HOST = "local-moonlight"
CONF_TOKEN = "token"  # Moonlight display token from pairing (absent when Moonlight doesn't require pairing)
SCAN_INTERVAL = timedelta(seconds=60)
MANUFACTURER = "Moonlight"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_PERSON = "person"
ATTR_CHORE = "chore"
ATTR_DATE = "date"
ATTR_STARS = "stars"
ATTR_REASON = "reason"
ATTR_PIN = "pin"
ATTR_LIST = "list"
ATTR_ITEM = "item"
ATTR_DUE = "due"

SERVICE_COMPLETE_CHORE = "complete_chore"
SERVICE_AWARD_STARS = "award_stars"
SERVICE_ADD_LIST_ITEM = "add_list_item"
