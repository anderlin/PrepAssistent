"""Gemeinsame Validierungsschemas für WebSocket-API und Services."""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol


def iso_date(value: Any) -> str | None:
    """Akzeptiert date/ISO-String, leere Werte werden zu None."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as err:
        raise vol.Invalid("invalid date, expected YYYY-MM-DD") from err


QUANTITY = vol.All(vol.Coerce(float), vol.Range(min=0))
OPTIONAL_QUANTITY = vol.Any(None, "", QUANTITY)
OPTIONAL_DAYS = vol.Any(None, "", vol.All(vol.Coerce(int), vol.Range(min=0)))
NAME = vol.All(str, vol.Strip, vol.Length(min=1, max=200))
LOCATION = vol.All(str, vol.Strip, vol.Length(min=1, max=100))
ICON = vol.All(str, vol.Strip, vol.Length(max=100))
ITEM_IDS = vol.All([str], vol.Length(min=1))

# Gemeinsam änderbare Felder bei Mehrfachauswahl
BULK_FIELDS: dict[vol.Marker, Any] = {
    vol.Optional("list_id"): str,
    vol.Optional("category"): str,
    vol.Optional("location"): vol.All(str, vol.Strip, vol.Length(max=100)),
}

ITEM_FIELDS: dict[vol.Marker, Any] = {
    vol.Optional("name"): NAME,
    vol.Optional("category"): str,
    vol.Optional("quantity"): QUANTITY,
    vol.Optional("target_quantity"): OPTIONAL_QUANTITY,
    vol.Optional("unit"): vol.All(str, vol.Length(max=30)),
    vol.Optional("purchase_date"): iso_date,
    vol.Optional("expiry_date"): iso_date,
    vol.Optional("location"): vol.All(str, vol.Length(max=100)),
    vol.Optional("notes"): vol.All(str, vol.Length(max=1000)),
    vol.Optional("shelf_life_days"): OPTIONAL_DAYS,
    vol.Optional("opened_date"): iso_date,
    vol.Optional("opened_shelf_life_days"): OPTIONAL_DAYS,
    vol.Optional("kcal_per_unit"): OPTIONAL_QUANTITY,
    vol.Optional("water_per_unit"): OPTIONAL_QUANTITY,
}

LIST_FIELDS: dict[vol.Marker, Any] = {
    vol.Optional("name"): NAME,
    vol.Optional("description"): vol.All(str, vol.Length(max=500)),
}

PERSONS = vol.All(vol.Coerce(int), vol.Range(min=1, max=100))
DAYS = vol.All(vol.Coerce(int), vol.Range(min=1, max=3650))
