"""Base entity: one "Moonlight" device per config entry."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import MoonlightCoordinator
from .model import Person, Summary


class MoonlightEntity(CoordinatorEntity[MoonlightCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: MoonlightCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Moonlight",
            manufacturer=MANUFACTURER,
            model="Family wall calendar",
            sw_version=coordinator.data.version if coordinator.data else None,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=coordinator.client.base,
        )


class MoonlightPersonEntity(MoonlightEntity):
    """An entity about one person; unavailable once that person is deleted in Moonlight."""

    def __init__(self, coordinator: MoonlightCoordinator, person: Person, kind: str) -> None:
        super().__init__(coordinator, f"{person.id}_{kind}")
        self.person_id = person.id
        self._attr_translation_key = kind
        self._attr_translation_placeholders = {"person": person.name}

    @property
    def person(self) -> Person | None:
        return self.coordinator.data.person(self.person_id) if self.coordinator.data else None

    @property
    def available(self) -> bool:
        return super().available and self.person is not None


@callback
def add_entities_as_they_appear(
    coordinator: MoonlightCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build: Callable[[Summary], Iterable[tuple[str, Callable[[], Entity]]]],
) -> None:
    """Add entities now and whenever a new person or list shows up in Moonlight (no reload needed)."""
    known: set[str] = set()

    @callback
    def _check() -> None:
        if coordinator.data is None:
            return
        new = []
        for key, factory in build(coordinator.data):
            if key not in known:
                known.add(key)
                new.append(factory())
        if new:
            async_add_entities(new)

    _check()
    coordinator.config_entry.async_on_unload(coordinator.async_add_listener(_check))
