#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

if bashio::config.true 'demo'; then
    export MOONLIGHT_DEMO=1
else
    export MOONLIGHT_DEMO=0
fi

# Weather and speakers are chosen in Moonlight (Settings > Display > Weather, Settings > Music).
# homeassistant_api: true in config.yaml provides SUPERVISOR_TOKEN for http://supervisor/core/api.

# Wall screens on the LAN port must be paired (Settings > Screens); HA ingress is always allowed.
if bashio::config.false 'require_pairing'; then
    export MOONLIGHT_AUTH=off
else
    export MOONLIGHT_AUTH=on
fi

# HTTPS for the internet on port 8443 (map a host port for it under Network), with a certificate from /ssl,
# e.g. the Let's Encrypt app's fullchain.pem / privkey.pem. Pairing is always required on that port.
export MOONLIGHT_SSL_CERT=""
export MOONLIGHT_SSL_KEY=""
if bashio::config.true 'ssl'; then
    cert="/ssl/$(bashio::config 'certfile')"
    key="/ssl/$(bashio::config 'keyfile')"
    if [ -f "${cert}" ] && [ -f "${key}" ]; then
        MOONLIGHT_SSL_CERT="${cert}"
        MOONLIGHT_SSL_KEY="${key}"
    else
        bashio::log.error "HTTPS is on but ${cert} or ${key} is missing; serving the home network only. Check the certfile and keyfile options."
    fi
fi
export MOONLIGHT_SSL_CERT MOONLIGHT_SSL_KEY
https_state="off"
if [ -n "${MOONLIGHT_SSL_CERT}" ]; then
    https_state="port 8443"
fi

# Moonlight's public address (shown to the apps) and Home Assistant's (for "Sign in with Home Assistant").
export MOONLIGHT_EXTERNAL_URL=""
if bashio::config.has_value 'external_url'; then
    MOONLIGHT_EXTERNAL_URL="$(bashio::config 'external_url')"
fi
export MOONLIGHT_HA_LOGIN_URL=""
if bashio::config.has_value 'homeassistant_url'; then
    MOONLIGHT_HA_LOGIN_URL="$(bashio::config 'homeassistant_url')"
fi
export MOONLIGHT_EXTERNAL_URL MOONLIGHT_HA_LOGIN_URL

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
bashio::log.info "Starting Moonlight on port ${MOONLIGHT_PORT:-8091} (db: ${MOONLIGHT_DB}, demo: ${MOONLIGHT_DEMO}, pairing: ${MOONLIGHT_AUTH}, https: ${https_state}, timezone: ${MOONLIGHT_TIMEZONE:-default})"

cd /app/backend
exec python3 -m moonlight
