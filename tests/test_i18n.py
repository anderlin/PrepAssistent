"""Tests der Übersetzungen: Sprachdateien, Pluralregeln und Vollständigkeit der Vorlagen."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import pytest

from custom_components.prep_assistent.calc import load_templates
from custom_components.prep_assistent.i18n import (
    I18N_DIR,
    LANGUAGES,
    Translator,
    plural_category,
    resolve_language,
)

COMPONENT = Path(__file__).parents[1] / "custom_components" / "prep_assistent"
PLURAL_KEYS = {"zero", "one", "two", "few", "many", "other"}
REQUIRED_PLURALS = {"ru": {"one", "few", "many", "other"}}
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _load(lang: str) -> dict[str, Any]:
    return json.loads((I18N_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def _leaves(node: Any, prefix: str = "") -> dict[str, Any]:
    """Pfad -> Text bzw. Plural-Objekt."""
    if isinstance(node, dict) and not (node.keys() <= PLURAL_KEYS):
        out: dict[str, Any] = {}
        for key, value in node.items():
            out.update(_leaves(value, f"{prefix}{key}."))
        return out
    return {prefix.rstrip("."): node}


def _placeholders(value: Any) -> set[str]:
    texts = value.values() if isinstance(value, dict) else [value]
    return {p for text in texts for p in PLACEHOLDER.findall(text)}


@pytest.mark.parametrize("lang", LANGUAGES)
def test_language_file_matches_english(lang: str) -> None:
    reference = _leaves(_load("en"))
    strings = _leaves(_load(lang))
    assert strings.keys() == reference.keys()
    for key, value in strings.items():
        ref = reference[key]
        assert isinstance(value, dict) == isinstance(ref, dict), key
        if isinstance(value, dict):
            assert {"one", "other"} | REQUIRED_PLURALS.get(lang, set()) <= value.keys(), key
        # Keine Platzhalter erfinden; Pluralformen dürfen {count} weglassen ("am nächsten Tag")
        assert _placeholders(value) <= _placeholders(ref), key
        if not isinstance(value, dict):
            assert _placeholders(value) == _placeholders(ref), key


@pytest.mark.parametrize(
    ("language", "expected"),
    [("de", "de"), ("en-GB", "en"), ("pt-BR", "en"), ("nb", "nb"), ("nn", "nb"), ("no", "nb"), ("el", "el"), (None, "en"), ("zh_Hans", "en")],
)
def test_resolve_language(language: str | None, expected: str) -> None:
    assert resolve_language(language) == expected


@pytest.mark.parametrize(
    ("lang", "count", "expected"),
    [("ru", 1, "one"), ("ru", 3, "few"), ("ru", 5, "many"), ("ru", 11, "many"), ("ru", 21, "one"), ("ru", 22, "few"), ("ru", 112, "many"),
     ("fr", 0, "one"), ("fr", 2, "other"), ("de", 1, "one"), ("de", 0, "other"), ("hu", 1, "one")],
)
def test_plural_category(lang: str, count: int, expected: str) -> None:
    assert plural_category(lang, count) == expected


def test_translator() -> None:
    tr = Translator.load()
    assert tr.translate("de", "expiry.days_left", count=1) == "noch 1 Tag"
    assert tr.translate("de", "expiry.days_left", count=5) == "noch 5 Tage"
    assert tr.translate("ru", "expiry.days_left", count=5) == "ещё 5 дней"
    assert tr.translate("xx", "error.unknown_category", category="foo") == "Unknown category: foo"
    assert tr.translate("de", "does.not.exist") == "does.not.exist"
    assert tr.units("sv")["can"] == "burkar"
    assert {"stk", "pcs", "шт.", "τεμ."} <= tr.unit_variants("pcs")


def test_builtin_templates_are_fully_translated() -> None:
    templates, errors = load_templates([("builtin", COMPONENT / "templates")])
    assert errors == []
    unit_codes = set(_load("en")["unit"])

    def check(value: Any, where: str) -> None:
        assert isinstance(value, dict), where
        assert set(value) == set(LANGUAGES), (where, set(LANGUAGES) ^ set(value))

    for tpl in templates.values():
        check(tpl["name"], tpl["id"])
        check(tpl["description"], tpl["id"])
        for item in tpl["items"]:
            where = f"{tpl['id']}: {item['name']}"
            check(item["name"], where)
            if item.get("notes"):
                check(item["notes"], where)
            if isinstance(item["unit"], dict):
                check(item["unit"], where)
            else:
                assert item["unit"] in unit_codes, where
