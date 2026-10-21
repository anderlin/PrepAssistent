"""Einkaufsliste als To-do-Liste: fehlende Artikel aller Vorratslisten.

Abhaken erfasst den Artikel als gekauft (Soll-Menge, Kaufdatum, ggf. Ablaufdatum),
Hinzufügen setzt einen Artikel auf die Einkaufsliste, Löschen nimmt ihn nur von
der Einkaufsliste (der Artikel selbst bleibt erhalten).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PrepConfigEntry
from .const import SIGNAL_UPDATED
from .manager import PrepError, PrepManager
from .sensor import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PrepConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([PrepShoppingList(entry.runtime_data, entry.entry_id)])


def _summary(item: dict[str, Any]) -> str:
    return f"{item['name']} ({item['missing']:g} {item['unit']})".replace(" )", ")")


def _description(item: dict[str, Any]) -> str:
    return " · ".join(part for part in (item["list_name"], item.get("location")) if part)


class PrepShoppingList(TodoListEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "shopping_list"
    _attr_icon = "mdi:cart-outline"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, manager: PrepManager, entry_id: str) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry_id}_shopping_list"
        self._attr_device_info = device_info(entry_id)
        self._refresh()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATED, self._handle_update)
        )

    @callback
    def _refresh(self) -> None:
        missing = sorted(
            self._manager.summary()["missing"],
            key=lambda i: (i["list_name"].lower(), i["name"].lower()),
        )
        self._attr_todo_items = [
            TodoItem(
                uid=item["id"],
                summary=_summary(item),
                description=_description(item) or None,
                status=TodoItemStatus.NEEDS_ACTION,
            )
            for item in missing
        ]

    @callback
    def _handle_update(self) -> None:
        self._refresh()
        self.async_write_ha_state()

    def _run(self, func: Any, *args: Any) -> None:
        try:
            func(*args)
        except PrepError as err:
            raise ServiceValidationError(self._manager.error_text(err)) from err

    async def async_create_todo_item(self, item: TodoItem) -> None:
        self._run(self._manager.add_need, item.summary or "")

    async def async_update_todo_item(self, item: TodoItem) -> None:
        # Nur das Abhaken hat eine Wirkung; Text und Menge kommen aus dem Vorrat
        if item.status == TodoItemStatus.COMPLETED and item.uid:
            self._run(self._manager.mark_bought, [item.uid])

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        self._run(self._manager.clear_need, uids)
