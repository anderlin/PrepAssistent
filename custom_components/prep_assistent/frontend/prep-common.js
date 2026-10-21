/**
 * Gemeinsame Hilfen für Panel und Lovelace-Karte: Sprachdateien, Formatierung, Escaping.
 * Wird per dynamischem import() mit derselben Versions-Query (?v=…) geladen wie das aufrufende Modul.
 */

export const LANGUAGES = ["de", "en", "fr", "es", "it", "ru", "da", "nb", "sv", "hu", "el"];
export const FALLBACK_LANGUAGE = "en";
const LANGUAGE_ALIASES = { no: "nb", nn: "nb" };
export const BUILTIN_CATEGORIES = ["lebensmittel", "getraenke", "hausapotheke", "drogerie", "haushalt", "dokumente", "tiere", "sonstiges"];

// Versions-Query auch für die Sprachdateien verwenden (Cache-Busting)
const VERSION_QUERY = new URL(import.meta.url).search;
const stringCache = new Map();

export const resolveLanguage = (language) => {
  const lang = String(language || "").replace("_", "-").toLowerCase();
  for (let candidate of [lang, lang.split("-")[0]]) {
    candidate = LANGUAGE_ALIASES[candidate] || candidate;
    if (LANGUAGES.includes(candidate)) return candidate;
  }
  return FALLBACK_LANGUAGE;
};

const loadStrings = (lang) => {
  if (!stringCache.has(lang)) {
    const url = new URL(`./i18n/${lang}.json${VERSION_QUERY}`, import.meta.url);
    stringCache.set(
      lang,
      fetch(url)
        .then((res) => (res.ok ? res.json() : {}))
        .catch(() => ({})),
    );
  }
  return stringCache.get(lang);
};

const lookup = (strings, key) =>
  key.split(".").reduce((node, part) => (node && typeof node === "object" ? node[part] : undefined), strings);

export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

export const addDays = (iso, days) => {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export const localeOf = (hass) => hass?.locale?.language || hass?.language || FALLBACK_LANGUAGE;

/** Übersetzungen und Formatierung in der Sprache des HA-Benutzers. */
export class I18n {
  constructor() {
    this.strings = {};
    this.fallback = {};
    this.locale = FALLBACK_LANGUAGE;
    this.lang = FALLBACK_LANGUAGE;
  }

  /** Lädt die Sprache; false, wenn währenddessen eine andere angefordert wurde. */
  async set(locale) {
    this.locale = locale;
    const lang = resolveLanguage(locale);
    const [strings, fallback] = await Promise.all([loadStrings(lang), loadStrings(FALLBACK_LANGUAGE)]);
    if (this.locale !== locale) return false;
    this.lang = lang;
    this.strings = strings;
    this.fallback = fallback;
    try {
      this.pluralRules = new Intl.PluralRules(locale);
      this.numberFormat = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
    } catch {
      this.pluralRules = new Intl.PluralRules(lang);
      this.numberFormat = new Intl.NumberFormat(lang, { maximumFractionDigits: 2 });
    }
    return true;
  }

  /** Übersetzt einen Schlüssel; Pluralformen über params.count, Platzhalter {name}. */
  t(key, params = {}) {
    let value = lookup(this.strings, key) ?? lookup(this.fallback, key);
    if (value === undefined) return key;
    if (typeof value === "object") {
      const category = this.pluralRules?.select(Number(params.count ?? 0)) || "other";
      value = value[category] ?? value.other ?? "";
    }
    return String(value).replace(/\{(\w+)\}/g, (match, name) => (name in params ? params[name] : match));
  }

  has(key) {
    return lookup(this.strings, key) !== undefined || lookup(this.fallback, key) !== undefined;
  }

  /** Sprach-Objekt ({de: …, en: …}) oder String in der aktuellen Sprache. */
  localize(value) {
    if (value && typeof value === "object") {
      return value[this.lang] || value[FALLBACK_LANGUAGE] || value.de || Object.values(value)[0] || "";
    }
    return value ?? "";
  }

  errText(err) {
    const key = err?.translation_key;
    if (key && this.has(`error.${key}`)) return this.t(`error.${key}`, err.translation_placeholders || {});
    return err?.message || String(err);
  }

  num(n) {
    if (n === null || n === undefined || n === "") return "";
    return (this.numberFormat || new Intl.NumberFormat()).format(Number(n));
  }

  date(iso) {
    if (!iso) return "–";
    const date = new Date(`${iso}T00:00:00`);
    try {
      return date.toLocaleDateString(this.locale);
    } catch {
      return date.toLocaleDateString(this.lang);
    }
  }

  expiryText(item) {
    const d = item.days_left;
    if (d === null || d === undefined) {
      return this.t(item.quantity > 0 ? "expiry.no_date" : "expiry.not_in_stock");
    }
    if (d < -1) return this.t("expiry.expired_days_ago", { count: -d });
    if (d === -1) return this.t("expiry.expired_yesterday");
    if (d === 0) return this.t("expiry.today");
    if (d === 1) return this.t("expiry.tomorrow");
    if (d < 60) return this.t("expiry.days_left", { count: d });
    if (d < 730) return this.t("expiry.months_left", { count: Math.round(d / 30) });
    return this.t("expiry.years_left", { count: Math.round(d / 365) });
  }

  /** Standardkategorien übersetzt, sofern nicht umbenannt; eigene mit gespeichertem Namen. */
  catName(cat) {
    if (BUILTIN_CATEGORIES.includes(cat.id) && !cat.renamed) return this.t(`category.${cat.id}`);
    return this.localize(cat.name);
  }

  /** Reichweite in ganzen Tagen (abgerundet) als Text, z. B. „12 Tage“. */
  rangeText(days) {
    if (days === null || days === undefined) return "–";
    return this.t("common.days", { count: Math.floor(days) });
  }
}
