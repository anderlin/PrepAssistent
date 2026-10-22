"""Datenhaltung, Ablaufprüfung und Vorlagen für PrepAssistent."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging
from pathlib import Path
from typing import Any
import uuid

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .calc import (
    INT_FIELDS,
    NUTRITION_FIELDS,
    build_item_list,
    calculate_quantity,
    load_templates,
    localize_item,
    slug,
    supply_range,
)
from .const import (
    CONF_HOUSEHOLD_PERSONS,
    CONF_KCAL_PER_DAY,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TIME,
    CONF_PERSISTENT_NOTIFICATION,
    CONF_WARNING_DAYS,
    CONF_WATER_PER_DAY,
    DEFAULT_CATEGORIES,
    DEFAULT_CATEGORY,
    DEFAULT_HOUSEHOLD_PERSONS,
    DEFAULT_KCAL_PER_DAY,
    DEFAULT_NOTIFY_TIME,
    DEFAULT_PERSISTENT_NOTIFICATION,
    DEFAULT_WARNING_DAYS,
    DEFAULT_WATER_PER_DAY,
    EVENT_EXPIRY,
    NOTIFICATION_ID,
    SAVE_DELAY,
    SIGNAL_UPDATED,
    STATUS_EXPIRED,
    STATUS_EXPIRING,
    STATUS_NONE,
    STATUS_OK,
    STORAGE_KEY,
    STORAGE_VERSION,
    USER_TEMPLATE_DIR,
)
from .i18n import Translator, localize, variants

_LOGGER = logging.getLogger(__name__)

ITEM_DEFAULTS: dict[str, Any] = {
    "category": DEFAULT_CATEGORY,
    "quantity": 0.0,
    "target_quantity": None,
    "unit": "Stk",
    "purchase_date": None,
    "expiry_date": None,
    "location": "",
    "notes": "",
    "shelf_life_days": None,
    "opened_date": None,
    "opened_shelf_life_days": None,
    "kcal_per_unit": None,
    "water_per_unit": None,
}
# Felder, die beim Öffnen auf die abgetrennte Charge übergehen
SPLIT_SKIP = ("id", "quantity", "target_quantity", "created_at", "updated_at")


class PrepError(ValueError):
    """Fachlicher Fehler, der dem Benutzer angezeigt wird.

    ``key`` verweist auf ``error.<key>`` in den Sprachdateien, ``params`` sind die Platzhalter.
    """

    def __init__(self, key: str, **params: Any) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


def _now_iso() -> str:
    return dt_util.utcnow().isoformat()


def _clean_optional_number(value: Any) -> Any:
    return None if value == "" else value


class PrepManager:
    """Verwaltet Listen, Artikel, Kategorien und Vorlagen."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.lists: dict[str, dict[str, Any]] = {}
        self.items: dict[str, dict[str, Any]] = {}
        self.categories: list[dict[str, Any]] = []
        self.locations: list[str] = []
        self.templates: dict[str, dict[str, Any]] = {}
        self.template_errors: list[str] = []
        self.translator = Translator()
        self._unsubs: list[CALLBACK_TYPE] = []

    # ------------------------------------------------------------------ setup

    @property
    def warning_days(self) -> int:
        return int(self.entry.options.get(CONF_WARNING_DAYS, DEFAULT_WARNING_DAYS))

    @property
    def household_persons(self) -> int:
        return int(self.entry.options.get(CONF_HOUSEHOLD_PERSONS, DEFAULT_HOUSEHOLD_PERSONS))

    @property
    def kcal_per_day(self) -> float:
        return float(self.entry.options.get(CONF_KCAL_PER_DAY, DEFAULT_KCAL_PER_DAY))

    @property
    def water_per_day(self) -> float:
        return float(self.entry.options.get(CONF_WATER_PER_DAY, DEFAULT_WATER_PER_DAY))

    @property
    def user_template_dir(self) -> Path:
        return Path(self.hass.config.path(USER_TEMPLATE_DIR))

    def tr(self, key: str, language: str | None = None, **params: Any) -> str:
        """Übersetzt in die angegebene Sprache, sonst in die Systemsprache von HA."""
        return self.translator.translate(language or self.hass.config.language, key, **params)

    def error_text(self, err: PrepError, language: str | None = None) -> str:
        return self.tr(f"error.{err.key}", language, **err.params)

    async def async_setup(self) -> None:
        self.translator = await self.hass.async_add_executor_job(Translator.load)
        data = await self._store.async_load()
        if data:
            self.lists = {lst["id"]: lst for lst in data.get("lists", [])}
            # Neue Felder älterer Datenstände mit Standardwerten ergänzen
            self.items = {item["id"]: {**ITEM_DEFAULTS, **item} for item in data.get("items", [])}
            self.categories = data.get("categories") or [dict(c) for c in DEFAULT_CATEGORIES]
            self.locations = data.get("locations", [])
        else:
            self.categories = [dict(c) for c in DEFAULT_CATEGORIES]
            self._add_list(self.tr("default_list"), "")
            self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

        await self.async_reload_templates()

        notify_time = time.fromisoformat(
            self.entry.options.get(CONF_NOTIFY_TIME, DEFAULT_NOTIFY_TIME)
        )
        self._unsubs.append(
            async_track_time_change(
                self.hass,
                self._async_daily_check,
                hour=notify_time.hour,
                minute=notify_time.minute,
                second=0,
            )
        )
        # Nach Mitternacht ändern sich Resttage -> Sensoren & Panel aktualisieren
        self._unsubs.append(
            async_track_time_change(self.hass, self._midnight, hour=0, minute=0, second=5)
        )

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data_to_save())

    @callback
    def _data_to_save(self) -> dict[str, Any]:
        return {
            "lists": list(self.lists.values()),
            "items": list(self.items.values()),
            "categories": self.categories,
            "locations": self.locations,
        }

    @callback
    def _changed(self) -> None:
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)

    @callback
    def _midnight(self, _now: datetime) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)

    # -------------------------------------------------------------- abfragen

    @staticmethod
    def today() -> date:
        return dt_util.now().date()

    @staticmethod
    def effective_expiry(item: dict[str, Any]) -> tuple[str | None, str | None]:
        """Maßgebliches Ablaufdatum und seine Quelle (``expiry`` oder ``opened``).

        Nach dem Öffnen gilt das frühere Datum aus Ablaufdatum und
        Öffnungsdatum + Haltbarkeit nach dem Öffnen.
        """
        expiry = item.get("expiry_date")
        opened, days = item.get("opened_date"), item.get("opened_shelf_life_days")
        if opened and days is not None:
            opened_expiry = (date.fromisoformat(opened) + timedelta(days=days)).isoformat()
            if not expiry or opened_expiry < expiry:
                return opened_expiry, "opened"
        return (expiry, "expiry") if expiry else (None, None)

    def decorate_item(self, item: dict[str, Any], today: date) -> dict[str, Any]:
        """Ergänzt Status, Resttage, maßgebliches Ablaufdatum und Fehlmenge."""
        out = dict(item)
        days_left: int | None = None
        status = STATUS_NONE
        expiry, source = self.effective_expiry(item)
        if expiry and item.get("quantity", 0) > 0:
            days_left = (date.fromisoformat(expiry) - today).days
            if days_left < 0:
                status = STATUS_EXPIRED
            elif days_left <= self.warning_days:
                status = STATUS_EXPIRING
            else:
                status = STATUS_OK
        target = item.get("target_quantity")
        out["effective_expiry"] = expiry
        out["expiry_source"] = source
        out["days_left"] = days_left
        out["status"] = status
        out["missing"] = round(max(target - item.get("quantity", 0), 0), 3) if target else 0
        out["list_name"] = self.lists.get(item["list_id"], {}).get("name", "")
        return out

    def decorated_items(self) -> list[dict[str, Any]]:
        today = self.today()
        return [self.decorate_item(item, today) for item in self.items.values()]

    def supply_range(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return supply_range(items, self.household_persons, self.kcal_per_day, self.water_per_day)

    def all_locations(self) -> list[str]:
        """Verwaltete Lagerorte plus alle, die bei Artikeln eingetragen sind."""
        names = {loc.lower(): loc for loc in self.locations}
        for item in self.items.values():
            if loc := (item.get("location") or "").strip():
                names.setdefault(loc.lower(), loc)
        return sorted(names.values(), key=str.lower)

    def as_dict(self) -> dict[str, Any]:
        items = self.decorated_items()
        return {
            "lists": sorted(self.lists.values(), key=lambda lst: lst["created_at"]),
            "items": items,
            "categories": self.categories,
            "locations": self.all_locations(),
            "range": self.supply_range(items),
            "list_ranges": {
                list_id: self.supply_range([i for i in items if i["list_id"] == list_id])
                for list_id in self.lists
            },
            "settings": {
                "warning_days": self.warning_days,
                "household_persons": self.household_persons,
                "kcal_per_day": self.kcal_per_day,
                "water_per_day": self.water_per_day,
                "user_template_dir": str(self.user_template_dir),
            },
            "today": self.today().isoformat(),
        }

    def summary(self) -> dict[str, Any]:
        items = self.decorated_items()

        def by_expiry(i: dict[str, Any]) -> Any:
            return i["days_left"]

        return {
            "stock": [i for i in items if i["quantity"] > 0],
            "expired": sorted((i for i in items if i["status"] == STATUS_EXPIRED), key=by_expiry),
            "expiring": sorted((i for i in items if i["status"] == STATUS_EXPIRING), key=by_expiry),
            "missing": [i for i in items if i["missing"] > 0],
            "dated": sorted((i for i in items if i["days_left"] is not None), key=by_expiry),
            "range": self.supply_range(items),
        }

    def default_list(self) -> dict[str, Any] | None:
        """Die zuerst angelegte Liste (Ziel für Artikel ohne Listenangabe)."""
        return min(self.lists.values(), key=lambda lst: lst["created_at"], default=None)

    def find_list(self, ref: str) -> dict[str, Any] | None:
        """Sucht eine Liste per ID oder Name (ohne Groß-/Kleinschreibung)."""
        if ref in self.lists:
            return self.lists[ref]
        ref_lower = ref.strip().lower()
        return next((lst for lst in self.lists.values() if lst["name"].lower() == ref_lower), None)

    # ---------------------------------------------------------------- listen

    def _add_list(self, name: str, description: str) -> dict[str, Any]:
        lst = {
            "id": uuid.uuid4().hex,
            "name": name,
            "description": description,
            "created_at": _now_iso(),
        }
        self.lists[lst["id"]] = lst
        return lst

    @callback
    def create_list(self, name: str, description: str = "") -> dict[str, Any]:
        lst = self._add_list(name, description)
        self._changed()
        return lst

    @callback
    def update_list(self, list_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        lst = self._get_list(list_id)
        lst.update(changes)
        self._changed()
        return lst

    @callback
    def delete_list(self, list_id: str) -> None:
        self._get_list(list_id)
        del self.lists[list_id]
        self.items = {k: v for k, v in self.items.items() if v["list_id"] != list_id}
        self._changed()

    def _get_list(self, list_id: str) -> dict[str, Any]:
        if list_id not in self.lists:
            raise PrepError("list_not_found")
        return self.lists[list_id]

    # --------------------------------------------------------------- artikel

    def _validate_item_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        fields = {k: _clean_optional_number(v) for k, v in fields.items()}
        if "category" in fields and not any(c["id"] == fields["category"] for c in self.categories):
            raise PrepError("unknown_category", category=fields["category"])
        if "list_id" in fields:
            self._get_list(fields["list_id"])
        return fields

    @staticmethod
    def _check_dates(item: dict[str, Any]) -> None:
        purchase, expiry = item.get("purchase_date"), item.get("expiry_date")
        if purchase and expiry and expiry < purchase:
            raise PrepError("expiry_before_purchase")

    def _add_item(self, list_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        now = _now_iso()
        item = {
            **ITEM_DEFAULTS,
            **fields,
            "id": uuid.uuid4().hex,
            "list_id": list_id,
            "created_at": now,
            "updated_at": now,
        }
        self.items[item["id"]] = item
        return item

    @callback
    def create_item(self, list_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        if "name" not in fields:
            raise PrepError("name_missing")
        fields = self._validate_item_fields({**fields, "list_id": list_id})
        self._check_dates(fields)
        item = self._add_item(fields.pop("list_id"), fields)
        self._changed()
        return item

    @callback
    def update_item(self, item_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        item = self._get_item(item_id)
        changes = self._validate_item_fields(changes)
        self._check_dates({**item, **changes})
        item.update(changes)
        item["updated_at"] = _now_iso()
        self._changed()
        return item

    @callback
    def adjust_item(self, item_id: str, delta: float) -> dict[str, Any]:
        item = self._get_item(item_id)
        return self.update_item(item_id, {"quantity": max(round(item["quantity"] + delta, 3), 0.0)})

    @callback
    def delete_item(self, item_id: str) -> None:
        self._get_item(item_id)
        del self.items[item_id]
        self._changed()

    def _get_item(self, item_id: str) -> dict[str, Any]:
        if item_id not in self.items:
            raise PrepError("item_not_found")
        return self.items[item_id]

    def _buy(self, item: dict[str, Any]) -> None:
        """Erfasst einen Artikel als gekauft: Soll-Menge, Kaufdatum, Ablaufdatum.

        Ohne Haltbarkeit ist das neue Ablaufdatum unbekannt; das alte gehört zum
        vorherigen Bestand und wird daher entfernt.
        """
        today = self.today()
        if item.get("target_quantity"):
            item["quantity"] = max(item["quantity"], item["target_quantity"])
        item["purchase_date"] = today.isoformat()
        item["opened_date"] = None
        if item.get("shelf_life_days"):
            item["expiry_date"] = (today + timedelta(days=item["shelf_life_days"])).isoformat()
        else:
            item["expiry_date"] = None
        item["updated_at"] = _now_iso()

    @callback
    def mark_bought(self, item_ids: list[str]) -> list[dict[str, Any]]:
        items = [self._get_item(item_id) for item_id in item_ids]
        for item in items:
            self._buy(item)
        self._changed()
        return items

    @callback
    def add_need(self, name: str, amount: float = 1) -> dict[str, Any]:
        """Setzt einen Artikel auf die Einkaufsliste (z. B. per Sprachbefehl).

        Gibt es den Artikel schon, steigt seine Soll-Menge um ``amount`` über den
        Bestand; sonst wird er in der ersten Liste mit Menge 0 angelegt.
        """
        name = name.strip()
        if not name:
            raise PrepError("name_missing")
        lower = name.lower()
        match = min(
            (i for i in self.items.values() if i["name"].lower() == lower),
            key=lambda i: i["created_at"],
            default=None,
        )
        if match:
            target = max(match.get("target_quantity") or 0, match["quantity"]) + amount
            match["target_quantity"] = round(target, 3)
            match["updated_at"] = _now_iso()
            self._changed()
            return match
        if (lst := self.default_list()) is None:
            raise PrepError("no_list")
        item = self._add_item(
            lst["id"],
            {"name": name, "quantity": 0.0, "target_quantity": amount, "unit": self.tr("unit.pcs")},
        )
        self._changed()
        return item

    @callback
    def clear_need(self, item_ids: list[str]) -> None:
        """Nimmt Artikel von der Einkaufsliste, ohne sie zu löschen (Soll = Bestand)."""
        items = [self._get_item(item_id) for item_id in item_ids]
        for item in items:
            item["target_quantity"] = item["quantity"] or None
            item["updated_at"] = _now_iso()
        self._changed()

    @callback
    def open_item(self, item_id: str) -> dict[str, Any]:
        """Markiert eine Einheit als geöffnet.

        Bei mehr als einer Einheit wird die geöffnete als eigene Charge abgetrennt,
        damit die übrigen ihr ursprüngliches Ablaufdatum behalten.
        """
        item = self._get_item(item_id)
        if item["quantity"] <= 0:
            raise PrepError("not_in_stock")
        today = self.today().isoformat()
        if item["quantity"] <= 1:
            item["opened_date"] = today
            item["updated_at"] = _now_iso()
            self._changed()
            return item
        item["quantity"] = round(item["quantity"] - 1, 3)
        item["updated_at"] = _now_iso()
        fields = {k: v for k, v in item.items() if k not in SPLIT_SKIP and k != "list_id"}
        opened = self._add_item(item["list_id"], {**fields, "quantity": 1.0, "opened_date": today})
        self._changed()
        return opened

    @callback
    def bulk_update(self, item_ids: list[str], changes: dict[str, Any]) -> int:
        """Ändert Liste, Kategorie oder Lagerort mehrerer Artikel auf einmal."""
        items = [self._get_item(item_id) for item_id in item_ids]
        changes = self._validate_item_fields(changes)
        now = _now_iso()
        for item in items:
            item.update(changes)
            item["updated_at"] = now
        self._changed()
        return len(items)

    @callback
    def bulk_delete(self, item_ids: list[str]) -> int:
        for item_id in item_ids:
            self._get_item(item_id)
        for item_id in item_ids:
            self.items.pop(item_id, None)
        self._changed()
        return len(item_ids)

    # ------------------------------------------------------------ kategorien

    def _get_category(self, category_id: str) -> dict[str, Any]:
        category = next((c for c in self.categories if c["id"] == category_id), None)
        if category is None:
            raise PrepError("unknown_category", category=category_id)
        return category

    @callback
    def create_category(self, name: str, icon: str = "") -> dict[str, Any]:
        known = {c["id"] for c in self.categories}
        base = slug(name, "kategorie")
        category_id, n = base, 2
        while category_id in known:
            category_id, n = f"{base}_{n}", n + 1
        category = {"id": category_id, "name": name, "icon": icon or "mdi:tag"}
        self.categories.append(category)
        self._changed()
        return category

    @callback
    def update_category(self, category_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        category = self._get_category(category_id)
        if "name" in changes and changes["name"] != category["name"]:
            category["name"] = changes["name"]
            # Standardkategorien zeigt das Panel übersetzt an – außer sie wurden umbenannt
            category["renamed"] = True
        if changes.get("icon"):
            category["icon"] = changes["icon"]
        self._changed()
        return category

    @callback
    def delete_category(self, category_id: str) -> int:
        """Löscht eine Kategorie; ihre Artikel wandern nach „Sonstiges“."""
        if category_id == DEFAULT_CATEGORY:
            raise PrepError("category_protected")
        self._get_category(category_id)
        self.categories = [c for c in self.categories if c["id"] != category_id]
        moved = 0
        for item in self.items.values():
            if item["category"] == category_id:
                item["category"] = DEFAULT_CATEGORY
                moved += 1
        self._changed()
        return moved

    @callback
    def reorder_categories(self, category_ids: list[str]) -> None:
        order = {cid: index for index, cid in enumerate(category_ids)}
        self.categories.sort(key=lambda c: order.get(c["id"], len(order)))
        self._changed()

    # ------------------------------------------------------------- lagerorte

    @callback
    def create_location(self, name: str) -> None:
        if name.lower() in {loc.lower() for loc in self.all_locations()}:
            raise PrepError("location_exists", location=name)
        self.locations.append(name)
        self._changed()

    @callback
    def rename_location(self, old: str, new: str) -> int:
        """Benennt einen Lagerort um – in der Verwaltung und bei allen Artikeln."""
        old_lower = old.lower()
        if new.lower() != old_lower and new.lower() in {loc.lower() for loc in self.all_locations()}:
            raise PrepError("location_exists", location=new)
        self.locations = [new if loc.lower() == old_lower else loc for loc in self.locations]
        if new not in self.locations:
            self.locations.append(new)
        changed = 0
        for item in self.items.values():
            if (item.get("location") or "").strip().lower() == old_lower:
                item["location"] = new
                changed += 1
        self._changed()
        return changed

    @callback
    def delete_location(self, name: str) -> int:
        """Entfernt einen Lagerort; betroffene Artikel verlieren den Eintrag."""
        lower = name.lower()
        self.locations = [loc for loc in self.locations if loc.lower() != lower]
        cleared = 0
        for item in self.items.values():
            if (item.get("location") or "").strip().lower() == lower:
                item["location"] = ""
                cleared += 1
        self._changed()
        return cleared

    # -------------------------------------------------------------- vorlagen

    async def async_reload_templates(self) -> None:
        builtin_dir = Path(__file__).parent / "templates"
        user_dir = self.user_template_dir

        def _load() -> tuple[dict[str, dict[str, Any]], list[str]]:
            user_dir.mkdir(parents=True, exist_ok=True)
            return load_templates([("builtin", builtin_dir), ("user", user_dir)])

        self.templates, self.template_errors = await self.hass.async_add_executor_job(_load)
        for error in self.template_errors:
            _LOGGER.warning("Vorlage konnte nicht geladen werden: %s", error)
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)

    def templates_overview(self, language: str | None = None) -> dict[str, Any]:
        lang = language or self.hass.config.language
        overview = [
            {
                "id": tpl["id"],
                "name": localize(tpl["name"], lang),
                "description": localize(tpl["description"], lang),
                "source": tpl["source"],
                "default_persons": tpl["default_persons"],
                "default_days": tpl["default_days"],
                "item_count": len(tpl["items"]),
            }
            for tpl in self.templates.values()
        ]
        return {
            "templates": sorted(overview, key=lambda t: t["name"].lower()),
            "errors": self.template_errors,
            "user_template_dir": str(self.user_template_dir),
        }

    def _get_template(self, template_id: str) -> dict[str, Any]:
        if template_id not in self.templates:
            raise PrepError("template_not_found", template=template_id)
        return self.templates[template_id]

    def preview_template(
        self, template_id: str, persons: int, days: int, language: str | None = None
    ) -> list[dict[str, Any]]:
        lang = language or self.hass.config.language
        return build_item_list(
            self._get_template(template_id), persons, days, lang, self.translator.units(lang)
        )

    def _unit_variants(self, unit: Any) -> set[str]:
        if isinstance(unit, str):
            return self.translator.unit_variants(unit)
        return variants(unit)

    @callback
    def apply_template(
        self,
        template_id: str,
        persons: int,
        days: int,
        list_id: str | None = None,
        list_name: str | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        """Übernimmt eine Vorlage als Soll-Mengen in eine (neue) Liste.

        Vorhandene Artikel gleichen Namens und gleicher Einheit erhalten die neue
        Soll-Menge, fehlende werden mit Menge 0 angelegt (= Einkaufsliste).
        Namen und Einheiten werden in allen Sprachvarianten verglichen, damit ein
        erneutes Übernehmen nach einem Sprachwechsel keine Duplikate erzeugt.
        """
        lang = language or self.hass.config.language
        template = self._get_template(template_id)
        units = self.translator.units(lang)

        known = {c["id"] for c in self.categories}
        for category in template["categories"]:
            if category["id"] not in known:
                self.categories.append(
                    {
                        "id": category["id"],
                        "name": category.get("name", category["id"]),
                        "icon": category.get("icon", "mdi:tag"),
                    }
                )
                known.add(category["id"])

        if list_id:
            lst = self._get_list(list_id)
        else:
            params = {
                "name": localize(template["name"], lang),
                "persons": self.tr("common.persons", lang, count=persons),
                "days": self.tr("common.days", lang, count=days),
            }
            lst = self._add_list(
                list_name or self.tr("templates.list_name", lang, **params),
                self.tr("templates.list_description", lang, **params),
            )

        existing = [item for item in self.items.values() if item["list_id"] == lst["id"]]
        created = updated = 0
        for spec in template["items"]:
            quantity = calculate_quantity(spec, persons, days)
            if quantity <= 0:
                continue
            names, unit_names = variants(spec["name"]), self._unit_variants(spec["unit"])
            match = next(
                (
                    item
                    for item in existing
                    if item["name"].lower() in names and item["unit"].lower() in unit_names
                ),
                None,
            )
            if match:
                match["target_quantity"] = quantity
                # Fehlende Zusatzangaben aus der Vorlage ergänzen, eigene Werte behalten
                for key in (*INT_FIELDS, *NUTRITION_FIELDS):
                    if match.get(key) is None and spec.get(key) is not None:
                        match[key] = spec[key]
                match["updated_at"] = _now_iso()
                updated += 1
                continue
            entry = localize_item(spec, quantity, lang, units)
            self._add_item(
                lst["id"],
                {
                    "name": entry["name"],
                    "category": entry["category"] if entry["category"] in known else DEFAULT_CATEGORY,
                    "unit": entry["unit"],
                    "quantity": 0.0,
                    "target_quantity": quantity,
                    "notes": entry["notes"],
                    **{key: entry[key] for key in (*INT_FIELDS, *NUTRITION_FIELDS)},
                },
            )
            created += 1

        self._changed()
        return {"list_id": lst["id"], "list_name": lst["name"], "created": created, "updated": updated}

    # --------------------------------------------------------- ablaufprüfung

    async def _async_daily_check(self, _now: datetime) -> None:
        await self.async_check_expiry()

    async def async_check_expiry(self) -> dict[str, Any]:
        """Prüft Ablaufdaten und benachrichtigt."""
        summary = self.summary()
        expired, expiring = summary["expired"], summary["expiring"]
        options = self.entry.options

        if not expired and not expiring:
            if options.get(CONF_PERSISTENT_NOTIFICATION, DEFAULT_PERSISTENT_NOTIFICATION):
                persistent_notification.async_dismiss(self.hass, NOTIFICATION_ID)
            return {"expired": 0, "expiring": 0}

        def brief(item: dict[str, Any]) -> dict[str, Any]:
            return {
                **{
                    key: item[key]
                    for key in ("id", "name", "list_name", "category", "quantity", "unit", "days_left")
                },
                "expiry_date": item["effective_expiry"],
                "opened": item["expiry_source"] == "opened",
            }

        self.hass.bus.async_fire(
            EVENT_EXPIRY,
            {
                "expired": [brief(i) for i in expired],
                "expiring": [brief(i) for i in expiring],
                "warning_days": self.warning_days,
            },
        )

        title, message = self._build_message(expired, expiring)
        if options.get(CONF_PERSISTENT_NOTIFICATION, DEFAULT_PERSISTENT_NOTIFICATION):
            persistent_notification.async_create(
                self.hass, message, title=title, notification_id=NOTIFICATION_ID
            )

        if notify_service := (options.get(CONF_NOTIFY_SERVICE) or "").strip():
            service = notify_service.removeprefix("notify.")
            if self.hass.services.has_service("notify", service):
                await self.hass.services.async_call(
                    "notify",
                    service,
                    {"title": title, "message": message, "data": {"tag": NOTIFICATION_ID}},
                    blocking=False,
                )
            else:
                _LOGGER.warning("Benachrichtigungsdienst notify.%s existiert nicht", service)

        return {"expired": len(expired), "expiring": len(expiring)}

    def _build_message(
        self, expired: list[dict[str, Any]], expiring: list[dict[str, Any]]
    ) -> tuple[str, str]:
        tr = self.tr
        parts = []
        if expired:
            parts.append(tr("notify.expired", count=len(expired)))
        if expiring:
            parts.append(tr("notify.expiring", count=len(expiring)))
        title = tr("notify.title", summary=", ".join(parts))

        def line(item: dict[str, Any]) -> str:
            days = item["days_left"]
            if days < 0:
                when = tr("expiry.expired_days_ago", count=-days)
            elif days == 0:
                when = tr("expiry.today")
            else:
                when = tr("expiry.days_left", count=days)
            qty = f"{item['quantity']:g} {item['unit']}".strip()
            return f"- **{item['name']}** ({qty}, {item['list_name']}): {when}"

        lines: list[str] = []
        if expired:
            lines += [f"**{tr('notify.heading_expired')}**", *(line(i) for i in expired[:20]), ""]
        if expiring:
            lines += [
                f"**{tr('notify.heading_expiring', count=self.warning_days)}**",
                *(line(i) for i in expiring[:20]),
            ]
        hidden = max(len(expired) - 20, 0) + max(len(expiring) - 20, 0)
        if hidden:
            lines.append(tr("notify.more", count=hidden))
        return title, "\n".join(lines).strip()
