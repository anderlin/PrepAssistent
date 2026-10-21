# PrepAssistent

Home-Assistant-Integration zum Anlegen und Verwalten von Vorratskammern: Lebensmittel, Getränke, Hausapotheke, Drogerie & Co. – mit Ablaufwarnungen, Dashboard und Vorlagen, die Einkaufslisten für eine beliebige Zahl von Personen und Tagen automatisch berechnen.

## Funktionen

- **Mehrere Vorratslisten** (z. B. „Keller“, „Hausapotheke“, „Notvorrat“)
- **Artikel** mit Kategorie, Menge, Soll-Menge, Einheit, Lagerort, Notizen, **Anschaffungsdatum** und **Ablaufdatum**
- **Chargen**: Gleicher Artikel mehrfach mit unterschiedlichen Ablaufdaten („Duplizieren“)
- **Geöffnet am**: Eine Einheit als geöffnet markieren – sie wird als eigene Charge abgetrennt, mit „nach dem Öffnen haltbar (Tage)“ gilt das frühere Ablaufdatum
- **Reichweite**: Wie viele Tage reichen Nahrung (kcal) und Trinkwasser für den Haushalt? Als Karte in der Übersicht, pro Liste und als Sensor
- **Einkaufsliste in HA**: fehlende Artikel als To-do-Liste – abhaken bucht ein, per Sprachassistent hinzufügen
- **Mehrfachauswahl**: mehrere Artikel auf einmal als gekauft erfassen, verschieben, Kategorie/Lagerort setzen oder löschen
- **Verwalten**: eigene Kategorien (Name, Icon, Reihenfolge) und Lagerorte (umbenennen, löschen, als Filter)
- **Lovelace-Karte** `custom:prep-assistent-card` für eigene Dashboards
- **Ablaufwarnungen**: tägliche Prüfung zur eingestellten Uhrzeit → HA-Benachrichtigung, optionale Push-Nachricht (`notify.*`) und Event `prep_assistent_expiry` für eigene Automationen
- **Dashboard** in der Seitenleiste: Kennzahlen, „Ablauf im Blick“, Kategorien, Listen mit Erfüllungsgrad
- **Vorlagen** (JSON/YAML): Personen und Tage wählen → Mengen werden berechnet → als Einkaufsliste übernehmen
- **Einkaufsliste**: Filter auf fehlende Mengen, „Als gekauft erfassen“ setzt Menge, Kaufdatum und (falls hinterlegt) Ablaufdatum
- **Sensoren** für eigene Dashboards/Automationen
- **Services** für Automationen und Sprachassistenten
- **Mehrsprachig**: Deutsch, Englisch, Französisch, Spanisch, Italienisch, Russisch, Dänisch, Norwegisch, Schwedisch, Ungarisch, Griechisch

## Sprachen

| Bereich | Sprache |
| --- | --- |
| Panel (Oberfläche, Datums- und Zahlenformat) | Sprache des angemeldeten HA-Benutzers |
| Vorlagen-Vorschau und übernommene Artikel | Sprache des Benutzers, der die Vorlage übernimmt |
| Benachrichtigungen, Name der ersten Liste, Service-Fehler | Systemsprache von Home Assistant |
| Einrichtung, Sensoren, Services | HA-Übersetzungen (`translations/`) |

Nicht unterstützte Sprachen fallen auf Englisch zurück. Bereits angelegte Artikel und Listen behalten ihren Namen – beim erneuten Übernehmen einer Vorlage werden sie aber auch nach einem Sprachwechsel wiedererkannt.

Die Texte des Panels und des Backends liegen in `custom_components/prep_assistent/frontend/i18n/<sprache>.json`. Für eine neue Sprache die Datei `en.json` kopieren, übersetzen und den Sprachcode in `i18n.py` (`LANGUAGES`) und im Panel (`LANGUAGES`) ergänzen. Pluralformen sind Objekte mit den [CLDR-Kategorien](https://cldr.unicode.org/index/cldr-spec/plural-rules) (`one`, `few`, `many`, `other`).

## Installation

### HACS (benutzerdefiniertes Repository)

1. HACS → Integrationen → ⋮ → *Benutzerdefinierte Repositories* → Repository-URL eintragen, Typ *Integration*
2. „PrepAssistent“ installieren, Home Assistant neu starten
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → PrepAssistent*

### Manuell

Den Ordner `custom_components/prep_assistent` nach `<config>/custom_components/` kopieren, HA neu starten und die Integration hinzufügen.

Voraussetzung: Home Assistant **2025.2** oder neuer.

## Einstellungen

| Option | Bedeutung | Standard |
| --- | --- | --- |
| Warnvorlauf | Ab wie vielen Tagen vor Ablauf ein Artikel als „läuft bald ab“ gilt | 30 |
| Uhrzeit der täglichen Prüfung | Wann gewarnt wird | 08:00 |
| Benachrichtigung in HA | Dauerhafte Benachrichtigung in der HA-Oberfläche | an |
| Push-Benachrichtigungsdienst | z. B. `notify.mobile_app_mein_handy` | leer |
| Personen im Haushalt | Grundlage der Reichweite (im Panel temporär änderbar) | 2 |
| Energiebedarf pro Person und Tag | für die Reichweite der Nahrung | 2200 kcal |
| Trinkwasser pro Person und Tag | für die Reichweite des Wassers | 2 l |

## Einkaufsliste (To-do)

Die Entität `todo.prepassistent_einkaufsliste` (Name je nach Systemsprache) enthält alle Artikel, deren Menge unter der Soll-Menge liegt, z. B. „Reis (2 kg)“ mit Liste und Lagerort als Beschreibung. Sie erscheint in *Einstellungen → To-do-Listen*, in der HA-App und kann mit der To-do-Karte auf Dashboards gezeigt werden.

| Aktion | Wirkung |
| --- | --- |
| Abhaken | Als gekauft erfasst: Menge = Soll-Menge, Kaufdatum heute, Ablaufdatum aus „Haltbarkeit ab Kauf“ |
| Hinzufügen (auch per Assist: „Füge Kaffee zur Einkaufsliste hinzu“) | Bekannter Artikel: Soll-Menge +1 über Bestand. Neuer Artikel: wird in der ersten Liste mit Menge 0 und Soll 1 angelegt |
| Entfernen | Nur der Bedarf entfällt (Soll = Bestand), der Artikel bleibt erhalten |

## Reichweite

Bei jedem Artikel lassen sich unter *Weitere Angaben* **kcal pro Einheit** und **Liter Trinkwasser pro Einheit** hinterlegen (Beispiel: Reis in kg → 3500 kcal, Mineralwasser in l → 1). Die Notvorrat-Vorlagen bringen diese Werte mit.

```
Reichweite Nahrung = Σ Menge × kcal pro Einheit ÷ (Personen × kcal pro Tag)
Reichweite Wasser  = Σ Menge × Liter pro Einheit ÷ (Personen × Liter pro Tag)
Reichweite         = Minimum aus beiden (fehlen Angaben für einen Wert, zählt nur der andere)
```

Abgelaufene Artikel zählen nicht mit. Die Übersicht zeigt die Reichweite für die eingestellte Haushaltsgröße; die Personenzahl lässt sich dort zum Durchspielen ändern.

## Lovelace-Karte

Die Karte wird automatisch geladen (keine Ressource nötig) und erscheint im Kartenauswahldialog als „PrepAssistent“. Alle Optionen sind im visuellen Editor einstellbar:

```yaml
type: custom:prep-assistent-card
title: Vorrat            # optional
list: Keller             # optional: Name oder ID einer Liste, leer = alle Listen
show_stats: true         # Kennzahlen
show_range: true         # Reichweite
show_attention: true     # Ablauf im Blick
show_shopping: true      # Einkaufsliste mit Abhaken
max_items: 5             # Einträge je Bereich
```

## Vorlagen

Mitgelieferte Beispielvorlagen liegen in `custom_components/prep_assistent/templates/`.
**Eigene Vorlagen** gehören nach `<config>/prep_assistent/templates/` (wird beim ersten Start angelegt) und bleiben bei Updates erhalten. Eine eigene Vorlage mit gleicher `id` ersetzt eine mitgelieferte. Nach Änderungen im Tab *Vorlagen* auf „Neu laden“ klicken.

### Format

```yaml
id: notvorrat_familie          # optional, sonst Dateiname
name: Notvorrat Familie        # oder mehrsprachig, siehe unten
description: Kurzbeschreibung
default_persons: 4             # Vorbelegung im Dialog
default_days: 14
categories:                    # optional: zusätzliche Kategorien
  - id: baby
    name: Babybedarf
    icon: mdi:baby-bottle
items:
  - name: Trinkwasser
    category: getraenke
    unit: l
    per_person_per_day: 2      # 2 l pro Person und Tag
    shelf_life_days: 365       # optional: Vorschlag fürs Ablaufdatum beim Kauf
    water_per_unit: 1          # optional: Liter Trinkwasser je Einheit (Reichweite)
  - name: Reis
    category: lebensmittel
    unit: kg
    per_person_per_day: 0.1
    step: 0.5                  # auf 0,5 kg aufrunden
    kcal_per_unit: 3500        # optional: kcal je Einheit (Reichweite)
  - name: Erste-Hilfe-Set
    category: hausapotheke
    unit: pcs                  # Einheiten-Code, wird übersetzt (Stk, pcs, шт. …)
    fixed: 1                   # unabhängig von Personen/Tagen
  - name: Windeln
    category: baby
    unit: pcs
    per_day: 6
    notes: nur bei Kleinkind
```

### Mehrsprachige Vorlagen

`name`, `description`, `notes` und `unit` dürfen statt eines Strings ein Sprach-Objekt sein. Angezeigt wird die Sprache des Benutzers, sonst Englisch, sonst Deutsch:

```yaml
name: {de: "Notvorrat", en: "Emergency supply", fr: "Réserve d'urgence"}
items:
  - name: {de: "Trockenfleisch", en: "Dried meat", sv: "Torkat kött"}
    unit: kg
    per_person_per_day: 0.01
    notes:
      de: Vakuumverpackt kaufen
      en: Buy vacuum-packed
```

**Einheiten-Codes** (werden automatisch übersetzt): `pcs`, `kg`, `g`, `l`, `ml`, `pack`, `can`, `jar`, `bottle`, `roll`, `tube`, `bar`, `box`, `pair`, `bag`, `folder`, `daily_dose`, `eur`. Jeder andere Text wird unverändert übernommen.

### Berechnung

```
Menge = fixed + per_person × Personen + per_day × Tage + per_person_per_day × Personen × Tage
```

Danach wird auf `step` gerundet (Standard `1`, `round`: `up` (Standard) | `nearest` | `down`) und mindestens `min` verwendet. Positionen mit Menge 0 entfallen.

Beispiele: `per_person: 0.25` mit Standard-Rundung → 1 Stück je angefangene 4 Personen. `fixed: 8, per_person: 4, step: 4` → Batterien in 4er-Packs.

Weitere optionale Felder je Artikel: `opened_shelf_life_days` (nach dem Öffnen haltbar, Tage). `shelf_life_days`, `opened_shelf_life_days`, `kcal_per_unit` und `water_per_unit` werden beim Übernehmen in die Artikel kopiert; bei bestehenden Artikeln nur, wenn dort noch kein Wert eingetragen ist.

Kategorie-IDs (Standard): `lebensmittel`, `getraenke`, `hausapotheke`, `drogerie`, `haushalt`, `dokumente`, `tiere`, `sonstiges`.

Beim Übernehmen in eine **bestehende** Liste erhalten Artikel mit gleichem Namen und gleicher Einheit die neue Soll-Menge; alle anderen werden mit Menge 0 als Einkaufsposition angelegt.

## Sensoren

| Entität | Inhalt |
| --- | --- |
| Artikel auf Lager | Anzahl Artikel mit Menge > 0 |
| Läuft bald ab | Anzahl, Attribut `items` |
| Abgelaufen | Anzahl, Attribut `items` |
| Fehlende Artikel | Anzahl Artikel unter Soll-Menge, Attribut `items` |
| Nächstes Ablaufdatum | Datum, Attribute zum Artikel |
| Reichweite | Tage (Minimum aus Nahrung und Wasser), Attribute `kcal`, `water`, `persons` … |
| Reichweite Nahrung / Wasser | Tage je Bereich |
| Einkaufsliste (`todo`) | Anzahl fehlender Artikel, siehe oben |

Ablaufdaten in Sensoren und Events sind die maßgeblichen Daten – bei geöffneten Artikeln das Datum „geöffnet + haltbar nach dem Öffnen“, falls es früher liegt (Attribut `opened: true`).

## Services

| Service | Zweck |
| --- | --- |
| `prep_assistent.add_item` | Artikel anlegen (Liste per Name oder ID) |
| `prep_assistent.consume_item` | Bestand reduzieren – per Name wird die zuerst ablaufende Charge genommen |
| `prep_assistent.apply_template` | Vorlage berechnen und übernehmen |
| `prep_assistent.check_expiry` | Ablaufprüfung sofort ausführen |
| `prep_assistent.reload_templates` | Vorlagendateien neu laden |

### Beispiel-Automation: Push bei Ablaufwarnung

```yaml
triggers:
  - trigger: event
    event_type: prep_assistent_expiry
actions:
  - action: notify.mobile_app_mein_handy
    data:
      title: "Vorrat prüfen"
      message: >
        {{ trigger.event.data.expired | count }} abgelaufen,
        {{ trigger.event.data.expiring | count }} laufen bald ab.
```

## Entwicklung

### Lokal ausprobieren (Docker)

```bash
docker compose up -d          # startet HA auf http://localhost:8123
docker compose restart        # nach Python-Änderungen
docker compose logs -f        # Logs (PrepAssistent auf debug)
docker compose down           # stoppen
```

Der Integrationsordner wird direkt in den Container eingebunden, die HA-Konfiguration liegt in `.dev/config/`. Beim ersten Start einen Benutzer anlegen, dann *Einstellungen → Geräte & Dienste → Integration hinzufügen → PrepAssistent*. Änderungen am Panel (JS) brauchen nur einen Browser-Reload ohne Cache (Cmd+Shift+R).

### Tests

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/pytest
```

Das Panel (`frontend/prep-assistent-panel.js`) ist ein Web Component ohne Build-Schritt. Daten laufen über die WebSocket-API (`prep_assistent/*`), Änderungen werden live an alle offenen Panels verteilt.

> Die mitgelieferten Vorlagen sind Beispiele (angelehnt an die Empfehlungen des BBK) und ersetzen keine individuelle Planung.
