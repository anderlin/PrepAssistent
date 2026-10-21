"""WebSocket-API für das PrepAssistent-Panel."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, SIGNAL_UPDATED
from .manager import PrepError, PrepManager
from .schemas import (
    BULK_FIELDS,
    DAYS,
    ICON,
    ITEM_FIELDS,
    ITEM_IDS,
    LIST_FIELDS,
    LOCATION,
    NAME,
    PERSONS,
)

Handler = Callable[[PrepManager, dict[str, Any]], Any]
LANGUAGE = vol.Optional("language")


def _send_not_loaded(connection: websocket_api.ActiveConnection, msg_id: int) -> None:
    connection.send_error(
        msg_id,
        "not_loaded",
        "PrepAssistent is not loaded",
        translation_key="not_loaded",
        translation_domain=DOMAIN,
    )


def _handler(func: Handler) -> websocket_api.WebSocketCommandHandler:
    """Holt den Manager, ruft den Handler auf und sendet Ergebnis bzw. Fehler."""

    @wraps(func)
    def wrapper(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
    ) -> None:
        manager: PrepManager | None = hass.data.get(DOMAIN)
        if manager is None:
            _send_not_loaded(connection, msg["id"])
            return
        try:
            result = func(manager, msg)
        except PrepError as err:
            # Das Panel übersetzt anhand von translation_key in die Sprache des Benutzers
            connection.send_error(
                msg["id"],
                "invalid",
                manager.error_text(err),
                translation_key=err.key,
                translation_domain=DOMAIN,
                translation_placeholders={k: str(v) for k, v in err.params.items()},
            )
            return
        connection.send_result(msg["id"], result)

    return wrapper


def _fields(msg: dict[str, Any], schema: dict[vol.Marker, Any]) -> dict[str, Any]:
    keys = {str(marker) for marker in schema}
    return {k: v for k, v in msg.items() if k in keys}


@websocket_api.websocket_command({vol.Required("type"): "prep_assistent/data"})
@callback
@_handler
def ws_data(manager: PrepManager, msg: dict[str, Any]) -> Any:
    return manager.as_dict()


@websocket_api.websocket_command({vol.Required("type"): "prep_assistent/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    @callback
    def forward() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"updated": True}))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_UPDATED, forward)
    connection.send_result(msg["id"])


# ------------------------------------------------------------------- listen


@websocket_api.websocket_command(
    {
        vol.Required("type"): "prep_assistent/list/create",
        vol.Required("name"): NAME,
        vol.Optional("description", default=""): str,
    }
)
@callback
@_handler
def ws_list_create(manager: PrepManager, msg: dict[str, Any]) -> Any:
    return manager.create_list(msg["name"], msg["description"])


@websocket_api.websocket_command(
    {vol.Required("type"): "prep_assistent/list/update", vol.Required("list_id"): str, **LIST_FIELDS}
)
@callback
@_handler
def ws_list_update(manager: PrepManager, msg: dict[str, Any]) -> Any:
    return manager.update_list(msg["list_id"], _fields(msg, LIST_FIELDS))


@websocket_api.websocket_command(
    {vol.Required("type"): "prep_assistent/list/delete", vol.Required("list_id"): str}
)
@callback
@_handler
def ws_list_delete(manager: PrepManager, msg: dict[str, Any]) -> Any:
    manager.delete_list(msg["list_id"])


# ------------------------------------------------------------------ artikel


@websocket_api.websocket_command(
    {vol.Required("type"): "prep_assistent/item/create", vol.Required("list_id"): str, **ITEM_FIELDS}
)
@callback
@_handler
def ws_item_create(manager: PrepManager, msg: dict[str, Any]) -> Any:
    return manager.create_item(msg["list_id"], _fields(msg, ITEM_FIELDS))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "prep_assistent/item/update",
        vol.Required("item_id"): str,
        vol.Optional("list_id"): str,
        **ITEM_FIELDS,
    }
)
@callback
@_handler
def ws_item_update(manager: PrepManager, msg: dict[str, Any]) -> Any:
    changes = _fields(msg, ITEM_FIELDS)
    if "list_id" in msg:
        changes["list_id"] = msg["list_id"]
    return manager.update_item(msg["item_id"], changes)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "prep_assistent/item/adjust",
        vol.Required("item_id"): str,
        vol.Required("delta"): vol.Coerce(float),
    }
)
@callback
@_handler
def ws_item_adjust(manager: PrepManager, msg: dict[str, Any]) -> Any:
    return manager.adjust_item(msg["item_id"], msg["delta"])


@websocket_api.websocket_command(
    {vol.Required("type"): "prep_assistent/item/delete", vol.Required("item_id"): str}
)
@callback
@_handler
def ws_item_delete(manager: PrepManager, msg: dict[str, Any]) -> Any:
    manager.delete_item(msg["item_id"])


@websocket_api.websocket_command(
    {vol.Required("type"): "prep_assistent/item/open", vol.Required("item_id"): str}
)
@callback
@_handler
def ws_item_open(manager: PrepManager, msg: dict[str, Any]) -> Any:
    return manager.open_item(msg["item_id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "prep_assistent/items/bulk",
        vol.Required("item_ids"): ITEM_IDS,
        vol.Required("action"): vol.In(("update", "buy", "delete")),
        **BULK_FIELDS,
    }
)
@callback
@_handler
def ws_items_bulk(manager: PrepManager, msg: dict[str, Any]) -> Any:
    ids = msg["item_ids"]
    if msg["action"] == "buy":
        return {"count": len(manager.mark_bought(ids))}
    if msg["action"] == "delete":
        return {"count": manager.bulk_delete(ids)}
    return {"count": manager.bulk_update(ids, _fields(msg, BULK_FIELDS))}


# --------------------------------------------------------------- kategorien


@websocket_api.websocket_command(
    {
        vol.Required("type"): "prep_assistent/category/create",
        vol.Required("name"): NAME,
        vol.Optional("icon", default=""): ICON,
    }
)
@callback
@_handler
def ws_category_create(manager: PrepManager, msg: dict[str, Any]) -> Any:
    return manager.create_category(msg["name"], msg["icon"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "prep_assistent/category/update",
        vol.Required("category_id"): str,
        vol.Optional("name"): NAME,
        vol.Optional("icon"): ICON,
    }
)
@callback
@_handler
def ws_category_update(manager: PrepManager, msg: dict[str, Any]) -> Any:
    changes = {k: msg[k] for k in ("name", "icon") if k in msg}
    return manager.update_category(msg["category_id"], changes)


@websocket_api.websocket_command(
    {vol.Required("type"): "prep_assistent/category/delete", vol.Required("category_id"): str}
)
@callback
@_handler
def ws_category_delete(manager: PrepManager, msg: dict[str, Any]) -> Any:
    return {"moved": manager.delete_category(msg["category_id"])}


@websocket_api.websocket_command(
    {vol.Required("type"): "prep_assistent/category/reorder", vol.Required("category_ids"): [str]}
)
@callback
@_handler
def ws_category_reorder(manager: PrepManager, msg: dict[str, Any]) -> Any:
    manager.reorder_categories(msg["category_ids"])


# ---------------------------------------------------------------- lagerorte


@websocket_api.websocket_command(
    {vol.Required("type"): "prep_assistent/location/create", vol.Required("name"): LOCATION}
)
@callback
@_handler
def ws_location_create(manager: PrepManager, msg: dict[str, Any]) -> Any:
    manager.create_location(msg["name"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "prep_assistent/location/rename",
        vol.Required("old"): LOCATION,
        vol.Required("new"): LOCATION,
    }
)
@callback
@_handler
def ws_location_rename(manager: PrepManager, msg: dict[str, Any]) -> Any:
    return {"changed": manager.rename_location(msg["old"], msg["new"])}


@websocket_api.websocket_command(
    {vol.Required("type"): "prep_assistent/location/delete", vol.Required("name"): LOCATION}
)
@callback
@_handler
def ws_location_delete(manager: PrepManager, msg: dict[str, Any]) -> Any:
    return {"cleared": manager.delete_location(msg["name"])}


# ----------------------------------------------------------------- vorlagen


@websocket_api.websocket_command(
    {vol.Required("type"): "prep_assistent/templates", LANGUAGE: str}
)
@callback
@_handler
def ws_templates(manager: PrepManager, msg: dict[str, Any]) -> Any:
    return manager.templates_overview(msg.get("language"))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "prep_assistent/template/preview",
        vol.Required("template_id"): str,
        vol.Required("persons"): PERSONS,
        vol.Required("days"): DAYS,
        LANGUAGE: str,
    }
)
@callback
@_handler
def ws_template_preview(manager: PrepManager, msg: dict[str, Any]) -> Any:
    return {
        "items": manager.preview_template(
            msg["template_id"], msg["persons"], msg["days"], msg.get("language")
        )
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): "prep_assistent/template/apply",
        vol.Required("template_id"): str,
        vol.Required("persons"): PERSONS,
        vol.Required("days"): DAYS,
        vol.Exclusive("list_id", "target"): str,
        vol.Exclusive("list_name", "target"): NAME,
        LANGUAGE: str,
    }
)
@callback
@_handler
def ws_template_apply(manager: PrepManager, msg: dict[str, Any]) -> Any:
    return manager.apply_template(
        msg["template_id"],
        msg["persons"],
        msg["days"],
        list_id=msg.get("list_id"),
        list_name=msg.get("list_name"),
        language=msg.get("language"),
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "prep_assistent/templates/reload", LANGUAGE: str}
)
@websocket_api.async_response
async def ws_templates_reload(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    manager: PrepManager | None = hass.data.get(DOMAIN)
    if manager is None:
        _send_not_loaded(connection, msg["id"])
        return
    await manager.async_reload_templates()
    connection.send_result(msg["id"], manager.templates_overview(msg.get("language")))


@callback
def async_register(hass: HomeAssistant) -> None:
    for command in (
        ws_data,
        ws_subscribe,
        ws_list_create,
        ws_list_update,
        ws_list_delete,
        ws_item_create,
        ws_item_update,
        ws_item_adjust,
        ws_item_delete,
        ws_item_open,
        ws_items_bulk,
        ws_category_create,
        ws_category_update,
        ws_category_delete,
        ws_category_reorder,
        ws_location_create,
        ws_location_rename,
        ws_location_delete,
        ws_templates,
        ws_template_preview,
        ws_template_apply,
        ws_templates_reload,
    ):
        websocket_api.async_register_command(hass, command)
