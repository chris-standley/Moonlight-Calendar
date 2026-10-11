"""Moonlight integration inside a real (test) Home Assistant, against a real Moonlight backend."""
from __future__ import annotations

import asyncio
import json
import urllib.request
from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

DOMAIN = "moonlight"


def http(port: int, method: str, path: str, body=None, headers: dict | None = None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


async def setup(hass: HomeAssistant, port: int) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Moonlight", data={CONF_HOST: "127.0.0.1", CONF_PORT: port})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_config_flow(hass: HomeAssistant, moonlight_server) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["errors"] == {}
    # Nothing listening on port 1
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: 1})
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "cannot_connect"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: moonlight_server})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "127.0.0.1", CONF_PORT: moonlight_server}
    await hass.async_block_till_done()
    # Same host/port again -> aborted
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: moonlight_server})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    for entry in hass.config_entries.async_entries(DOMAIN):
        await unload(hass, entry)


INGRESS = {"X-Ingress-Path": "/api/hassio_ingress/test"}  # see the moonlight_server_pairing fixture
PIN = "1234"  # the demo household's PIN (seed/demo.json)


def approve(port: int, code: str) -> dict:
    return http(port, "POST", "/api/displays/approve", {"code": code, "pin": PIN}, INGRESS)


def service_token(port: int) -> str:
    """A Home Assistant token as the add-on makes one for discovery (here: paired as a service)."""
    start = http(port, "POST", "/api/pair/start", {"layout": "service", "name": "Home Assistant"})
    approve(port, start["code"])
    return http(port, "GET", f"/api/pair/{start['pair_id']}")["token"]


async def test_discovered_from_the_add_on(hass: HomeAssistant, moonlight_server_pairing) -> None:
    from homeassistant.helpers.service_info.hassio import HassioServiceInfo

    port = moonlight_server_pairing
    token = service_token(port)
    info = HassioServiceInfo(config={"host": "127.0.0.1", "port": port, "token": token, "addon": "Moonlight"},
                             name="Moonlight", slug="abc12345_moonlight", uuid="u1")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_HASSIO},
                                                       data=info)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "hassio_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["data"]["token"] == token
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED and entry.unique_id == "addon_abc12345_moonlight"

    # A new announcement (new token after the connection was removed in Moonlight) updates the entry.
    token2 = service_token(port)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO},
        data=HassioServiceInfo(config={**info.config, "token": token2}, name="Moonlight", slug=info.slug, uuid="u2"))
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert entry.data["token"] == token2
    await hass.async_block_till_done()
    await unload(hass, entry)


async def test_discovery_adopts_a_manual_entry(hass: HomeAssistant, moonlight_server) -> None:
    from homeassistant.helpers.service_info.hassio import HassioServiceInfo

    port = moonlight_server
    entry = await setup(hass, port)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO},
        data=HassioServiceInfo(config={"host": "127.0.0.1", "port": port, "token": "mlt_x"}, name="Moonlight",
                               slug="abc_moonlight", uuid="u1"))
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert entry.unique_id == "addon_abc_moonlight" and entry.data["token"] == "mlt_x"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    await hass.async_block_till_done()
    await unload(hass, entry)


async def test_config_flow_pairing(hass: HomeAssistant, moonlight_server_pairing) -> None:
    port = moonlight_server_pairing
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: port})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "pair"
    code = result["description_placeholders"]["code"]
    assert len(code.replace(" ", "")) == 6
    # Submitting before the code is entered in Moonlight keeps the same code.
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "pair" and result["errors"] == {"base": "not_paired"}
    assert result["description_placeholders"]["code"] == code
    d = approve(port, code)
    assert d["name"] == "Home Assistant" and d["layout"] == "service"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    token = result["data"]["token"]
    assert token.startswith("mlt_")
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED
    assert any(s.entity_id.startswith("sensor.moonlight_") for s in hass.states.async_all("sensor"))
    coordinator = entry.runtime_data
    for _ in range(50):
        if coordinator.ws_connected:
            break
        await asyncio.sleep(0.1)
    assert coordinator.ws_connected  # the WebSocket sends the token too

    # Revoking Home Assistant in Moonlight -> 401 -> reauth flow -> pair again.
    http(port, "DELETE", f"/api/displays/{d['id']}", {"pin": PIN}, INGRESS)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [config_entries.SOURCE_REAUTH]
    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {})
    assert result["step_id"] == "pair"
    approve(port, result["description_placeholders"]["code"])
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data["token"] != token and entry.state is ConfigEntryState.LOADED
    await unload(hass, entry)


async def test_entities(hass: HomeAssistant, moonlight_server) -> None:
    entry = await setup(hass, moonlight_server)
    ent_reg = er.async_get(hass)
    ids = sorted(e.entity_id for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id))
    assert "sensor.moonlight_mia_stars" in ids and "sensor.moonlight_leo_stars" in ids
    assert "sensor.moonlight_alex_stars" not in ids                       # adults have no stars sensor
    assert "sensor.moonlight_alex_chores_left" in ids
    assert "binary_sensor.moonlight_mia_all_chores_done" in ids
    assert "sensor.moonlight_tonight_s_dinner" in ids and "sensor.moonlight_next_event" in ids
    assert "todo.moonlight_groceries" in ids and "calendar.moonlight_mia" in ids

    summary = http(moonlight_server, "GET", "/api/summary")
    mia = next(p for p in summary["people"] if p["id"] == "p_mia")
    stars = hass.states.get("sensor.moonlight_mia_stars")
    assert int(stars.state) == mia["balance"] and stars.attributes["unit_of_measurement"] == "stars"
    assert stars.attributes["state_class"] == "measurement"
    left = hass.states.get("sensor.moonlight_mia_chores_left")
    assert int(left.state) == mia["chores_left"]
    assert left.attributes["remaining"] == [c["title"] for c in mia["chores"] if not c["completed"]]
    done = hass.states.get("binary_sensor.moonlight_mia_all_chores_done")
    assert done.state == ("on" if mia["all_done"] else "off")
    dinner = hass.states.get("sensor.moonlight_tonight_s_dinner").state
    assert dinner == (summary["dinner"]["title"] if summary["dinner"] else "Nothing planned")
    groceries = hass.states.get("todo.moonlight_groceries")
    lists = http(moonlight_server, "GET", "/api/lists")
    assert int(groceries.state) == next(l for l in lists if l["name"] == "Groceries")["open_count"]
    await unload(hass, entry)


async def test_websocket_push_refresh(hass: HomeAssistant, moonlight_server) -> None:
    """A change made in Moonlight (not via HA) shows up without waiting for the 60 s poll."""
    entry = await setup(hass, moonlight_server)
    for _ in range(50):  # wait for the WebSocket listener to connect
        if entry.runtime_data.ws_connected:
            break
        await asyncio.sleep(0.1)
    assert entry.runtime_data.ws_connected
    before = int(hass.states.get("sensor.moonlight_leo_stars").state)
    await hass.async_add_executor_job(http, moonlight_server, "POST", "/api/points/adjust",
                                      {"person_id": "p_leo", "change": 7, "reason": "test", "pin": "1234"})
    for _ in range(50):
        await asyncio.sleep(0.1)
        await hass.async_block_till_done()
        if int(hass.states.get("sensor.moonlight_leo_stars").state) == before + 7:
            break
    assert int(hass.states.get("sensor.moonlight_leo_stars").state) == before + 7
    await unload(hass, entry)


async def test_services(hass: HomeAssistant, moonlight_server) -> None:
    entry = await setup(hass, moonlight_server)
    today = dt_util.now().date().isoformat()
    chores = await hass.async_add_executor_job(http, moonlight_server, "GET", f"/api/chores?date={today}")
    pending = next(c for c in chores if c["person_id"] == "p_mia" and not c["completed"])

    resp = await hass.services.async_call(DOMAIN, "complete_chore", {"person": "mia", "chore": pending["title"]},
                                          blocking=True, return_response=True)
    assert resp["person"] == "Mia" and resp["chore"] == pending["title"] and resp["date"] == today
    chores = await hass.async_add_executor_job(http, moonlight_server, "GET", f"/api/chores?date={today}")
    assert any(c["id"] == pending["id"] or (c["title"] == pending["title"] and c["completed"]) for c in chores)

    before = (await hass.async_add_executor_job(http, moonlight_server, "GET", "/api/points"))
    leo_before = next(b["balance"] for b in before if b["person_id"] == "p_leo")
    resp = await hass.services.async_call(DOMAIN, "award_stars",
                                          {"person": "Leo", "stars": 3, "reason": "Tidied up", "pin": "1234"},
                                          blocking=True, return_response=True)
    assert resp["balance"] == leo_before + 3
    with pytest.raises(ServiceValidationError, match="PIN"):
        await hass.services.async_call(DOMAIN, "award_stars", {"person": "Leo", "stars": 3, "pin": "0000"},
                                       blocking=True)
    with pytest.raises(ServiceValidationError, match="No person"):
        await hass.services.async_call(DOMAIN, "award_stars", {"person": "Nobody", "stars": 1, "pin": "1234"},
                                       blocking=True)

    await hass.services.async_call(DOMAIN, "add_list_item", {"list": "groceries", "item": "Bananas"}, blocking=True)
    await hass.async_block_till_done()
    lists = await hass.async_add_executor_job(http, moonlight_server, "GET", "/api/lists")
    gid = next(l["id"] for l in lists if l["name"] == "Groceries")
    items = await hass.async_add_executor_job(http, moonlight_server, "GET", f"/api/lists/{gid}/items")
    assert any(i["title"] == "Bananas" for i in items)

    # add_chore: a one-off chore for today; firing twice adds it once.
    call = {"person": ["Mia", "leo"], "title": "Empty the dishwasher", "emoji": "🍽️", "points": 2,
            "time_of_day": "evening"}
    resp = await hass.services.async_call(DOMAIN, "add_chore", call, blocking=True, return_response=True)
    assert resp["date"] == today and sorted(a["person"] for a in resp["added"]) == ["Leo", "Mia"]
    resp = await hass.services.async_call(DOMAIN, "add_chore", {**call, "title": "empty the DISHWASHER"},
                                          blocking=True, return_response=True)
    assert resp["added"] == [] and len(resp["already_there"]) == 2
    chores = await hass.async_add_executor_job(http, moonlight_server, "GET", f"/api/chores?date={today}")
    new = [c for c in chores if c["title"] == "Empty the dishwasher"]
    assert len(new) == 2 and all(c["schedule"] == {"type": "once", "date": today} and c["points"] == 2
                                 and c["time_of_day"] == "evening" for c in new)
    with pytest.raises(ServiceValidationError, match="No person"):
        await hass.services.async_call(DOMAIN, "add_chore", {"person": "Nobody", "title": "x"}, blocking=True)
    await unload(hass, entry)


async def test_todo_entity(hass: HomeAssistant, moonlight_server) -> None:
    entry = await setup(hass, moonlight_server)
    eid = "todo.moonlight_groceries"
    await hass.services.async_call("todo", "add_item", {"item": "Oat milk", "due_date": "2026-12-01"},
                                   target={"entity_id": eid}, blocking=True)
    got = await hass.services.async_call("todo", "get_items", {}, target={"entity_id": eid},
                                         blocking=True, return_response=True)
    item = next(i for i in got[eid]["items"] if i["summary"] == "Oat milk")
    assert item["due"] == "2026-12-01" and item["status"] == "needs_action"

    await hass.services.async_call("todo", "update_item", {"item": "Oat milk", "rename": "Soy milk",
                                                           "status": "completed"},
                                   target={"entity_id": eid}, blocking=True)
    got = await hass.services.async_call("todo", "get_items", {}, target={"entity_id": eid},
                                         blocking=True, return_response=True)
    item = next(i for i in got[eid]["items"] if i["uid"] == item["uid"])
    assert item["summary"] == "Soy milk" and item["status"] == "completed"

    await hass.services.async_call("todo", "remove_item", {"item": "Soy milk"}, target={"entity_id": eid},
                                   blocking=True)
    got = await hass.services.async_call("todo", "get_items", {}, target={"entity_id": eid},
                                         blocking=True, return_response=True)
    assert all(i["uid"] != item["uid"] for i in got[eid]["items"])
    await unload(hass, entry)


async def test_calendar_entity(hass: HomeAssistant, moonlight_server) -> None:
    entry = await setup(hass, moonlight_server)
    start = dt_util.start_of_local_day()
    end = start + timedelta(days=14)
    got = await hass.services.async_call("calendar", "get_events",
                                         {"start_date_time": start.isoformat(), "end_date_time": end.isoformat()},
                                         target={"entity_id": ["calendar.moonlight_mia", "calendar.moonlight_alex"]},
                                         blocking=True, return_response=True)
    raw = await hass.async_add_executor_job(
        http, moonlight_server, "GET",
        f"/api/events?start={start.date().isoformat()}&end={end.date().isoformat()}")
    want_mia = sorted(o["title"] for o in raw if "p_mia" in o["person_ids"])
    assert sorted(e["summary"] for e in got["calendar.moonlight_mia"]["events"]) == want_mia
    assert want_mia, "demo data should give Mia some events"
    state = hass.states.get("calendar.moonlight_mia")
    assert state.state in ("on", "off")
    await unload(hass, entry)
