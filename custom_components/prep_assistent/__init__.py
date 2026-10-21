"""PrepAssistent – Vorratskammern in Home Assistant verwalten."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.frontend import add_extra_js_url, remove_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from . import services, websocket_api
from .const import (
    CARD_URL,
    DOMAIN,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL_PATH,
    STATIC_URL,
    VERSION,
)
from .manager import PrepManager

PLATFORMS = [Platform.SENSOR, Platform.TODO]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type PrepConfigEntry = ConfigEntry[PrepManager]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registriert Frontend-Dateien, WebSocket-API und Services (einmalig)."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "frontend"), False)]
    )
    websocket_api.async_register(hass)
    services.async_register(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PrepConfigEntry) -> bool:
    manager = PrepManager(hass, entry)
    await manager.async_setup()
    entry.runtime_data = manager
    hass.data[DOMAIN] = manager

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=f"{STATIC_URL}/prep-assistent-panel.js?v={VERSION}",
        require_admin=False,
    )
    # Lovelace-Karte "custom:prep-assistent-card" ohne manuelle Ressource bereitstellen
    add_extra_js_url(hass, CARD_URL)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PrepConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
        remove_extra_js_url(hass, CARD_URL)
        hass.data.pop(DOMAIN, None)
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: PrepConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
