"""A to-do list entity per Moonlight list (groceries, chores lists, ...)."""
from __future__ import annotations

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import MoonlightError
from .coordinator import MoonlightConfigEntry, MoonlightCoordinator
from .entity import MoonlightEntity, add_entities_as_they_appear
from .model import Summary, TodoList, due_param, item_patch

PARALLEL_UPDATES = 1


async def async_setup_entry(hass: HomeAssistant, entry: MoonlightConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data

    def build(data: Summary):
        for lst in data.lists:
            yield f"list_{lst.id}", lambda lst=lst: MoonlightTodoList(coordinator, lst)

    add_entities_as_they_appear(coordinator, async_add_entities, build)


class MoonlightTodoList(MoonlightEntity, TodoListEntity):
    _attr_translation_key = "list"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
    )

    def __init__(self, coordinator: MoonlightCoordinator, lst: TodoList) -> None:
        super().__init__(coordinator, f"list_{lst.id}")
        self.list_id = lst.id
        self._attr_name = lst.name

    @property
    def _list(self) -> TodoList | None:
        return self.coordinator.data.todo_list(self.list_id) if self.coordinator.data else None

    @property
    def available(self) -> bool:
        return super().available and self._list is not None

    @property
    def todo_items(self) -> list[TodoItem] | None:
        lst = self._list
        if lst is None:
            return None
        return [
            TodoItem(
                summary=i.title,
                uid=i.id,
                status=TodoItemStatus.COMPLETED if i.done else TodoItemStatus.NEEDS_ACTION,
                due=i.due,
            )
            for i in lst.items
        ]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        client = self.coordinator.client
        try:
            created = await client.add_item(self.list_id, item.summary or "", due_param(item.due))
            if item.status == TodoItemStatus.COMPLETED:
                await client.update_item(created["id"], {"done": True})
        except MoonlightError as err:
            raise HomeAssistantError(f"Couldn't add to Moonlight: {err}") from err
        await self.coordinator.async_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        lst = self._list
        current = next((i for i in lst.items if i.id == item.uid), None) if lst else None
        if current is None:
            raise ServiceValidationError(f"Item {item.uid} is not on this list")
        patch = item_patch(current, item.summary, item.status == TodoItemStatus.COMPLETED, item.due)
        if not patch:
            return
        try:
            await self.coordinator.client.update_item(current.id, patch)
        except MoonlightError as err:
            raise HomeAssistantError(f"Couldn't update Moonlight: {err}") from err
        await self.coordinator.async_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        try:
            for uid in uids:
                await self.coordinator.client.delete_item(uid)
        except MoonlightError as err:
            raise HomeAssistantError(f"Couldn't delete from Moonlight: {err}") from err
        await self.coordinator.async_refresh()
