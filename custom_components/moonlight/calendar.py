"""A calendar entity per person, backed by Moonlight's /api/events."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import MoonlightError
from .coordinator import MoonlightConfigEntry, MoonlightCoordinator
from .entity import MoonlightPersonEntity, add_entities_as_they_appear
from .model import Event, Summary, event_times, events_for_person, query_range

PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: MoonlightConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data

    def build(data: Summary):
        for p in data.people:
            yield f"{p.id}_calendar", lambda p=p: PersonCalendar(coordinator, p)

    add_entities_as_they_appear(coordinator, async_add_entities, build)


def to_calendar_event(ev: Event, people: list[str]) -> CalendarEvent:
    # Moonlight stores household-local times; HA's configured time zone is assumed to be the household's.
    start, end = event_times(ev, dt_util.get_default_time_zone())
    description = "\n".join(x for x in (ev.notes, ("With " + ", ".join(people)) if people else "") if x)
    return CalendarEvent(
        start=start,
        end=end,
        summary=ev.title,
        description=description or None,
        location=ev.location or None,
        uid=ev.id,
        recurrence_id=ev.occurrence_id if ev.recurring else None,
    )


class PersonCalendar(MoonlightPersonEntity, CalendarEntity):
    def __init__(self, coordinator: MoonlightCoordinator, person) -> None:
        super().__init__(coordinator, person, "calendar")

    @property
    def event(self) -> CalendarEvent | None:
        p = self.person
        if p is None or p.event is None:
            return None
        return to_calendar_event(p.event, self.coordinator.data.names(p.event.person_ids))

    async def async_get_events(self, hass: HomeAssistant, start_date: datetime,
                               end_date: datetime) -> list[CalendarEvent]:
        tz = dt_util.get_default_time_zone()
        start, end = query_range(start_date, end_date, tz)
        try:
            raw = await self.coordinator.client.events(start, end)
        except MoonlightError as err:
            raise HomeAssistantError(f"Couldn't read Moonlight events: {err}") from err
        data = self.coordinator.data
        return [to_calendar_event(ev, data.names(ev.person_ids) if data else [])
                for ev in events_for_person(raw, self.person_id, start_date, end_date, tz)]
