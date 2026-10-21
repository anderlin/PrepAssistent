"""Konstanten für PrepAssistent."""

from __future__ import annotations

DOMAIN = "prep_assistent"
VERSION = "0.3.0"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1
SAVE_DELAY = 1

# Optionen
CONF_WARNING_DAYS = "warning_days"
CONF_NOTIFY_TIME = "notify_time"
CONF_PERSISTENT_NOTIFICATION = "persistent_notification"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_HOUSEHOLD_PERSONS = "household_persons"
CONF_KCAL_PER_DAY = "kcal_per_day"
CONF_WATER_PER_DAY = "water_per_day"

DEFAULT_WARNING_DAYS = 30
DEFAULT_NOTIFY_TIME = "08:00:00"
DEFAULT_PERSISTENT_NOTIFICATION = True
DEFAULT_HOUSEHOLD_PERSONS = 2
DEFAULT_KCAL_PER_DAY = 2200  # Rechengrundlage des BBK
DEFAULT_WATER_PER_DAY = 2.0  # Liter pro Person und Tag (BBK)

# Frontend
PANEL_URL_PATH = "prep-assistent"
PANEL_TITLE = "PrepAssistent"
PANEL_ICON = "mdi:warehouse"
PANEL_COMPONENT = "prep-assistent-panel"
STATIC_URL = "/prep_assistent_static"
CARD_URL = f"{STATIC_URL}/prep-assistent-card.js?v={VERSION}"

# Vorlagen
USER_TEMPLATE_DIR = "prep_assistent/templates"

# Events & Signale
EVENT_EXPIRY = "prep_assistent_expiry"
SIGNAL_UPDATED = "prep_assistent_updated"
NOTIFICATION_ID = "prep_assistent_expiry"

# Item-Status
STATUS_EXPIRED = "expired"
STATUS_EXPIRING = "expiring"
STATUS_OK = "ok"
STATUS_NONE = "none"

DEFAULT_CATEGORY = "sonstiges"
DEFAULT_CATEGORIES: list[dict[str, str]] = [
    {"id": "lebensmittel", "name": "Lebensmittel", "icon": "mdi:food-apple"},
    {"id": "getraenke", "name": "Getränke", "icon": "mdi:cup-water"},
    {"id": "hausapotheke", "name": "Hausapotheke", "icon": "mdi:medical-bag"},
    {"id": "drogerie", "name": "Drogerie & Hygiene", "icon": "mdi:lotion"},
    {"id": "haushalt", "name": "Haushalt & Energie", "icon": "mdi:flashlight"},
    {"id": "dokumente", "name": "Dokumente & Bargeld", "icon": "mdi:file-document"},
    {"id": "tiere", "name": "Haustiere", "icon": "mdi:paw"},
    {"id": DEFAULT_CATEGORY, "name": "Sonstiges", "icon": "mdi:package-variant"},
]
