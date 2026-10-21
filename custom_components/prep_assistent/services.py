"""Services für Automationen und Skripte."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN
from .manager import PrepError, PrepManager
from .schemas import DAYS, ITEM_FIELDS, NAME, PERSONS, QUANTITY

SERVICE_ADD_ITEM = "add_item"
SERVICE_CONSUME_ITEM = "consume_item"
SERVICE_APPLY_TEMPLATE = "apply_template"
SERVICE_CHECK_EXPIRY = "check_expiry"
SERVICE_RELOAD_TEMPLATES = "reload_templates"

# Marker vergleichen nur den Schlüssel, daher "name" vorher entfernen statt überschreiben
ADD_ITEM_SCHEMA = vol.Schema(
    {
        vol.Required("name"): NAME,
        vol.Optional("list"): str,
        **{k: v for k, v in ITEM_FIELDS.items() if str(k) != "name"},
    }
)
CONSUME_ITEM_SCHEMA = vol.Schema(
    {
        vol.Exclusive("item_id", "item"): str,
        vol.Exclusive("name", "item"): NAME,
        vol.Optional("list"): str,
        vol.Optional("amount", default=1): QUANTITY,
    }
)
APPLY_TEMPLATE_SCHEMA = vol.Schema(
    {
        vol.Required("template"): str,
        vol.Required("persons"): PERSONS,
        vol.Required("days"): DAYS,
        vol.Optional("list"): str,
    }
)


def _manager(hass: HomeAssistant) -> PrepManager:
    manager: PrepManager | None = hass.data.get(DOMAIN)
    if manager is None:
        raise ServiceValidationError("PrepAssistent is not set up")
    return manager


def _error(manager: PrepManager, key: str, **params: Any) -> ServiceValidationError:
    """Fehlermeldung in der Systemsprache von Home Assistant."""
    return ServiceValidationError(manager.error_text(PrepError(key, **params)))


def _resolve_list(manager: PrepManager, ref: str | None) -> dict[str, Any]:
    if ref is None:
        if not manager.lists:
            raise _error(manager, "no_list")
        return min(manager.lists.values(), key=lambda lst: lst["created_at"])
    if (lst := manager.find_list(ref)) is None:
        raise _error(manager, "list_ref_not_found", list=ref)
    return lst


@callback
def async_register(hass: HomeAssistant) -> None:
    async def add_item(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        data = dict(call.data)
        lst = _resolve_list(manager, data.pop("list", None))
        try:
            item = manager.create_item(lst["id"], data)
        except PrepError as err:
            raise ServiceValidationError(manager.error_text(err)) from err
        return {"item_id": item["id"], "list_id": lst["id"]}

    async def consume_item(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        item_id = call.data.get("item_id")
        if item_id is None:
            name = call.data.get("name")
            if name is None:
                raise _error(manager, "item_or_name")
            list_id = _resolve_list(manager, call.data["list"])["id"] if "list" in call.data else None
            # Bei mehreren Chargen zuerst die, die am frühesten abläuft
            candidates = sorted(
                (
                    i
                    for i in manager.items.values()
                    if i["name"].lower() == name.lower()
                    and i["quantity"] > 0
                    and (list_id is None or i["list_id"] == list_id)
                ),
                key=lambda i: i["expiry_date"] or "9999-12-31",
            )
            if not candidates:
                raise _error(manager, "no_stock", name=name)
            item_id = candidates[0]["id"]
        try:
            item = manager.adjust_item(item_id, -call.data["amount"])
        except PrepError as err:
            raise ServiceValidationError(manager.error_text(err)) from err
        return {"item_id": item["id"], "quantity": item["quantity"]}

    async def apply_template(call: ServiceCall) -> ServiceResponse:
        manager = _manager(hass)
        list_ref = call.data.get("list")
        existing = manager.find_list(list_ref) if list_ref else None
        try:
            return manager.apply_template(
                call.data["template"],
                call.data["persons"],
                call.data["days"],
                list_id=existing["id"] if existing else None,
                list_name=None if existing else list_ref,
            )
        except PrepError as err:
            raise ServiceValidationError(manager.error_text(err)) from err

    async def check_expiry(call: ServiceCall) -> ServiceResponse:
        return await _manager(hass).async_check_expiry()

    async def reload_templates(call: ServiceCall) -> None:
        await _manager(hass).async_reload_templates()

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_ITEM, add_item, ADD_ITEM_SCHEMA, SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CONSUME_ITEM, consume_item, CONSUME_ITEM_SCHEMA, SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_APPLY_TEMPLATE,
        apply_template,
        APPLY_TEMPLATE_SCHEMA,
        SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CHECK_EXPIRY, check_expiry, vol.Schema({}), SupportsResponse.OPTIONAL
    )
    hass.services.async_register(DOMAIN, SERVICE_RELOAD_TEMPLATES, reload_templates, vol.Schema({}))
