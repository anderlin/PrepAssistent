"""Tests für v0.3.0: Einkaufsliste (To-do), Reichweite, Mehrfachauswahl, Öffnen, Kategorien & Lagerorte."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.prep_assistent.calc import supply_range
from custom_components.prep_assistent.const import DOMAIN

TODAY = date(2026, 10, 20)
TODO = "todo.prepassistent_shopping_list"


@pytest.fixture
async def entry(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(dt_util.as_utc(dt_util.parse_datetime("2026-10-20 07:00:00+02:00")))
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={"warning_days": 30, "notify_time": "08:00:00", "household_persons": 2, "kcal_per_day": 2000, "water_per_day": 2.0},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _ws(client: Any, msg: dict[str, Any]) -> Any:
    await client.send_json_auto_id(msg)
    resp = await client.receive_json()
    assert resp["success"], resp
    return resp["result"]


async def _ws_error(client: Any, msg: dict[str, Any]) -> dict[str, Any]:
    await client.send_json_auto_id(msg)
    resp = await client.receive_json()
    assert not resp["success"], resp
    return resp["error"]


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


async def _add(hass: HomeAssistant, **fields: Any) -> str:
    res = await hass.services.async_call(DOMAIN, "add_item", fields, blocking=True, return_response=True)
    return res["item_id"]


async def _todo_items(hass: HomeAssistant) -> list[dict[str, Any]]:
    res = await hass.services.async_call("todo", "get_items", {}, target={"entity_id": TODO}, blocking=True, return_response=True)
    return res[TODO]["items"]


# ----------------------------------------------------------------- reichweite


def test_supply_range() -> None:
    items = [
        {"quantity": 2, "kcal_per_unit": 3500, "status": "ok"},  # 7000 kcal
        {"quantity": 10, "water_per_unit": 1, "status": "none"},  # 10 l
        {"quantity": 5, "kcal_per_unit": 1000, "status": "expired"},  # zählt nicht
        {"quantity": 0, "kcal_per_unit": 1000, "status": "none"},  # nicht vorrätig
    ]
    r = supply_range(items, persons=2, kcal_per_day=2000, water_per_day=2)
    assert (r["food_days"], r["water_days"], r["days"]) == (1.8, 2.5, 1.8)
    assert (r["kcal"], r["water"]) == (7000, 10)
    # Ohne Wasserangaben zählt nur die Nahrung, ohne Angaben gibt es keine Reichweite
    assert supply_range(items[:1], 1, 2000, 2)["days"] == 3.5
    assert supply_range([], 1, 2000, 2)["days"] is None


async def test_range_sensors_and_data(hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: Any) -> None:
    await _add(hass, name="Reis", unit="kg", quantity=4, kcal_per_unit=3500)  # 14000 kcal → 3,5 Tage
    await _add(hass, name="Wasser", unit="l", quantity=20, water_per_unit=1)  # 20 l → 5 Tage
    await hass.async_block_till_done()
    assert hass.states.get("sensor.prepassistent_supply_range").state == "3.5"
    assert hass.states.get("sensor.prepassistent_water_supply_range").state == "5.0"
    attrs = hass.states.get("sensor.prepassistent_supply_range").attributes
    assert (attrs["kcal"], attrs["persons"]) == (14000, 2)

    client = await hass_ws_client(hass)
    data = await _ws(client, {"type": "prep_assistent/data"})
    list_id = data["lists"][0]["id"]
    assert data["range"]["days"] == 3.5
    assert data["list_ranges"][list_id]["water_days"] == 5.0
    assert data["settings"]["kcal_per_day"] == 2000


async def test_template_apply_copies_nutrition(hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: Any) -> None:
    client = await hass_ws_client(hass)
    applied = await _ws(client, {"type": "prep_assistent/template/apply", "template_id": "bbk_notvorrat_detail", "persons": 2, "days": 10, "language": "en"})
    items = {i["name"]: i for i in hass.data[DOMAIN].items.values() if i["list_id"] == applied["list_id"]}
    assert items["Rice"]["kcal_per_unit"] == 3500
    assert items["Mineral water"]["water_per_unit"] == 1
    assert items["UHT milk"]["opened_shelf_life_days"] == 3

    # Eigene Werte bleiben beim erneuten Übernehmen erhalten
    await _ws(client, {"type": "prep_assistent/item/update", "item_id": items["Rice"]["id"], "kcal_per_unit": 3600})
    await _ws(client, {"type": "prep_assistent/template/apply", "template_id": "bbk_notvorrat_detail", "persons": 2, "days": 10, "list_id": applied["list_id"]})
    assert hass.data[DOMAIN].items[items["Rice"]["id"]]["kcal_per_unit"] == 3600


# --------------------------------------------------------------- einkaufsliste


async def test_shopping_list_todo(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    manager = hass.data[DOMAIN]
    reis = await _add(hass, name="Reis", unit="kg", quantity=1, target_quantity=3, shelf_life_days=365, location="Keller")
    await _add(hass, name="Nudeln", quantity=2, target_quantity=2)  # nichts fehlt
    await hass.async_block_till_done()

    items = await _todo_items(hass)
    assert [(i["uid"], i["summary"], i["description"]) for i in items] == [(reis, "Reis (2 kg)", "Pantry · Keller")]
    assert hass.states.get(TODO).state == "1"

    # Abhaken = gekauft: Soll-Menge, Kaufdatum und Ablaufdatum aus der Haltbarkeit
    await hass.services.async_call("todo", "update_item", {"item": reis, "status": "completed"}, target={"entity_id": TODO}, blocking=True)
    item = manager.items[reis]
    assert (item["quantity"], item["purchase_date"], item["expiry_date"]) == (3, _iso(0), _iso(365))
    assert await _todo_items(hass) == []

    # Hinzufügen per Sprache: neuer Artikel bzw. höhere Soll-Menge bei bekanntem Artikel
    await hass.services.async_call("todo", "add_item", {"item": "Kaffee"}, target={"entity_id": TODO}, blocking=True)
    await hass.services.async_call("todo", "add_item", {"item": "reis"}, target={"entity_id": TODO}, blocking=True)
    summaries = sorted(i["summary"] for i in await _todo_items(hass))
    assert summaries == ["Kaffee (1 pcs)", "Reis (1 kg)"]
    assert manager.items[reis]["target_quantity"] == 4

    # Entfernen nimmt nur den Bedarf weg, der Artikel bleibt
    await hass.services.async_call("todo", "remove_item", {"item": "Reis (1 kg)"}, target={"entity_id": TODO}, blocking=True)
    assert manager.items[reis]["target_quantity"] == 3
    assert [i["summary"] for i in await _todo_items(hass)] == ["Kaffee (1 pcs)"]


async def test_shopping_list_without_list(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    manager = hass.data[DOMAIN]
    manager.delete_list(next(iter(manager.lists)))
    with pytest.raises(ServiceValidationError, match="No list exists yet"):
        await hass.services.async_call("todo", "add_item", {"item": "Kaffee"}, target={"entity_id": TODO}, blocking=True)


# ------------------------------------------------------------------- öffnen


async def test_open_item_splits_batch(hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: Any) -> None:
    client = await hass_ws_client(hass)
    milk = await _add(hass, name="H-Milch", unit="l", quantity=6, target_quantity=6, expiry_date=_iso(90), opened_shelf_life_days=3, kcal_per_unit=640)
    opened = await _ws(client, {"type": "prep_assistent/item/open", "item_id": milk})
    assert opened["id"] != milk
    assert (opened["quantity"], opened["opened_date"], opened["target_quantity"], opened["kcal_per_unit"]) == (1, _iso(0), None, 640)

    data = {i["id"]: i for i in (await _ws(client, {"type": "prep_assistent/data"}))["items"]}
    assert (data[milk]["quantity"], data[milk]["status"], data[milk]["effective_expiry"]) == (5, "ok", _iso(90))
    # Geöffnete Charge: früheres Datum aus Öffnung + 3 Tage zählt
    assert (data[opened["id"]]["effective_expiry"], data[opened["id"]]["expiry_source"], data[opened["id"]]["status"]) == (_iso(3), "opened", "expiring")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.prepassistent_next_expiry_date").state == _iso(3)

    # Einzelne Einheit: wird direkt markiert
    again = await _ws(client, {"type": "prep_assistent/item/open", "item_id": opened["id"]})
    assert again["id"] == opened["id"]
    await _ws(client, {"type": "prep_assistent/item/adjust", "item_id": opened["id"], "delta": -1})
    error = await _ws_error(client, {"type": "prep_assistent/item/open", "item_id": opened["id"]})
    assert error["translation_key"] == "not_in_stock"


# -------------------------------------------------------------- mehrfachauswahl


async def test_bulk_actions(hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: Any) -> None:
    client = await hass_ws_client(hass)
    manager = hass.data[DOMAIN]
    other = await _ws(client, {"type": "prep_assistent/list/create", "name": "Keller"})
    a = await _add(hass, name="A", quantity=0, target_quantity=2)
    b = await _add(hass, name="B", quantity=1, target_quantity=4, shelf_life_days=10)
    c = await _add(hass, name="C", quantity=1)

    res = await _ws(client, {"type": "prep_assistent/items/bulk", "item_ids": [a, b], "action": "update", "list_id": other["id"], "category": "haushalt", "location": "Regal"})
    assert res == {"count": 2}
    assert {(manager.items[i]["list_id"], manager.items[i]["category"], manager.items[i]["location"]) for i in (a, b)} == {(other["id"], "haushalt", "Regal")}

    await _ws(client, {"type": "prep_assistent/items/bulk", "item_ids": [a, b], "action": "buy"})
    assert (manager.items[a]["quantity"], manager.items[b]["quantity"], manager.items[b]["expiry_date"]) == (2, 4, _iso(10))

    error = await _ws_error(client, {"type": "prep_assistent/items/bulk", "item_ids": [c, "gibtsnicht"], "action": "delete"})
    assert error["translation_key"] == "item_not_found"
    assert c in manager.items  # nichts gelöscht, wenn eine ID fehlt
    await _ws(client, {"type": "prep_assistent/items/bulk", "item_ids": [a, c], "action": "delete"})
    assert set(manager.items) == {b}


# --------------------------------------------------------- kategorien & lagerorte


async def test_categories(hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: Any) -> None:
    client = await hass_ws_client(hass)
    manager = hass.data[DOMAIN]
    baby = await _ws(client, {"type": "prep_assistent/category/create", "name": "Baby & Kind", "icon": "mdi:baby-bottle"})
    assert baby == {"id": "baby_kind", "name": "Baby & Kind", "icon": "mdi:baby-bottle"}
    assert (await _ws(client, {"type": "prep_assistent/category/create", "name": "Baby Kind"}))["id"] == "baby_kind_2"

    item = await _add(hass, name="Windeln", category="baby_kind")
    renamed = await _ws(client, {"type": "prep_assistent/category/update", "category_id": "lebensmittel", "name": "Essen"})
    assert renamed["renamed"] is True

    await _ws(client, {"type": "prep_assistent/category/reorder", "category_ids": ["baby_kind", "getraenke"]})
    assert [c["id"] for c in manager.categories][:3] == ["baby_kind", "getraenke", "lebensmittel"]

    assert await _ws(client, {"type": "prep_assistent/category/delete", "category_id": "baby_kind"}) == {"moved": 1}
    assert manager.items[item]["category"] == "sonstiges"
    error = await _ws_error(client, {"type": "prep_assistent/category/delete", "category_id": "sonstiges"})
    assert error["translation_key"] == "category_protected"


async def test_locations(hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: Any) -> None:
    client = await hass_ws_client(hass)
    manager = hass.data[DOMAIN]
    a = await _add(hass, name="A", location="Keller")
    b = await _add(hass, name="B", location="keller")
    await _ws(client, {"type": "prep_assistent/location/create", "name": "Speisekammer"})
    assert (await _ws(client, {"type": "prep_assistent/data"}))["locations"] == ["Keller", "Speisekammer"]

    error = await _ws_error(client, {"type": "prep_assistent/location/create", "name": "KELLER"})
    assert error["translation_placeholders"] == {"location": "KELLER"}
    error = await _ws_error(client, {"type": "prep_assistent/location/rename", "old": "Keller", "new": "speisekammer"})
    assert error["translation_key"] == "location_exists"

    assert await _ws(client, {"type": "prep_assistent/location/rename", "old": "Keller", "new": "Vorratskeller"}) == {"changed": 2}
    assert {manager.items[a]["location"], manager.items[b]["location"]} == {"Vorratskeller"}
    assert await _ws(client, {"type": "prep_assistent/location/delete", "name": "vorratskeller"}) == {"cleared": 2}
    assert (await _ws(client, {"type": "prep_assistent/data"}))["locations"] == ["Speisekammer"]


async def test_old_storage_gets_new_fields(hass: HomeAssistant, hass_storage: dict, freezer: FrozenDateTimeFactory) -> None:
    hass_storage[DOMAIN] = {
        "version": 1,
        "key": DOMAIN,
        "data": {
            "lists": [{"id": "l1", "name": "Alt", "description": "", "created_at": "2026-01-01T00:00:00+00:00"}],
            "items": [{"id": "i1", "list_id": "l1", "name": "Reis", "category": "lebensmittel", "quantity": 1.0, "target_quantity": None, "unit": "kg", "purchase_date": None, "expiry_date": "2027-01-01", "location": "", "notes": "", "shelf_life_days": None, "created_at": "x", "updated_at": "x"}],
            "categories": [],
        },
    }
    entry = MockConfigEntry(domain=DOMAIN, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    item = hass.data[DOMAIN].items["i1"]
    assert (item["opened_date"], item["kcal_per_unit"]) == (None, None)
    assert hass.data[DOMAIN].supply_range(hass.data[DOMAIN].decorated_items())["days"] is None
