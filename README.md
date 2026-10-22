# PrepAssistent

Home Assistant integration for creating and managing stockpiles: food, drinks, first aid supplies, toiletries and more – with expiry warnings, a dashboard, and templates that automatically calculate shopping lists for any number of people and days.

## Features

- **Multiple stock lists** (e.g. "Basement", "Medicine cabinet", "Emergency supply")
- **Items** with category, quantity, target quantity, unit, storage location, notes, **purchase date** and **expiry date**
- **Batches**: the same item several times with different expiry dates ("Duplicate")
- **Opened on**: mark one unit as opened – it is split off as its own batch; with "use within after opening (days)" the earlier expiry date applies
- **Supply range**: how many days will food (kcal) and drinking water last for your household? Shown as a card in the overview, per list and as a sensor
- **Shopping list in HA**: missing items as a to-do list – checking an item off records it as bought, items can be added via voice assistant
- **Bulk selection**: record several items as bought at once, move them, set category/location or delete them
- **Manage**: custom categories (name, icon, order) and storage locations (rename, delete, use as filter)
- **Lovelace card** `custom:prep-assistent-card` for your own dashboards
- **Expiry warnings**: daily check at the configured time → HA notification, optional push message (`notify.*`) and event `prep_assistent_expiry` for your own automations
- **Dashboard** in the sidebar: key figures, "Expiry at a glance", categories, lists with fill level
- **Templates** (JSON/YAML): choose people and days → quantities are calculated → apply as a shopping list
- **Shopping list filter**: show missing quantities only; "Record as purchased" sets quantity, purchase date and expiry date (from "shelf life after purchase"; without it the old expiry date is cleared)
- **Sensors** for your own dashboards/automations
- **Services** for automations and voice assistants
- **Multilingual**: German, English, French, Spanish, Italian, Russian, Danish, Norwegian, Swedish, Hungarian, Greek

## Languages

| Area | Language |
| --- | --- |
| Panel (UI, date and number format) | Language of the logged-in HA user |
| Template preview and applied items | Language of the user applying the template |
| Notifications, name of the first list, service errors | Home Assistant system language |
| Setup, sensors, services | HA translations (`translations/`) |

Unsupported languages fall back to English. Existing items and lists keep their names. When a template is applied again, its items are recognised even after a language change – as long as the template defines names as language objects (`{de: …, en: …}`); plain-string names only match exactly.

Panel and backend texts live in `custom_components/prep_assistent/frontend/i18n/<language>.json`. To add a language:

1. Copy `frontend/i18n/en.json`, translate it and add the language code to `i18n.py` (`LANGUAGES`) and to `frontend/prep-common.js` (`LANGUAGES`).
2. Copy `translations/en.json` to `translations/<language>.json` and translate it (setup, sensors, services).
3. Plural forms are objects with the [CLDR categories](https://cldr.unicode.org/index/cldr-spec/plural-rules) (`one`, `few`, `many`, `other`). The panel uses `Intl.PluralRules`, but the backend (`plural_category` in `i18n.py`) only knows special rules for Russian and French – every other language uses `one`/`other`. For languages with more forms (e.g. Polish, Czech), add a rule there.

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ → *Custom repositories* → enter `https://github.com/anderlin/PrepAssistent`, type *Integration*
2. Install "PrepAssistent", restart Home Assistant
3. *Settings → Devices & services → Add integration → PrepAssistent*

### Manual

Copy the folder `custom_components/prep_assistent` to `<config>/custom_components/`, restart HA and add the integration.

Requirement: Home Assistant **2025.2** or newer.

## Options

| Option | Meaning | Default |
| --- | --- | --- |
| Warning lead time | How many days before expiry an item counts as "expiring soon" | 30 |
| Time of daily check | When warnings are sent | 08:00 |
| Home Assistant notification | Persistent notification in the HA UI | on |
| Push notify service | e.g. `notify.mobile_app_my_phone` | empty |
| People in household | Basis for the supply range (can be changed temporarily in the panel) | 2 |
| Energy need per person and day | For the food supply range | 2200 kcal |
| Drinking water per person and day | For the water supply range | 2 l |

## Shopping list (to-do)

The entity `todo.prepassistent_shopping_list` (name depends on the system language) contains every item whose quantity is below its target quantity, e.g. "Rice (2 kg)", with list and storage location as description. It appears in the *To-do lists* panel in the sidebar, in the HA app, and can be shown on dashboards with the to-do card.

| Action | Effect |
| --- | --- |
| Check off | Recorded as purchased: quantity is raised to the target quantity (never lowered), purchase date today; the expiry date is recalculated from "shelf life after purchase" – if that is not set, the old expiry date is cleared |
| Add (also via Assist: "Add coffee to the PrepAssistent shopping list") | Known item: target quantity +1 (starting from the higher of target and stock). New item: created in the first list with quantity 0 and target 1 |
| Remove | Only the need is removed (target = stock), the item itself is kept |

## Supply range

For each item you can enter **kcal per unit** and **litres of drinking water per unit** under *More details* (example: rice in kg → 3500 kcal, mineral water in l → 1). The emergency supply templates include these values.

```
Food range  = Σ quantity × kcal per unit ÷ (people × kcal per day)
Water range = Σ quantity × litres per unit ÷ (people × litres per day)
Range       = minimum of both (if one of them has no data, only the other counts)
```

Expired items are not counted. The overview shows the range for the configured household size; you can change the number of people there to try out scenarios.

## Lovelace card

The card is loaded automatically (no resource needed) and appears as "PrepAssistent" in the card picker. All options can be set in the visual editor:

```yaml
type: custom:prep-assistent-card
title: Pantry            # optional
list: Basement           # optional: name or ID of a list, empty = all lists
show_stats: true         # key figures
show_range: true         # supply range
show_attention: true     # expiry at a glance
show_shopping: true      # shopping list with check-off
max_items: 5             # entries per section
```

## Templates

Bundled example templates live in `custom_components/prep_assistent/templates/`.
**Your own templates** go into `<config>/prep_assistent/templates/` (created on first start) and survive updates. A custom template with the same `id` replaces a bundled one. After changes, click "Reload" in the *Templates* tab.

### Format

```yaml
id: emergency_family           # optional, otherwise the file name
name: Emergency supply family  # or multilingual, see below
description: Short description
default_persons: 4             # preset in the dialog
default_days: 14
categories:                    # optional: additional categories
  - id: baby
    name: Baby supplies
    icon: mdi:baby-bottle
items:
  - name: Drinking water
    category: getraenke
    unit: l
    per_person_per_day: 2      # 2 l per person and day
    shelf_life_days: 365       # optional: suggested expiry date when buying
    water_per_unit: 1          # optional: litres of drinking water per unit (supply range)
  - name: Rice
    category: lebensmittel
    unit: kg
    per_person_per_day: 0.1
    step: 0.5                  # round up to 0.5 kg
    kcal_per_unit: 3500        # optional: kcal per unit (supply range)
  - name: First aid kit
    category: hausapotheke
    unit: pcs                  # unit code, gets translated (Stk, pcs, шт. …)
    fixed: 1                   # independent of people/days
  - name: Nappies
    category: baby
    unit: pcs
    per_day: 6
    notes: only with a toddler
```

### Multilingual templates

`name`, `description`, `notes` and `unit` may be a language object instead of a string. The user's language is shown, otherwise English, otherwise German:

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

**Unit codes** (translated automatically): `pcs`, `kg`, `g`, `l`, `ml`, `pack`, `can`, `jar`, `bottle`, `roll`, `tube`, `bar`, `box`, `pair`, `bag`, `folder`, `daily_dose`, `eur`. Any other text is used as is.

### Calculation

```
quantity = fixed + per_person × people + per_day × days + per_person_per_day × people × days
```

The result is then rounded to `step` (default `1`, `round`: `up` (default) | `nearest` | `down`) and at least `min` is used. Positions with quantity 0 are dropped.

Examples: `per_person: 0.25` with default rounding → 1 piece per started group of 4 people. `fixed: 8, per_person: 4, step: 4` → batteries in packs of 4.

Further optional fields per item: `opened_shelf_life_days` (use within after opening, days). `shelf_life_days`, `opened_shelf_life_days`, `kcal_per_unit` and `water_per_unit` are copied into the items when applying a template; for existing items only if no value is set there yet.

Category IDs (default): `lebensmittel` (food), `getraenke` (drinks), `hausapotheke` (first aid), `drogerie` (toiletries), `haushalt` (household & energy), `dokumente` (documents & cash), `tiere` (pets), `sonstiges` (other).

When applying to an **existing** list, items with the same name and unit get the new target quantity; all others are created with quantity 0 as shopping positions.

## Sensors

| Entity | Content |
| --- | --- |
| Items in stock | Number of items with quantity > 0 |
| Expiring soon | Count, attribute `items` |
| Expired | Count, attribute `items` |
| Missing items | Number of items below target quantity, attribute `items` |
| Next expiry date | Date, attributes of the item |
| Supply range | Days (minimum of food and water), attributes `kcal`, `water`, `persons` … |
| Food / water supply range | Days per area |
| Shopping list (`todo`) | Number of missing items, see above |

Expiry dates in sensors and events are the effective dates – for opened items the date "opened + use within after opening" if it is earlier (attribute `opened: true`).

## Services

| Service | Purpose |
| --- | --- |
| `prep_assistent.add_item` | Create an item (list by name or ID) |
| `prep_assistent.consume_item` | Reduce stock – by name, the batch expiring first is used |
| `prep_assistent.apply_template` | Calculate and apply a template |
| `prep_assistent.check_expiry` | Run the expiry check immediately |
| `prep_assistent.reload_templates` | Reload template files |

### Example automation: push on expiry warning

```yaml
triggers:
  - trigger: event
    event_type: prep_assistent_expiry
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: "Check your supplies"
      message: >
        {{ trigger.event.data.expired | count }} expired,
        {{ trigger.event.data.expiring | count }} expiring soon.
```

## Development

### Try it locally (Docker)

```bash
docker compose up -d          # starts HA on http://localhost:8123
docker compose restart        # after Python changes
docker compose logs -f        # logs (PrepAssistent at debug level)
docker compose down           # stop
```

The integration folder is mounted directly into the container; the HA configuration lives in `.dev/config/`. On first start, create a user, then *Settings → Devices & services → Add integration → PrepAssistent*. Changes to the panel (JS) only need a browser reload without cache (Cmd+Shift+R).

### Tests

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/pytest
```

The panel (`frontend/prep-assistent-panel.js`) and the card (`frontend/prep-assistent-card.js`) are web components without a build step and share helpers from `frontend/prep-common.js`. Data flows through the WebSocket API (`prep_assistent/*`); changes are pushed live to all open panels and cards.

> The bundled templates are examples (based on the recommendations of the German Federal Office of Civil Protection, BBK) and do not replace individual planning.
