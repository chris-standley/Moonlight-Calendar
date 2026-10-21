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
ATTR_TITLE = "title"
ATTR_EMOJI = "emoji"
ATTR_POINTS = "points"
ATTR_TIME_OF_DAY = "time_of_day"
ATTR_SCREENS = "screens"
ATTR_STYLE = "style"
ATTR_MESSAGE = "message"
ATTR_ICON = "icon"
ATTR_IMAGE = "image"
ATTR_DURATION = "duration"
ATTR_DISMISSIBLE = "dismissible"
ATTR_CHIME = "chime"
ATTR_ID = "id"
ATTR_LABEL = "label"
ATTR_DESCRIPTION = "description"
ATTR_UNTIL = "until"
ATTR_FINISHED_FOR = "finished_for"

SERVICE_COMPLETE_CHORE = "complete_chore"
SERVICE_AWARD_STARS = "award_stars"
SERVICE_ADD_LIST_ITEM = "add_list_item"
SERVICE_ADD_CHORE = "add_chore"
SERVICE_SHOW_NOTIFICATION = "show_notification"
SERVICE_START_TIMER = "start_timer"
SERVICE_CLEAR_NOTIFICATIONS = "clear_notifications"

EVENT_ALERT = "moonlight_alert"  # a timer reached zero, or a notification was dismissed on a screen
