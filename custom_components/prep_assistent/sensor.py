"""Sensoren: Bestand, Ablauf, Fehlmengen und Reichweite."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PrepConfigEntry
from .const import DOMAIN, PANEL_URL_PATH, SIGNAL_UPDATED, VERSION
from .manager import PrepManager

MAX_ATTR_ITEMS = 25
Summary = dict[str, Any]


def _brief(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item["name"],
        "list": item["list_name"],
        "quantity": item["quantity"],
        "unit": item["unit"],
        "expiry_date": item["effective_expiry"],
        "opened": item["expiry_source"] == "opened",
        "days_left": item["days_left"],
        "missing": item["missing"],
    }


def _items_attr(key: str) -> Callable[[Summary], dict[str, Any]]:
    return lambda s: {"items": [_brief(i) for i in s[key][:MAX_ATTR_ITEMS]]}


def _next_expiry_attrs(summary: Summary) -> dict[str, Any]:
    if not summary["dated"]:
        return {}
    return _brief(summary["dated"][0])


def _range_attrs(summary: Summary) -> dict[str, Any]:
    return {k: v for k, v in summary["range"].items() if k != "days"}


def device_info(entry_id: str) -> DeviceInfo:
    """Gemeinsames Gerät für alle Entitäten von PrepAssistent."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name="PrepAssistent",
        entry_type=DeviceEntryType.SERVICE,
        sw_version=VERSION,
        configuration_url=f"homeassistant://{PANEL_URL_PATH}",
    )


@dataclass(frozen=True, kw_only=True)
class PrepSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Summary], Any]
    attrs_fn: Callable[[Summary], dict[str, Any]] = lambda _: {}


SENSORS: tuple[PrepSensorDescription, ...] = (
    PrepSensorDescription(
        key="stock",
        translation_key="stock",
        icon="mdi:warehouse",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: len(s["stock"]),
    ),
    PrepSensorDescription(
        key="expiring",
        translation_key="expiring",
        icon="mdi:clock-alert-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: len(s["expiring"]),
        attrs_fn=_items_attr("expiring"),
    ),
    PrepSensorDescription(
        key="expired",
        translation_key="expired",
        icon="mdi:alert-octagon-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: len(s["expired"]),
        attrs_fn=_items_attr("expired"),
    ),
    PrepSensorDescription(
        key="missing",
        translation_key="missing",
        icon="mdi:cart-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: len(s["missing"]),
        attrs_fn=_items_attr("missing"),
    ),
    PrepSensorDescription(
        key="next_expiry",
        translation_key="next_expiry",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda s: date.fromisoformat(s["dated"][0]["effective_expiry"]) if s["dated"] else None,
        attrs_fn=_next_expiry_attrs,
    ),
    PrepSensorDescription(
        key="supply_days",
        translation_key="supply_days",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s["range"]["days"],
        attrs_fn=_range_attrs,
    ),
    PrepSensorDescription(
        key="food_supply_days",
        translation_key="food_supply_days",
        icon="mdi:food-variant",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s["range"]["food_days"],
    ),
    PrepSensorDescription(
        key="water_supply_days",
        translation_key="water_supply_days",
        icon="mdi:water",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s["range"]["water_days"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PrepConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    async_add_entities(PrepSensor(manager, entry.entry_id, description) for description in SENSORS)


class PrepSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: PrepSensorDescription

    def __init__(
        self, manager: PrepManager, entry_id: str, description: PrepSensorDescription
    ) -> None:
        self.entity_description = description
        self._manager = manager
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = device_info(entry_id)
        self._refresh()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATED, self._handle_update)
        )

    @callback
    def _refresh(self) -> None:
        summary = self._manager.summary()
        self._attr_native_value = self.entity_description.value_fn(summary)
        self._attr_extra_state_attributes = self.entity_description.attrs_fn(summary)

    @callback
    def _handle_update(self) -> None:
        self._refresh()
        self.async_write_ha_state()
