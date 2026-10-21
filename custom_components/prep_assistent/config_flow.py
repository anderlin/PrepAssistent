"""Config- und Options-Flow für PrepAssistent."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_HOUSEHOLD_PERSONS,
    CONF_KCAL_PER_DAY,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TIME,
    CONF_PERSISTENT_NOTIFICATION,
    CONF_WARNING_DAYS,
    CONF_WATER_PER_DAY,
    DEFAULT_HOUSEHOLD_PERSONS,
    DEFAULT_KCAL_PER_DAY,
    DEFAULT_NOTIFY_TIME,
    DEFAULT_PERSISTENT_NOTIFICATION,
    DEFAULT_WARNING_DAYS,
    DEFAULT_WATER_PER_DAY,
    DOMAIN,
)


def _box(minimum: float, maximum: float, step: float, unit: str | None = None) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(
        min=minimum, max=maximum, step=step, mode=selector.NumberSelectorMode.BOX
    )
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _options_schema(options: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_WARNING_DAYS, default=options.get(CONF_WARNING_DAYS, DEFAULT_WARNING_DAYS)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=365, step=1, unit_of_measurement="Tage", mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_NOTIFY_TIME, default=options.get(CONF_NOTIFY_TIME, DEFAULT_NOTIFY_TIME)
            ): selector.TimeSelector(),
            vol.Required(
                CONF_PERSISTENT_NOTIFICATION,
                default=options.get(CONF_PERSISTENT_NOTIFICATION, DEFAULT_PERSISTENT_NOTIFICATION),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_NOTIFY_SERVICE,
                description={"suggested_value": options.get(CONF_NOTIFY_SERVICE)},
            ): selector.TextSelector(),
            vol.Required(
                CONF_HOUSEHOLD_PERSONS,
                default=options.get(CONF_HOUSEHOLD_PERSONS, DEFAULT_HOUSEHOLD_PERSONS),
            ): _box(1, 100, 1),
            vol.Required(
                CONF_KCAL_PER_DAY, default=options.get(CONF_KCAL_PER_DAY, DEFAULT_KCAL_PER_DAY)
            ): _box(500, 6000, 50, "kcal"),
            vol.Required(
                CONF_WATER_PER_DAY, default=options.get(CONF_WATER_PER_DAY, DEFAULT_WATER_PER_DAY)
            ): _box(0.5, 10, 0.1, "l"),
        }
    )


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        **user_input,
        CONF_WARNING_DAYS: int(user_input[CONF_WARNING_DAYS]),
        CONF_HOUSEHOLD_PERSONS: int(user_input[CONF_HOUSEHOLD_PERSONS]),
        CONF_KCAL_PER_DAY: int(user_input[CONF_KCAL_PER_DAY]),
        CONF_WATER_PER_DAY: float(user_input[CONF_WATER_PER_DAY]),
    }


class PrepConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="PrepAssistent", data={}, options=_normalize(user_input))
        return self.async_show_form(step_id="user", data_schema=_options_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        return PrepOptionsFlow()


class PrepOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=_normalize(user_input))
        return self.async_show_form(
            step_id="init", data_schema=_options_schema(dict(self.config_entry.options))
        )
