"""Tests der Mengenberechnung und des Vorlagen-Parsers (ohne Home Assistant)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.prep_assistent.calc import (
    TemplateError,
    build_item_list,
    calculate_quantity,
    load_templates,
    parse_template,
)

BUILTIN = Path(__file__).parents[1] / "custom_components" / "prep_assistent" / "templates"


@pytest.mark.parametrize(
    ("spec", "persons", "days", "expected"),
    [
        ({"per_person_per_day": 2}, 2, 10, 40),  # Wasser: 2 l * 2 P * 10 T
        ({"per_person_per_day": 0.35, "step": 0.5}, 3, 10, 10.5),
        ({"per_person_per_day": 0.35, "step": 0.5}, 1, 10, 3.5),
        ({"per_person_per_day": 0.25}, 1, 10, 3),  # 2.5 -> aufrunden auf 3
        ({"per_person_per_day": 0.25, "round": "down"}, 1, 10, 2),
        ({"per_person_per_day": 0.25, "round": "nearest"}, 1, 10, 3),
        ({"fixed": 1}, 5, 30, 1),
        ({"fixed": 8, "per_person": 4, "step": 4}, 3, 10, 20),
        ({"per_day": 0.5, "min": 2}, 1, 2, 2),
        ({"per_person": 0.25}, 5, 1, 2),  # ceil(1.25)
        ({"per_person": 0}, 5, 1, 0),
        ({"per_person_per_day": 20, "step": 50}, 2, 10, 400),
    ],
)
def test_calculate_quantity(spec: dict, persons: int, days: int, expected: float) -> None:
    assert calculate_quantity(spec, persons, days) == expected


def test_float_noise_does_not_round_up() -> None:
    # 0.1 * 3 = 0.30000000000000004 darf nicht auf 0.4 springen
    assert calculate_quantity({"per_person": 0.1, "step": 0.1}, 3, 1) == 0.3


def test_build_item_list_skips_zero() -> None:
    template = parse_template(
        {"name": "T", "items": [{"name": "A", "fixed": 1}, {"name": "B", "per_person": 0}]},
        "builtin",
        "t",
    )
    items = build_item_list(template, 2, 10)
    assert [i["name"] for i in items] == ["A"]
    assert items[0]["category"] == "sonstiges"
    assert items[0]["unit"] == "pcs"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"items": [{"name": "A", "fixed": 1}]}, "name"),
        ({"name": "T", "items": []}, "items"),
        ({"name": "T", "items": [{"fixed": 1}]}, "has no name"),
        ({"name": "T", "items": [{"name": "A"}]}, "at least"),
        ({"name": "T", "items": [{"name": "A", "fixed": "viel"}]}, "number"),
        ({"name": "T", "items": [{"name": "A", "fixed": 1, "round": "auf"}]}, "round"),
    ],
)
def test_parse_template_errors(raw: dict, message: str) -> None:
    with pytest.raises(TemplateError, match=message):
        parse_template(raw, "user", "t")


def test_builtin_templates_are_valid() -> None:
    templates, errors = load_templates([("builtin", BUILTIN)])
    assert errors == []
    assert {
        "bbk_notvorrat",
        "bbk_notvorrat_detail",
        "hausapotheke_basis",
        "hausapotheke_detail",
    } <= templates.keys()
    water = build_item_list(templates["bbk_notvorrat"], 2, 10)[0]
    assert (water["quantity"], water["unit"]) == (40, "l")


def test_user_templates_override_and_report_errors(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    (builtin / "a.json").write_text(json.dumps({"name": "Builtin", "items": [{"name": "X", "fixed": 1}]}))
    (user / "a.yaml").write_text("name: Eigene\nitems:\n  - name: Y\n    fixed: 2\n")
    (user / "kaputt.json").write_text("{nicht json")
    (user / "notes.txt").write_text("ignoriert")

    templates, errors = load_templates([("builtin", builtin), ("user", user)])

    assert templates["a"]["name"] == "Eigene"
    assert templates["a"]["source"] == "user"
    assert len(errors) == 1 and errors[0].startswith("kaputt.json")


def test_localized_template_fields() -> None:
    template = parse_template(
        {
            "name": {"de": "Vorrat", "en": "Supply"},
            "items": [
                {"name": {"de": "Nudeln", "en": "Pasta"}, "unit": "pack", "fixed": 1, "notes": {"de": "Notiz"}},
                {"name": "Kerzen", "unit": {"de": "Kartuschen", "en": "cartridges"}, "fixed": 2},
            ],
        },
        "builtin",
        "t",
    )
    de = build_item_list(template, 1, 1, "de", {"pack": "Pkg"})
    assert [(i["name"], i["unit"], i["notes"]) for i in de] == [("Nudeln", "Pkg", "Notiz"), ("Kerzen", "Kartuschen", "")]
    # Unbekannte Sprache -> Englisch, fehlende Übersetzung -> Deutsch
    fr = build_item_list(template, 1, 1, "fr-CA", {"pack": "paquets"})
    assert [(i["name"], i["unit"], i["notes"]) for i in fr] == [("Pasta", "paquets", "Notiz"), ("Kerzen", "cartridges", "")]
