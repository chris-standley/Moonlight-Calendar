"""Sensors: stars per child, chores left/done per person, tonight's dinner, next event."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MoonlightConfigEntry, MoonlightCoordinator
from .entity import MoonlightEntity, MoonlightPersonEntity, add_entities_as_they_appear
from .model import Summary, chores_attributes, dinner_state, event_attributes

PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: MoonlightConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    async_add_entities([DinnerSensor(coordinator), NextEventSensor(coordinator)])

    def build(data: Summary):
        for p in data.people:
            if p.is_child:
                yield f"{p.id}_stars", lambda p=p: StarsSensor(coordinator, p)
            yield f"{p.id}_chores_left", lambda p=p: ChoresLeftSensor(coordinator, p)
            yield f"{p.id}_chores_done", lambda p=p: ChoresDoneSensor(coordinator, p)

    add_entities_as_they_appear(coordinator, async_add_entities, build)


class StarsSensor(MoonlightPersonEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "stars"

    def __init__(self, coordinator: MoonlightCoordinator, person) -> None:
        super().__init__(coordinator, person, "stars")

    @property
    def native_value(self) -> int | None:
        p = self.person
        return p.balance if p else None


class ChoresLeftSensor(MoonlightPersonEntity, SensorEntity):
    _attr_native_unit_of_measurement = "chores"

    def __init__(self, coordinator: MoonlightCoordinator, person) -> None:
        super().__init__(coordinator, person, "chores_left")

    @property
    def native_value(self) -> int | None:
        p = self.person
        return p.chores_left if p else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self.person
        return chores_attributes(p) if p else {}


class ChoresDoneSensor(MoonlightPersonEntity, SensorEntity):
    _attr_native_unit_of_measurement = "chores"

    def __init__(self, coordinator: MoonlightCoordinator, person) -> None:
        super().__init__(coordinator, person, "chores_done")

    @property
    def native_value(self) -> int | None:
        p = self.person
        return p.chores_done if p else None


class DinnerSensor(MoonlightEntity, SensorEntity):
    _attr_translation_key = "dinner"

    def __init__(self, coordinator: MoonlightCoordinator) -> None:
        super().__init__(coordinator, "dinner")

    @property
    def native_value(self) -> str:
        return dinner_state(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data.dinner
        return {"date": d.date.isoformat(), "notes": d.notes} if d else {}


class NextEventSensor(MoonlightEntity, SensorEntity):
    _attr_translation_key = "next_event"

    def __init__(self, coordinator: MoonlightCoordinator) -> None:
        super().__init__(coordinator, "next_event")

    @property
    def native_value(self) -> str | None:
        ev = self.coordinator.data.next_event
        return ev.title[:255] if ev else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return event_attributes(self.coordinator.data, self.coordinator.data.next_event)
