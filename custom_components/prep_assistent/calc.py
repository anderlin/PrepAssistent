"""Vorlagen laden und Mengen berechnen.

Bewusst ohne Home-Assistant-Abhängigkeiten, damit die Logik isoliert testbar ist.

Mengenformel je Vorlagen-Artikel:

    menge = fixed
          + per_person * personen
          + per_day * tage
          + per_person_per_day * personen * tage

Danach wird auf ``step`` gerundet (``round``: up | nearest | down) und
mindestens ``min`` verwendet. Artikel mit Menge 0 entfallen.

Optionale Artikelangaben, die beim Übernehmen mitkopiert werden:
``shelf_life_days``, ``opened_shelf_life_days`` (Haltbarkeit nach dem Öffnen),
``kcal_per_unit`` und ``water_per_unit`` (Liter Trinkwasser je Einheit, für die
Reichweite).

Texte (``name``, ``description``, ``notes``) dürfen ein String oder ein
Sprach-Objekt (``{de: …, en: …}``) sein. ``unit`` darf zusätzlich ein
Einheiten-Code (``pcs``, ``can``, ``kg`` …) sein, der übersetzt wird.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any

from .i18n import localize

QUANTITY_KEYS = ("fixed", "per_person", "per_day", "per_person_per_day")
ROUND_MODES = ("up", "nearest", "down")
INT_FIELDS = ("shelf_life_days", "opened_shelf_life_days")
NUTRITION_FIELDS = ("kcal_per_unit", "water_per_unit")
TEMPLATE_SUFFIXES = (".json", ".yaml", ".yml")


class TemplateError(ValueError):
    """Ungültige Vorlage."""


def _number(spec: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = spec.get(key, default)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as err:
        raise TemplateError(f"'{key}' must be a number (item '{localize(spec.get('name'), 'en')}')") from err


def calculate_quantity(spec: dict[str, Any], persons: int, days: int) -> float:
    """Berechnet die Menge eines Vorlagen-Artikels."""
    qty = (
        _number(spec, "fixed")
        + _number(spec, "per_person") * persons
        + _number(spec, "per_day") * days
        + _number(spec, "per_person_per_day") * persons * days
    )
    if qty <= 0:
        return 0.0

    step = _number(spec, "step", 1.0)
    mode = spec.get("round", "up")
    if step > 0:
        units = qty / step
        if mode == "nearest":
            units = math.floor(units + 0.5)
        elif mode == "down":
            units = math.floor(units + 1e-9)
        else:
            units = math.ceil(units - 1e-9)
        qty = units * step

    qty = max(qty, _number(spec, "min"))
    return round(qty, 3)


def localize_item(
    spec: dict[str, Any], quantity: float, language: str | None, units: dict[str, str] | None = None
) -> dict[str, Any]:
    """Berechneten Artikel in der gewünschten Sprache aufbereiten."""
    unit = spec["unit"]
    if isinstance(unit, str):
        unit = (units or {}).get(unit, unit)
    return {
        "name": localize(spec["name"], language or ""),
        "category": spec["category"],
        "unit": localize(unit, language or ""),
        "quantity": quantity,
        "notes": localize(spec.get("notes", ""), language or ""),
        **{key: spec.get(key) for key in (*INT_FIELDS, *NUTRITION_FIELDS)},
    }


def build_item_list(
    template: dict[str, Any],
    persons: int,
    days: int,
    language: str | None = None,
    units: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Berechnet alle Artikel einer Vorlage für Personen/Tage."""
    result: list[dict[str, Any]] = []
    for spec in template["items"]:
        qty = calculate_quantity(spec, persons, days)
        if qty > 0:
            result.append(localize_item(spec, qty, language, units))
    return result


def supply_range(
    items: list[dict[str, Any]], persons: int, kcal_per_day: float, water_per_day: float
) -> dict[str, Any]:
    """Wie viele Tage reicht der Vorrat für ``persons`` Personen?

    Gezählt werden vorrätige, nicht abgelaufene Artikel mit ``kcal_per_unit``
    bzw. ``water_per_unit``. Die Gesamtreichweite ist das Minimum aus Nahrung und
    Wasser; fehlen Angaben für einen der beiden Werte, zählt nur der andere.
    """
    kcal = water = 0.0
    for item in items:
        quantity = item.get("quantity") or 0
        if quantity <= 0 or item.get("status") == "expired":
            continue
        kcal += quantity * (item.get("kcal_per_unit") or 0)
        water += quantity * (item.get("water_per_unit") or 0)

    def days(total: float, per_day: float) -> float | None:
        if total <= 0 or per_day <= 0 or persons <= 0:
            return None
        return round(total / (persons * per_day), 1)

    food_days, water_days = days(kcal, kcal_per_day), days(water, water_per_day)
    known = [d for d in (food_days, water_days) if d is not None]
    return {
        "days": min(known) if known else None,
        "food_days": food_days,
        "water_days": water_days,
        "kcal": round(kcal),
        "water": round(water, 1),
        "persons": persons,
        "kcal_per_day": kcal_per_day,
        "water_per_day": water_per_day,
    }


def _text(value: Any) -> Any:
    """Normalisiert einen String oder ein Sprach-Objekt; leere Werte -> None."""
    if isinstance(value, dict):
        cleaned = {str(k): str(v).strip() for k, v in value.items() if v is not None and str(v).strip()}
        return cleaned or None
    if value is None:
        return None
    return str(value).strip() or None


def slug(value: str, fallback: str = "vorlage") -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or fallback


def parse_template(raw: Any, source: str, fallback_id: str) -> dict[str, Any]:
    """Validiert und normalisiert eine Vorlage."""
    if not isinstance(raw, dict):
        raise TemplateError("template must be an object")
    name = _text(raw.get("name"))
    if name is None:
        raise TemplateError("'name' is missing")
    raw_items = raw.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise TemplateError("'items' must be a non-empty list")

    items: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_items, start=1):
        item_name = _text(raw_item.get("name")) if isinstance(raw_item, dict) else None
        if item_name is None:
            raise TemplateError(f"item #{index} has no name")
        item = dict(raw_item)
        item["name"] = item_name
        label = localize(item_name, "en")
        item["category"] = str(item.get("category") or "sonstiges")
        item["unit"] = _text(item.get("unit")) or "pcs"
        if item.get("notes") is not None:
            item["notes"] = _text(item["notes"]) or ""
        if item.get("round", "up") not in ROUND_MODES:
            raise TemplateError(f"'round' of '{label}' must be up, nearest or down")
        if not any(key in item for key in QUANTITY_KEYS):
            raise TemplateError(f"'{label}' needs at least one of {', '.join(QUANTITY_KEYS)}")
        for key in (*QUANTITY_KEYS, "step", "min"):
            _number(item, key)
        for key in INT_FIELDS:
            if item.get(key) is not None:
                item[key] = int(_number(item, key))
        for key in NUTRITION_FIELDS:
            if item.get(key) is not None:
                item[key] = _number(item, key)
        items.append(item)

    categories = raw.get("categories") or []
    if not isinstance(categories, list):
        raise TemplateError("'categories' must be a list")

    return {
        "id": slug(str(raw.get("id") or fallback_id)),
        "name": name,
        "description": _text(raw.get("description")) or "",
        "default_persons": int(raw.get("default_persons", 2)),
        "default_days": int(raw.get("default_days", 10)),
        "categories": [c for c in categories if isinstance(c, dict) and c.get("id")],
        "items": items,
        "source": source,
    }


def _read_file(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    import yaml  # noqa: PLC0415 - nur bei YAML-Vorlagen nötig

    return yaml.safe_load(text)


def load_templates(
    directories: list[tuple[str, Path]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Lädt Vorlagen aus (quelle, ordner)-Paaren.

    Spätere Ordner überschreiben frühere bei gleicher ID (eigene vor mitgelieferten).
    Gibt die Vorlagen und eine Liste von Fehlermeldungen zurück.
    """
    templates: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for source, directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix not in TEMPLATE_SUFFIXES or path.name.startswith("."):
                continue
            try:
                template = parse_template(_read_file(path), source, path.stem)
            except Exception as err:  # noqa: BLE001 - IO-, JSON-, YAML- und Vorlagenfehler
                errors.append(f"{path.name}: {err}")
                continue
            templates[template["id"]] = template
    return templates, errors
