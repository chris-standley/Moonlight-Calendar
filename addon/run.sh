#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

if bashio::config.true 'demo'; then
    export MOONLIGHT_DEMO=1
else
    export MOONLIGHT_DEMO=0
fi

# Weather from an HA weather entity (e.g. weather.home) via the Supervisor API; empty = demo forecast.
# homeassistant_api: true in config.yaml provides SUPERVISOR_TOKEN for http://supervisor/core/api.
export MOONLIGHT_WEATHER_ENTITY=""
if bashio::config.has_value 'weather_entity'; then
    MOONLIGHT_WEATHER_ENTITY="$(bashio::config 'weather_entity')"
fi
export MOONLIGHT_WEATHER_ENTITY

# Wall screens on the LAN port must be paired (Settings > Screens); HA ingress is always allowed.
if bashio::config.false 'require_pairing'; then
    export MOONLIGHT_AUTH=off
else
    export MOONLIGHT_AUTH=on
fi

# Home Assistant's timezone (Settings > System > General): the container clock and the default household
# timezone (Moonlight Settings can still override it). The Supervisor usually sets TZ already; fall back to it.
ha_tz="$(bashio::info.timezone 2>/dev/null || true)"
if [ -z "${ha_tz}" ] || [ "${ha_tz}" = "null" ]; then
    ha_tz="${TZ:-}"
fi
if [ -n "${ha_tz}" ] && [ -f "/usr/share/zoneinfo/${ha_tz}" ]; then
    export TZ="${ha_tz}"
    export MOONLIGHT_TIMEZONE="${ha_tz}"
else
    bashio::log.warning "Could not read Home Assistant's timezone (got '${ha_tz}'); using UTC for the clock and Europe/London for the calendar"
fi

export MOONLIGHT_DB="${MOONLIGHT_DB:-/data/moonlight.db}"
export MOONLIGHT_DATA="${MOONLIGHT_DATA:-/data}"
bashio::log.info "Starting Moonlight on port ${MOONLIGHT_PORT:-8099} (db: ${MOONLIGHT_DB}, demo: ${MOONLIGHT_DEMO}, weather: ${MOONLIGHT_WEATHER_ENTITY:-demo}, pairing: ${MOONLIGHT_AUTH}, timezone: ${MOONLIGHT_TIMEZONE:-default})"

cd /app/backend
exec python3 -m moonlight
