"""Integrationstests: Setup, WebSocket-API, Services, Sensoren und Warnungen."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.prep_assistent.const import DOMAIN, EVENT_EXPIRY, NOTIFICATION_ID

TODAY = date(2026, 10, 20)


@pytest.fixture
async def entry(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(dt_util.as_utc(dt_util.parse_datetime("2026-10-20 07:00:00+02:00")))
    entry = MockConfigEntry(domain=DOMAIN, options={"warning_days": 30, "notify_time": "08:00:00"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _ws(client: Any, msg: dict[str, Any]) -> Any:
    await client.send_json_auto_id(msg)
    resp = await client.receive_json()
    assert resp["success"], resp
    return resp["result"]


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


async def test_setup_creates_default_list_and_sensors(hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: Any) -> None:
    assert entry.state is ConfigEntryState.LOADED
    client = await hass_ws_client(hass)
    data = await _ws(client, {"type": "prep_assistent/data"})
    assert [lst["name"] for lst in data["lists"]] == ["Pantry"]  # Systemsprache im Test: en
    assert data["today"] == TODAY.isoformat()
    assert any(c["id"] == "hausapotheke" for c in data["categories"])
    stock = hass.states.get("sensor.prepassistent_items_in_stock")
    assert (stock.state, stock.attributes["unit_of_measurement"]) == ("0", "items")
    assert "prep-assistent" in hass.data["frontend_panels"]


async def test_item_crud_and_status(hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: Any) -> None:
    client = await hass_ws_client(hass)
    list_id = (await _ws(client, {"type": "prep_assistent/data"}))["lists"][0]["id"]

    for name, days in (("Milch", -2), ("Reis", 10), ("Nudeln", 200)):
        await _ws(client, {"type": "prep_assistent/item/create", "list_id": list_id, "name": name, "category": "lebensmittel", "quantity": 2, "unit": "Pkg", "purchase_date": _iso(-30), "expiry_date": _iso(days)})
    pflaster = await _ws(client, {"type": "prep_assistent/item/create", "list_id": list_id, "name": "Pflaster", "category": "hausapotheke", "quantity": 1, "target_quantity": 3})

    data = await _ws(client, {"type": "prep_assistent/data"})
    by_name = {i["name"]: i for i in data["items"]}
    assert (by_name["Milch"]["status"], by_name["Milch"]["days_left"]) == ("expired", -2)
    assert by_name["Reis"]["status"] == "expiring"
    assert by_name["Nudeln"]["status"] == "ok"
    assert (by_name["Pflaster"]["status"], by_name["Pflaster"]["missing"]) == ("none", 2)

    await hass.async_block_till_done()
    states = {s.entity_id: s for s in hass.states.async_all("sensor")}
    values = sorted(s.state for s in states.values())
    assert "2026-10-18" in values  # nächstes Ablaufdatum
    expired = next(s for s in states.values() if s.attributes.get("items") and s.attributes["items"][0]["name"] == "Milch")
    assert expired.state == "1"

    adjusted = await _ws(client, {"type": "prep_assistent/item/adjust", "item_id": pflaster["id"], "delta": -5})
    assert adjusted["quantity"] == 0

    await client.send_json_auto_id({"type": "prep_assistent/item/update", "item_id": pflaster["id"], "purchase_date": _iso(0), "expiry_date": _iso(-1)})
    resp = await client.receive_json()
    assert not resp["success"]
    assert resp["error"]["translation_key"] == "expiry_before_purchase"
    assert resp["error"]["message"] == "Expiry date is before the purchase date"

    await client.send_json_auto_id({"type": "prep_assistent/item/create", "list_id": list_id, "name": "X", "category": "gibtsnicht"})
    resp = await client.receive_json()
    assert not resp["success"]
    assert resp["error"]["translation_placeholders"] == {"category": "gibtsnicht"}

    await _ws(client, {"type": "prep_assistent/item/delete", "item_id": pflaster["id"]})
    assert len((await _ws(client, {"type": "prep_assistent/data"}))["items"]) == 3


async def test_template_preview_and_apply(hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: Any) -> None:
    client = await hass_ws_client(hass)
    templates = await _ws(client, {"type": "prep_assistent/templates"})
    assert {"bbk_notvorrat", "hausapotheke_basis"} <= {t["id"] for t in templates["templates"]}

    preview = await _ws(client, {"type": "prep_assistent/template/preview", "template_id": "bbk_notvorrat", "persons": 4, "days": 14})
    water = next(i for i in preview["items"] if i["unit"] == "l" and i["category"] == "getraenke")
    assert water["quantity"] == 112  # 2 l * 4 P * 14 T

    result = await _ws(client, {"type": "prep_assistent/template/apply", "template_id": "bbk_notvorrat", "persons": 4, "days": 14})
    assert result["created"] == len(preview["items"]) and result["updated"] == 0

    again = await _ws(client, {"type": "prep_assistent/template/apply", "template_id": "bbk_notvorrat", "persons": 2, "days": 14, "list_id": result["list_id"]})
    assert again == {**again, "created": 0, "updated": len(preview["items"])}

    data = await _ws(client, {"type": "prep_assistent/data"})
    water_item = next(i for i in data["items"] if i["list_id"] == result["list_id"] and i["name"] == water["name"])
    assert (water_item["quantity"], water_item["target_quantity"], water_item["missing"]) == (0, 56, 56)


async def test_services(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    res = await hass.services.async_call(DOMAIN, "add_item", {"name": "Reis", "quantity": 3, "expiry_date": _iso(100)}, blocking=True, return_response=True)
    await hass.services.async_call(DOMAIN, "add_item", {"name": "Reis", "quantity": 1, "expiry_date": _iso(5)}, blocking=True)
    consumed = await hass.services.async_call(DOMAIN, "consume_item", {"name": "reis"}, blocking=True, return_response=True)
    manager = hass.data[DOMAIN]
    # Die früher ablaufende Charge wird zuerst verbraucht
    assert consumed["item_id"] != res["item_id"] and consumed["quantity"] == 0
    assert manager.items[res["item_id"]]["quantity"] == 3

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "add_item", {"name": "X", "list": "Gibt es nicht"}, blocking=True)

    applied = await hass.services.async_call(DOMAIN, "apply_template", {"template": "hausapotheke_basis", "persons": 3, "days": 30, "list": "Apotheke"}, blocking=True, return_response=True)
    assert applied["list_name"] == "Apotheke" and applied["created"] > 0


async def test_daily_expiry_warning(hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory) -> None:
    events = []
    hass.bus.async_listen(EVENT_EXPIRY, events.append)
    await hass.services.async_call(DOMAIN, "add_item", {"name": "Milch", "quantity": 1, "expiry_date": _iso(3)}, blocking=True)

    freezer.move_to(dt_util.as_utc(dt_util.parse_datetime("2026-10-20 08:00:00+02:00")))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["expiring"][0]["name"] == "Milch"
    notifications = persistent_notification._async_get_or_create_notifications(hass)
    assert NOTIFICATION_ID in notifications
    assert "Milch" in notifications[NOTIFICATION_ID]["message"]


async def test_persistence_and_unload(hass: HomeAssistant, entry: MockConfigEntry, hass_storage: dict) -> None:
    await hass.services.async_call(DOMAIN, "add_item", {"name": "Kerzen", "category": "haushalt", "quantity": 10}, blocking=True)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert "prep-assistent" not in hass.data["frontend_panels"]
    stored = hass_storage[DOMAIN]["data"]
    assert [i["name"] for i in stored["items"]] == ["Kerzen"]

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert [i["name"] for i in hass.data[DOMAIN].items.values()] == ["Kerzen"]


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"warning_days": 14.0, "notify_time": "07:30:00", "persistent_notification": True},
    )
    assert result["type"] == "create_entry"
    assert result["options"]["warning_days"] == 14


async def test_template_languages(hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: Any) -> None:
    client = await hass_ws_client(hass)
    templates = await _ws(client, {"type": "prep_assistent/templates", "language": "de"})
    names = {t["id"]: t["name"] for t in templates["templates"]}
    assert names["bbk_notvorrat_detail"].startswith("Notvorrat detailliert")

    msg = {"type": "prep_assistent/template/preview", "template_id": "bbk_notvorrat_detail", "persons": 2, "days": 10}
    de = (await _ws(client, {**msg, "language": "de"}))["items"]
    ru = (await _ws(client, {**msg, "language": "ru"}))["items"]
    by_name = {i["name"]: i for i in de}
    assert by_name["Trockenfleisch (Beef Jerky)"]["unit"] == "kg"
    assert by_name["Fertiggericht / Eintopf (Konserve)"]["unit"] == "Dosen"
    assert any(i["name"] == "Вяленое мясо (джерки)" for i in ru)
    assert [i["quantity"] for i in de] == [i["quantity"] for i in ru]

    # Erst auf Deutsch übernehmen, dann auf Englisch erneut: gleiche Artikel werden erkannt
    applied = await _ws(client, {"type": "prep_assistent/template/apply", "template_id": "bbk_notvorrat_detail", "persons": 2, "days": 10, "language": "de"})
    assert applied["list_name"] == "Notvorrat detailliert (Beispiel nach BBK-Empfehlung) (2 Personen, 10 Tage)"
    again = await _ws(client, {"type": "prep_assistent/template/apply", "template_id": "bbk_notvorrat_detail", "persons": 3, "days": 10, "list_id": applied["list_id"], "language": "en"})
    assert (again["created"], again["updated"]) == (0, applied["created"])


async def test_notification_in_system_language(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    hass.config.language = "de"
    await hass.services.async_call(DOMAIN, "add_item", {"name": "Milch", "quantity": 1, "expiry_date": _iso(1)}, blocking=True)
    await hass.services.async_call(DOMAIN, "add_item", {"name": "Brot", "quantity": 1, "expiry_date": _iso(-3)}, blocking=True)
    await hass.services.async_call(DOMAIN, "check_expiry", {}, blocking=True)
    notification = persistent_notification._async_get_or_create_notifications(hass)[NOTIFICATION_ID]
    assert notification["title"] == "PrepAssistent: 1 abgelaufen, 1 läuft bald ab"
    assert "seit 3 Tagen abgelaufen" in notification["message"]
    assert "noch 1 Tag" in notification["message"]

    with pytest.raises(ServiceValidationError, match="Liste „Gibt es nicht“ nicht gefunden"):
        await hass.services.async_call(DOMAIN, "add_item", {"name": "X", "list": "Gibt es nicht"}, blocking=True)
