"""Binary sensor per child: all of today's chores done."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MoonlightConfigEntry, MoonlightCoordinator
from .entity import MoonlightPersonEntity, add_entities_as_they_appear
from .model import Summary, chores_attributes

PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: MoonlightConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data

    def build(data: Summary):
        for p in data.people:
            if p.is_child:
                yield f"{p.id}_all_chores_done", lambda p=p: AllChoresDone(coordinator, p)

    add_entities_as_they_appear(coordinator, async_add_entities, build)


class AllChoresDone(MoonlightPersonEntity, BinarySensorEntity):
    """On when every chore due today is ticked off (also on when nothing is due)."""

    def __init__(self, coordinator: MoonlightCoordinator, person) -> None:
        super().__init__(coordinator, person, "all_chores_done")

    @property
    def is_on(self) -> bool | None:
        p = self.person
        return p.all_done if p else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self.person
        return chores_attributes(p) if p else {}
