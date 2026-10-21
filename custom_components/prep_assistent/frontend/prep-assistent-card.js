/**
 * PrepAssistent – Lovelace-Karte "custom:prep-assistent-card".
 * Wird von der Integration automatisch geladen (keine Ressource nötig).
 *
 * type: custom:prep-assistent-card
 * title: Vorrat            # optional
 * list: Keller             # optional: Name oder ID einer Liste, leer = alle
 * show_stats: true         # Kennzahlen
 * show_range: true         # Reichweite
 * show_attention: true     # Ablauf im Blick
 * show_shopping: true      # Einkaufsliste mit Abhaken
 * max_items: 5             # Einträge je Liste
 */

const { I18n, esc, localeOf } = await import(
  new URL(`./prep-common.js${new URL(import.meta.url).search}`, import.meta.url)
);

const PANEL_PATH = "/prep-assistent";
const DEFAULTS = {
  show_stats: true,
  show_range: true,
  show_attention: true,
  show_shopping: true,
  max_items: 5,
};

// Beschriftungen des Karteneditors (Sprache der HA-Oberfläche)
const editorI18n = new I18n();
await editorI18n.set(document.documentElement.lang || navigator.language);

class PrepAssistentCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._i18n = new I18n();
    this._data = null;
    this._error = null;
    this._unsub = null;
  }

  static getConfigForm() {
    const toggles = ["show_stats", "show_range", "show_attention", "show_shopping"];
    return {
      schema: [
        { name: "title", selector: { text: {} } },
        { name: "list", selector: { text: {} } },
        { type: "grid", name: "", schema: toggles.map((name) => ({ name, selector: { boolean: {} } })) },
        { name: "max_items", selector: { number: { min: 1, max: 50, mode: "box" } } },
      ],
      computeLabel: (schema) => editorI18n.t(`card.editor.${schema.name}`),
      computeHelper: (schema) => (schema.name === "list" ? editorI18n.t("card.editor.list_help") : undefined),
    };
  }

  static getStubConfig() {
    return { ...DEFAULTS };
  }

  setConfig(config) {
    this._config = { ...DEFAULTS, ...config };
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const locale = localeOf(hass);
    if (first) this._init(locale);
    else if (locale !== this._i18n.locale) this._i18n.set(locale).then((ok) => ok && this._render());
  }

  getCardSize() {
    return 5;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub.then((unsub) => unsub()).catch(() => {});
      this._unsub = null;
    }
  }

  async _init(locale) {
    await this._i18n.set(locale);
    if (this.isConnected) this._subscribe();
    await this._load();
  }

  _subscribe() {
    this._unsub = this._hass.connection.subscribeMessage(() => this._scheduleLoad(), {
      type: "prep_assistent/subscribe",
    });
    this._unsub.catch(() => {});
  }

  _scheduleLoad() {
    clearTimeout(this._loadTimer);
    this._loadTimer = setTimeout(() => this._load(), 150);
  }

  async _load() {
    try {
      this._data = await this._hass.callWS({ type: "prep_assistent/data" });
      this._error = null;
    } catch (err) {
      this._error = this._i18n.errText(err);
    }
    this._render();
  }

  _list() {
    const ref = String(this._config.list || "").trim();
    if (!ref) return null;
    return (
      this._data.lists.find((l) => l.id === ref) ||
      this._data.lists.find((l) => l.name.toLowerCase() === ref.toLowerCase()) ||
      undefined
    );
  }

  _render() {
    if (!this._config) return;
    const i18n = this._i18n;
    const t = (key, params) => esc(i18n.t(key, params));
    const c = this._config;
    let body;
    let title = c.title;

    if (this._error) body = `<div class="empty">${esc(this._error)}</div>`;
    else if (!this._data) body = `<div class="empty">${t("panel.loading")}</div>`;
    else {
      const list = this._list();
      if (list === undefined) {
        body = `<div class="empty">${t("card.list_not_found", { list: c.list })}</div>`;
      } else {
        title = title || list?.name;
        const items = list ? this._data.items.filter((i) => i.list_id === list.id) : this._data.items;
        const range = list ? this._data.list_ranges[list.id] : this._data.range;
        body = [
          c.show_stats ? this._renderStats(items) : "",
          c.show_range ? this._renderRange(range) : "",
          c.show_attention ? this._renderAttention(items) : "",
          c.show_shopping ? this._renderShopping(items) : "",
        ].join("");
      }
    }

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="header">
          <ha-icon icon="mdi:warehouse"></ha-icon>
          <span class="grow">${esc(title || "PrepAssistent")}</span>
          <button class="icon-btn" data-action="open" title="${t("card.open_panel")}"><ha-icon icon="mdi:open-in-new"></ha-icon></button>
        </div>
        <div class="content">${body}</div>
      </ha-card>`;
    this.shadowRoot.querySelector("ha-card").addEventListener("click", (ev) => this._onClick(ev));
  }

  _renderStats(items) {
    const t = (key, params) => esc(this._i18n.t(key, params));
    const count = (fn) => items.filter(fn).length;
    const stat = (icon, value, label, cls) => `
      <div class="stat ${value ? cls : ""}"><ha-icon icon="${icon}"></ha-icon><b>${value}</b><span>${label}</span></div>`;
    return `<div class="stats">
      ${stat("mdi:warehouse", count((i) => i.quantity > 0), t("overview.in_stock"), "")}
      ${stat("mdi:clock-alert-outline", count((i) => i.status === "expiring"), t("status.expiring"), "warning")}
      ${stat("mdi:alert-octagon-outline", count((i) => i.status === "expired"), t("status.expired"), "error")}
      ${stat("mdi:cart-outline", count((i) => i.missing > 0), t("status.missing"), "info")}
    </div>`;
  }

  _renderRange(range) {
    const i18n = this._i18n;
    const t = (key, params) => esc(i18n.t(key, params));
    if (!range || range.days === null) return "";
    const part = (icon, days) => (days === null ? "" : `<span><ha-icon icon="${icon}"></ha-icon>${esc(i18n.rangeText(days))}</span>`);
    return `<div class="range ${range.days < 10 ? "low" : ""}">
      <ha-icon icon="mdi:calendar-clock"></ha-icon>
      <div class="grow">
        <div><b>${esc(i18n.rangeText(range.days))}</b> ${t("card.range_for", { persons: i18n.t("common.persons", { count: range.persons }) })}</div>
        <div class="sub">${part("mdi:food-variant", range.food_days)}${part("mdi:water", range.water_days)}</div>
      </div>
    </div>`;
  }

  _renderAttention(items) {
    const i18n = this._i18n;
    const t = (key, params) => esc(i18n.t(key, params));
    const max = Number(this._config.max_items) || DEFAULTS.max_items;
    const attention = items
      .filter((i) => i.status === "expired" || i.status === "expiring")
      .sort((a, b) => a.days_left - b.days_left);
    const rows = attention
      .slice(0, max)
      .map(
        (i) => `<div class="row">
          <div class="grow"><div class="title">${esc(i.name)}</div>
          <div class="sub">${i18n.num(i.quantity)} ${esc(i.unit)}${i.location ? ` · ${esc(i.location)}` : ""}</div></div>
          <span class="badge ${i.status}">${esc(i18n.expiryText(i))}</span>
        </div>`,
      )
      .join("");
    const more = attention.length > max ? `<div class="sub more">${t("notify.more", { count: attention.length - max })}</div>` : "";
    return `<div class="section"><div class="section-title">${t("overview.attention")}</div>
      ${rows || `<div class="sub">${t("overview.all_good", { count: this._data.settings.warning_days })}</div>`}${more}</div>`;
  }

  _renderShopping(items) {
    const i18n = this._i18n;
    const t = (key, params) => esc(i18n.t(key, params));
    const max = Number(this._config.max_items) || DEFAULTS.max_items;
    const missing = items.filter((i) => i.missing > 0).sort((a, b) => a.name.localeCompare(b.name, i18n.locale));
    const rows = missing
      .slice(0, max)
      .map(
        (i) => `<div class="row">
          <button class="icon-btn" data-action="buy" data-id="${i.id}" title="${t("stock.buy")}"><ha-icon icon="mdi:checkbox-blank-outline"></ha-icon></button>
          <div class="grow"><div class="title">${esc(i.name)}</div>
          <div class="sub">${t("stock.missing_qty", { quantity: `${i18n.num(i.missing)} ${i.unit}` })}</div></div>
        </div>`,
      )
      .join("");
    const more = missing.length > max ? `<div class="sub more">${t("notify.more", { count: missing.length - max })}</div>` : "";
    return `<div class="section"><div class="section-title">${t("card.shopping")}</div>
      ${rows || `<div class="sub">${t("card.nothing_missing")}</div>`}${more}</div>`;
  }

  async _onClick(ev) {
    const el = ev.target.closest?.("[data-action]");
    if (!el) return;
    if (el.dataset.action === "open") {
      history.pushState(null, "", PANEL_PATH);
      window.dispatchEvent(new CustomEvent("location-changed"));
    } else if (el.dataset.action === "buy") {
      el.disabled = true;
      try {
        await this._hass.callWS({ type: "prep_assistent/items/bulk", item_ids: [el.dataset.id], action: "buy" });
      } catch (err) {
        el.disabled = false;
        this.dispatchEvent(
          new CustomEvent("hass-notification", {
            detail: { message: this._i18n.t("toast.error", { error: this._i18n.errText(err) }) },
            bubbles: true,
            composed: true,
          }),
        );
      }
    }
  }
}

const STYLES = `
  :host { --pa-warning: var(--warning-color, #ffa600); --pa-error: var(--error-color, #db4437); --pa-info: var(--info-color, #039be5); --pa-success: var(--success-color, #43a047); }
  ha-card { overflow: hidden; }
  .header { display: flex; align-items: center; gap: 10px; padding: 12px 8px 4px 16px; font-size: 18px; font-weight: 500; }
  .header > ha-icon { color: var(--primary-color); }
  .content { padding: 4px 16px 16px; }
  .grow { flex: 1; min-width: 0; }
  .empty { padding: 16px 0; color: var(--secondary-text-color); text-align: center; }
  .icon-btn {
    display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px;
    border-radius: 50%; border: none; background: none; cursor: pointer; color: var(--secondary-text-color);
  }
  .icon-btn:hover { background: var(--secondary-background-color, rgba(0,0,0,.06)); }
  .icon-btn:disabled { opacity: .4; }
  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 4px 0 8px; }
  .stat { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 2px; padding: 8px 4px;
    border-radius: 8px; background: var(--secondary-background-color, rgba(0,0,0,.04)); }
  .stat ha-icon { color: var(--primary-color); --mdc-icon-size: 22px; }
  .stat.warning ha-icon { color: var(--pa-warning); }
  .stat.error ha-icon { color: var(--pa-error); }
  .stat.info ha-icon { color: var(--pa-info); }
  .stat b { font-size: 20px; font-weight: 500; }
  .stat span { font-size: 11px; color: var(--secondary-text-color); line-height: 1.2; }
  .range { display: flex; align-items: center; gap: 12px; padding: 8px 0; }
  .range > ha-icon { color: var(--pa-success); }
  .range.low > ha-icon { color: var(--pa-warning); }
  .range .sub { display: flex; gap: 12px; }
  .range .sub ha-icon { --mdc-icon-size: 14px; margin-right: 2px; vertical-align: -2px; }
  .section { margin-top: 8px; }
  .section-title { font-weight: 500; margin: 8px 0 4px; }
  .row { display: flex; align-items: center; gap: 8px; padding: 4px 0; border-bottom: 1px solid var(--divider-color); }
  .row:last-of-type { border-bottom: none; }
  .title { overflow-wrap: anywhere; }
  .sub { font-size: 12.5px; color: var(--secondary-text-color); }
  .more { padding-top: 4px; }
  .badge { padding: 2px 8px; border-radius: 999px; font-size: 12px; white-space: nowrap;
    background: var(--secondary-background-color, #eee); color: var(--secondary-text-color); }
  .badge.expired { background: var(--pa-error); color: #fff; }
  .badge.expiring { background: var(--pa-warning); color: #000; }
`;

if (!customElements.get("prep-assistent-card")) {
  customElements.define("prep-assistent-card", PrepAssistentCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "prep-assistent-card")) {
  window.customCards.push({
    type: "prep-assistent-card",
    name: "PrepAssistent",
    description: editorI18n.t("card.description"),
    preview: true,
    documentationURL: "https://github.com/anderlin/PrepAssistent",
  });
}
