"""Übersetzungen für Backend-Texte (Benachrichtigungen, Fehler, Listennamen).

Quelle sind dieselben Sprachdateien, die auch das Panel lädt
(``frontend/i18n/<sprache>.json``). Bewusst ohne Home-Assistant-Abhängigkeiten.

Pluralformen sind Objekte mit CLDR-Kategorien (``one``, ``few``, ``many``,
``other``) und werden über den Platzhalter ``count`` ausgewählt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

I18N_DIR = Path(__file__).parent / "frontend" / "i18n"
LANGUAGES = ("de", "en", "fr", "es", "it", "ru", "da", "nb", "sv", "hu", "el")
FALLBACK_LANGUAGE = "en"
# Norwegisch: HA kennt "nb" und "nn", Browser liefern teils "no"
LANGUAGE_ALIASES = {"no": "nb", "nn": "nb"}


def resolve_language(language: str | None) -> str:
    """Bildet eine HA-/Browser-Sprache (z. B. ``en-GB``) auf eine unterstützte ab."""
    if not language:
        return FALLBACK_LANGUAGE
    lang = language.replace("_", "-").lower()
    for candidate in (lang, lang.split("-")[0]):
        candidate = LANGUAGE_ALIASES.get(candidate, candidate)
        if candidate in LANGUAGES:
            return candidate
    return FALLBACK_LANGUAGE


def plural_category(language: str, count: float) -> str:
    """CLDR-Pluralkategorie für ganze Zahlen der unterstützten Sprachen."""
    if count != int(count):
        return "other"
    n = abs(int(count))
    if language == "ru":
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    if language == "fr":
        return "one" if n in (0, 1) else "other"
    return "one" if n == 1 else "other"


def localize(value: Any, language: str) -> str:
    """Wählt aus einem Sprach-Objekt (``{de: …, en: …}``) den passenden Text.

    Reihenfolge: gewünschte Sprache → Englisch → Deutsch → erster Eintrag.
    Einfache Strings werden unverändert zurückgegeben.
    """
    if isinstance(value, dict):
        if not value:
            return ""
        lang = resolve_language(language)
        for key in (lang, FALLBACK_LANGUAGE, "de"):
            if value.get(key):
                return str(value[key])
        return str(next(iter(value.values())))
    return "" if value is None else str(value)


def variants(value: Any) -> set[str]:
    """Alle Sprachvarianten eines Textes (klein geschrieben) – für Namensvergleiche."""
    if isinstance(value, dict):
        return {str(v).lower() for v in value.values() if v}
    return {str(value).lower()} if value else set()


def _format(text: str, params: dict[str, Any]) -> str:
    for key, value in params.items():
        text = text.replace(f"{{{key}}}", str(value))
    return text


class Translator:
    """Lädt alle Sprachdateien und übersetzt Schlüssel wie ``error.list_not_found``."""

    def __init__(self, strings: dict[str, dict[str, Any]] | None = None) -> None:
        self.strings: dict[str, dict[str, Any]] = strings or {}

    @classmethod
    def load(cls, directory: Path = I18N_DIR) -> Translator:
        """Liest alle Sprachdateien (blockierend – im Executor aufrufen)."""
        strings = {}
        for lang in LANGUAGES:
            path = directory / f"{lang}.json"
            if path.is_file():
                strings[lang] = json.loads(path.read_text(encoding="utf-8"))
        return cls(strings)

    def _lookup(self, language: str, key: str) -> Any:
        node: Any = self.strings.get(language, {})
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def translate(self, language: str | None, key: str, **params: Any) -> str:
        lang = resolve_language(language)
        value = self._lookup(lang, key)
        if value is None:
            lang = FALLBACK_LANGUAGE
            value = self._lookup(lang, key)
        if value is None:
            return key
        if isinstance(value, dict):
            count = params.get("count", 0)
            value = value.get(plural_category(lang, count)) or value.get("other", key)
        return _format(str(value), params)

    def units(self, language: str | None) -> dict[str, str]:
        """Einheiten-Codes (``pcs``, ``can`` …) → Bezeichnung in der Sprache."""
        lang = resolve_language(language)
        return {**self.strings.get(FALLBACK_LANGUAGE, {}).get("unit", {}), **self.strings.get(lang, {}).get("unit", {})}

    def unit_variants(self, code: str) -> set[str]:
        """Alle Bezeichnungen eines Einheiten-Codes in allen Sprachen."""
        found = {code.lower()}
        for strings in self.strings.values():
            if label := strings.get("unit", {}).get(code):
                found.add(label.lower())
        return found
