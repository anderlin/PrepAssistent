/**
 * PrepAssistent – Sidebar-Panel für Home Assistant.
 * Kein Build-Schritt nötig: reines Web Component, Daten über die WebSocket-API.
 * Texte kommen aus ./i18n/<sprache>.json (Sprache des HA-Benutzers, Fallback Englisch).
 */

// Gemeinsame Hilfen mit derselben Versions-Query laden (Cache-Busting)
const { I18n, esc, addDays, localeOf, FALLBACK_LANGUAGE } = await import(
  new URL(`./prep-common.js${new URL(import.meta.url).search}`, import.meta.url)
);
const DIALOG_UNITS = ["pcs", "kg", "g", "l", "ml", "pack", "can", "jar", "bottle", "roll", "tube", "pair"];
const EMPTY_FILTER = { text: "", category: "", status: "", location: "", shopping: false };
const NO_LOCATION = "\u0000";

class PrepAssistentPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "overview";
    this._data = null;
    this._tplData = null;
    this._listId = "";
    this._filter = { ...EMPTY_FILTER };
    this._selecting = false;
    this._selected = new Set();
    this._rangePersons = null;
    this._tpl = { id: null, persons: 2, days: 10, mode: "new", listId: "", listName: "", preview: null };
    this._dialog = null;
    this._unsub = null;
    this._i18n = new I18n();
  }

  // ------------------------------------------------------------ HA-Hooks

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._menuButton) this._menuButton.hass = hass;
    if (first) this._init();
    else if (this._initialized && this._localeOf(hass) !== this._locale) this._changeLanguage();
  }

  set narrow(narrow) {
    this._narrow = narrow;
    if (this._menuButton) this._menuButton.narrow = narrow;
  }

  connectedCallback() {
    if (this._hass && this._initialized && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub.then((unsub) => unsub()).catch(() => {});
      this._unsub = null;
    }
  }

  async _init() {
    this._initialized = true;
    await this._setLanguage(this._localeOf(this._hass));
    this._renderShell();
    this._subscribe();
    await Promise.all([this._load(), this._loadTemplates()]);
  }

  _subscribe() {
    this._unsub = this._hass.connection.subscribeMessage(() => this._scheduleLoad(), {
      type: "prep_assistent/subscribe",
    });
    this._unsub.catch((err) => this._toast(this._t("toast.live_update_failed", { error: this._errText(err) })));
  }

  _scheduleLoad() {
    clearTimeout(this._loadTimer);
    this._loadTimer = setTimeout(() => this._load(), 150);
  }

  async _load() {
    try {
      this._data = await this._hass.callWS({ type: "prep_assistent/data" });
    } catch (err) {
      this._renderError(err);
      return;
    }
    if (this._listId && !this._data.lists.some((l) => l.id === this._listId)) this._listId = "";
    this._render();
  }

  async _loadTemplates(reload = false) {
    try {
      this._tplData = await this._hass.callWS({
        type: reload ? "prep_assistent/templates/reload" : "prep_assistent/templates",
        language: this._lang,
      });
      if (reload) this._toast(this._t("templates.loaded", { count: this._tplData.templates.length }));
    } catch (err) {
      this._toast(this._t("templates.load_error", { error: this._errText(err) }));
      return;
    }
    if (this._tab === "templates") this._render();
  }

  async _ws(msg, success) {
    try {
      const result = await this._hass.callWS(msg);
      if (success) this._toast(success);
      return result;
    } catch (err) {
      this._toast(this._t("toast.error", { error: this._errText(err) }));
      throw err;
    }
  }

  _toast(message) {
    this.dispatchEvent(
      new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }),
    );
  }

  // ---------------------------------------------------------- Sprache

  _localeOf(hass) {
    return localeOf(hass);
  }

  async _setLanguage(locale) {
    this._locale = locale;
    if (await this._i18n.set(locale)) this._lang = this._i18n.lang;
  }

  async _changeLanguage() {
    await this._setLanguage(this._localeOf(this._hass));
    this._render();
    await this._loadTemplates();
    if (this._tpl.id) this._schedulePreview();
  }

  _t(key, params = {}) {
    return this._i18n.t(key, params);
  }

  _has(key) {
    return this._i18n.has(key);
  }

  _localize(value) {
    return this._i18n.localize(value);
  }

  _errText(err) {
    return this._i18n.errText(err);
  }

  _fmtNum(n) {
    return this._i18n.num(n);
  }

  _fmtDate(iso) {
    return this._i18n.date(iso);
  }

  _expiryText(item) {
    return this._i18n.expiryText(item);
  }

  // --------------------------------------------------------- Hilfsdaten

  _category(id) {
    return (
      this._data.categories.find((c) => c.id === id) || { id, name: id, icon: "mdi:tag" }
    );
  }

  _catName(cat) {
    return this._i18n.catName(cat);
  }

  _list(id) {
    return this._data.lists.find((l) => l.id === id);
  }

  _filteredItems() {
    const f = this._filter;
    const text = f.text.trim().toLowerCase();
    return this._data.items.filter((item) => {
      if (this._listId && item.list_id !== this._listId) return false;
      if (f.category && item.category !== f.category) return false;
      if (f.shopping && !(item.missing > 0)) return false;
      if (f.status === "missing" && !(item.missing > 0)) return false;
      if (f.status && f.status !== "missing" && item.status !== f.status) return false;
      if (f.location === NO_LOCATION ? item.location : f.location && item.location?.toLowerCase() !== f.location.toLowerCase()) return false;
      if (text && !`${item.name} ${item.location} ${item.notes}`.toLowerCase().includes(text)) return false;
      return true;
    });
  }

  // ------------------------------------------------------------- Rendern

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="toolbar">
        <span id="menu"></span>
        <div class="main-title">PrepAssistent</div>
        <div class="toolbar-info" id="toolbar-info"></div>
      </div>
      <nav class="tabs" id="tabs"></nav>
      <main id="content"><div class="loading">${esc(this._t("panel.loading"))}</div></main>
      <div id="dialog"></div>
    `;
    this._menuButton = document.createElement("ha-menu-button");
    this._menuButton.hass = this._hass;
    this._menuButton.narrow = this._narrow;
    this.shadowRoot.getElementById("menu").appendChild(this._menuButton);

    const root = this.shadowRoot;
    root.addEventListener("click", (ev) => this._onClick(ev));
    root.addEventListener("input", (ev) => this._onInput(ev));
    root.addEventListener("change", (ev) => this._onInput(ev));
    root.addEventListener("submit", (ev) => this._onSubmit(ev));
    root.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && this._dialog) this._closeDialog();
    });
  }

  _renderError(err) {
    this.shadowRoot.getElementById("content").innerHTML = `
      <div class="card empty">
        <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
        <p>${esc(this._t("panel.load_failed", { error: this._errText(err) }))}</p>
      </div>`;
  }

  _render() {
    if (!this._data) return;
    const tabs = [
      ["overview", "mdi:view-dashboard-outline"],
      ["stock", "mdi:format-list-checks"],
      ["templates", "mdi:clipboard-text-outline"],
      ["manage", "mdi:cog-outline"],
    ];
    this.shadowRoot.getElementById("tabs").innerHTML = tabs
      .map(
        ([id, icon]) => `
        <button class="tab ${this._tab === id ? "active" : ""}" data-action="tab" data-id="${id}">
          <ha-icon icon="${icon}"></ha-icon><span>${esc(this._t(`tabs.${id}`))}</span>
        </button>`,
      )
      .join("");
    this.shadowRoot.getElementById("toolbar-info").textContent = this._t("panel.warning_info", {
      count: this._data.settings.warning_days,
    });

    const content = this.shadowRoot.getElementById("content");
    if (this._tab === "overview") content.innerHTML = this._renderOverview();
    else if (this._tab === "stock") {
      content.innerHTML = this._renderStock();
      this._renderItemTable();
    } else if (this._tab === "manage") content.innerHTML = this._renderManage();
    else content.innerHTML = this._renderTemplates();
  }

  // ----------------------------------------------------------- Übersicht

  _renderOverview() {
    const t = (key, params) => esc(this._t(key, params));
    const items = this._data.items;
    const stock = items.filter((i) => i.quantity > 0);
    const expired = items.filter((i) => i.status === "expired");
    const expiring = items.filter((i) => i.status === "expiring");
    const missing = items.filter((i) => i.missing > 0);

    const stat = (status, icon, value, label, cls) => `
      <button class="stat ${cls}" data-action="goto-status" data-id="${status}">
        <ha-icon icon="${icon}"></ha-icon>
        <div><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>
      </button>`;

    const attention = [...expired, ...expiring].sort((a, b) => a.days_left - b.days_left);
    const attentionHtml = attention.length
      ? attention
          .slice(0, 12)
          .map(
            (i) => `
          <button class="attention-row" data-action="edit-item" data-id="${i.id}">
            <ha-icon icon="${esc(this._category(i.category).icon)}"></ha-icon>
            <div class="grow">
              <div class="title">${esc(i.name)}</div>
              <div class="sub">${this._fmtNum(i.quantity)} ${esc(i.unit)} · ${esc(i.list_name)}${i.location ? ` · ${esc(i.location)}` : ""}</div>
            </div>
            <span class="badge ${i.status}">${esc(this._expiryText(i))}</span>
          </button>`,
          )
          .join("") +
        (attention.length > 12
          ? `<button class="link" data-action="goto-status" data-id="expiring">${t("overview.show_all", { count: attention.length })}</button>`
          : "")
      : `<div class="empty small"><ha-icon icon="mdi:check-circle-outline"></ha-icon>${t("overview.all_good", { count: this._data.settings.warning_days })}</div>`;

    const listCards = this._data.lists
      .map((list) => {
        const li = items.filter((i) => i.list_id === list.id);
        const targeted = li.filter((i) => i.target_quantity > 0);
        const coverage = targeted.length
          ? Math.round(
              (targeted.reduce((sum, i) => sum + Math.min(i.quantity / i.target_quantity, 1), 0) /
                targeted.length) *
                100,
            )
          : null;
        const warn = li.filter((i) => i.status === "expired" || i.status === "expiring").length;
        const range = this._data.list_ranges?.[list.id];
        const rangeText = range?.days != null ? ` · ${t("overview.range_short", { days: this._i18n.rangeText(range.days) })}` : "";
        return `
          <button class="card list-card" data-action="open-list" data-id="${list.id}">
            <div class="list-head">
              <ha-icon icon="mdi:warehouse"></ha-icon>
              <div class="grow"><div class="title">${esc(list.name)}</div>
              <div class="sub">${t("common.items", { count: li.length })}${rangeText}${warn ? ` · <span class="warn-text">${t("overview.expiry_warnings", { count: warn })}</span>` : ""}</div></div>
            </div>
            ${
              coverage === null
                ? `<div class="sub">${t("overview.no_targets")}</div>`
                : `<div class="progress-label"><span>${t("overview.coverage")}</span><span>${this._fmtNum(coverage)} %</span></div>
                   <div class="progress"><div style="width:${coverage}%"></div></div>`
            }
          </button>`;
      })
      .join("");

    const catRows = this._data.categories
      .map((cat) => {
        const ci = stock.filter((i) => i.category === cat.id);
        if (!ci.length) return "";
        const warn = ci.filter((i) => i.status === "expired" || i.status === "expiring").length;
        const pct = Math.round((ci.length / Math.max(stock.length, 1)) * 100);
        return `
          <button class="cat-row" data-action="goto-category" data-id="${esc(cat.id)}">
            <ha-icon icon="${esc(cat.icon)}"></ha-icon>
            <div class="grow">
              <div class="progress-label"><span>${esc(this._catName(cat))}</span><span>${ci.length}${warn ? ` <span class="warn-text">(${warn} ⚠)</span>` : ""}</span></div>
              <div class="progress thin"><div style="width:${pct}%"></div></div>
            </div>
          </button>`;
      })
      .join("");

    return `
      <div class="stats">
        ${stat("", "mdi:warehouse", stock.length, t("overview.in_stock"), "")}
        ${stat("expiring", "mdi:clock-alert-outline", expiring.length, t("status.expiring"), expiring.length ? "warning" : "")}
        ${stat("expired", "mdi:alert-octagon-outline", expired.length, t("status.expired"), expired.length ? "error" : "")}
        ${stat("missing", "mdi:cart-outline", missing.length, t("status.missing"), missing.length ? "info" : "")}
      </div>
      ${this._renderRange()}
      <div class="columns">
        <section class="card">
          <h2>${t("overview.attention")}</h2>
          ${attentionHtml}
        </section>
        <section class="card">
          <h2>${t("overview.categories")}</h2>
          ${catRows || `<div class="empty small">${t("overview.no_stock")}</div>`}
        </section>
      </div>
      <h2 class="section-title">${t("overview.lists")}</h2>
      <div class="list-grid">
        ${listCards}
        <button class="card list-card add" data-action="add-list">
          <ha-icon icon="mdi:plus"></ha-icon><span>${t("overview.new_list")}</span>
        </button>
      </div>`;
  }

  /** Reichweite für die Haushaltsgröße oder eine im Panel gewählte Personenzahl. */
  _renderRange() {
    const t = (key, params) => esc(this._t(key, params));
    const r = this._data.range;
    const persons = this._rangePersons || r.persons;
    // Reichweite ist umgekehrt proportional zur Personenzahl
    const scale = (days) => (days == null ? null : (days * r.persons) / persons);
    const food = scale(r.food_days);
    const water = scale(r.water_days);
    const days = scale(r.days);
    const goal = 10; // BBK-Empfehlung: Vorrat für 10 Tage
    const bar = (icon, label, value, detail) => `
      <div class="range-row">
        <ha-icon icon="${icon}"></ha-icon>
        <div class="grow">
          <div class="progress-label"><span>${label}</span><span>${value == null ? t("overview.range_unknown") : esc(this._i18n.rangeText(value))}</span></div>
          <div class="progress thin ${value != null && value < goal ? "low" : ""}"><div style="width:${value == null ? 0 : Math.min((value / (goal * 3)) * 100, 100)}%"></div></div>
          <div class="sub">${detail}</div>
        </div>
      </div>`;
    return `
      <section class="card range-card">
        <div class="range-head">
          <div class="grow">
            <h2>${t("overview.range_title")}</h2>
            <div class="range-value ${days != null && days < goal ? "low" : ""}">${days == null ? "–" : esc(this._i18n.rangeText(days))}</div>
          </div>
          <label class="range-persons">${t("templates.persons")}
            <div class="stepper">
              <button class="icon-btn small" data-action="range-persons" data-id="-1"><ha-icon icon="mdi:minus"></ha-icon></button>
              <input type="number" min="1" max="100" data-range="persons" value="${persons}">
              <button class="icon-btn small" data-action="range-persons" data-id="1"><ha-icon icon="mdi:plus"></ha-icon></button>
            </div>
          </label>
        </div>
        ${
          r.days == null
            ? `<div class="sub">${t("overview.range_none")}</div>`
            : bar("mdi:food-variant", t("overview.range_food"), food, t("overview.range_kcal", { kcal: this._fmtNum(r.kcal), per_day: this._fmtNum(r.kcal_per_day) })) +
              bar("mdi:water", t("overview.range_water"), water, t("overview.range_liters", { liters: this._fmtNum(r.water), per_day: this._fmtNum(r.water_per_day) }))
        }
      </section>`;
  }

  // ------------------------------------------------------------- Vorräte

  _renderStock() {
    const t = (key, params) => esc(this._t(key, params));
    const lists = this._data.lists;
    if (!lists.length) {
      return `<div class="card empty">
        <ha-icon icon="mdi:warehouse"></ha-icon>
        <p>${t("stock.no_lists")}</p>
        <div class="row-actions">
          <button class="primary" data-action="add-list">${t("stock.create_list")}</button>
          <button data-action="tab" data-id="templates">${t("stock.from_template")}</button>
        </div></div>`;
    }
    const chips = [{ id: "", name: this._t("stock.all_lists") }, ...lists]
      .map(
        (l) => `<button class="chip ${this._listId === l.id ? "active" : ""}" data-action="select-list" data-id="${l.id}">${esc(l.name)}</button>`,
      )
      .join("");
    const current = this._list(this._listId);
    const f = this._filter;
    const statusOptions = ["", "expired", "expiring", "ok", "none", "missing"].map((v) => [v, this._t(`status.${v || "all"}`)]);
    return `
      <div class="chips">${chips}<button class="chip add" data-action="add-list"><ha-icon icon="mdi:plus"></ha-icon>${t("stock.list")}</button></div>
      ${
        current
          ? `<div class="list-info">
              <div class="grow"><h2>${esc(current.name)}</h2>${current.description ? `<div class="sub">${esc(current.description)}</div>` : ""}</div>
              <button class="icon-btn" data-action="edit-list" data-id="${current.id}" title="${t("stock.edit_list")}"><ha-icon icon="mdi:pencil"></ha-icon></button>
              <button class="icon-btn danger" data-action="del-list" data-id="${current.id}" title="${t("stock.delete_list")}"><ha-icon icon="mdi:delete"></ha-icon></button>
            </div>`
          : ""
      }
      <div class="filters">
        <input type="search" placeholder="${t("stock.search")}" data-filter="text" value="${esc(f.text)}">
        <select data-filter="category">
          <option value="">${t("stock.all_categories")}</option>
          ${this._data.categories.map((c) => `<option value="${esc(c.id)}" ${f.category === c.id ? "selected" : ""}>${esc(this._catName(c))}</option>`).join("")}
        </select>
        <select data-filter="status">
          ${statusOptions.map(([v, l]) => `<option value="${v}" ${f.status === v ? "selected" : ""}>${esc(l)}</option>`).join("")}
        </select>
        ${
          this._data.locations.length
            ? `<select data-filter="location">
                <option value="">${t("stock.all_locations")}</option>
                ${this._data.locations.map((l) => `<option value="${esc(l)}" ${f.location === l ? "selected" : ""}>${esc(l)}</option>`).join("")}
                <option value="${NO_LOCATION}" ${f.location === NO_LOCATION ? "selected" : ""}>${t("stock.no_location")}</option>
              </select>`
            : ""
        }
        <label class="toggle"><input type="checkbox" data-filter="shopping" ${f.shopping ? "checked" : ""}> ${t("stock.shopping_list")}</label>
        <button class="${this._selecting ? "active" : ""}" data-action="toggle-select"><ha-icon icon="mdi:checkbox-multiple-marked-outline"></ha-icon>${t(this._selecting ? "stock.done" : "stock.select")}</button>
        <button class="primary" data-action="add-item"><ha-icon icon="mdi:plus"></ha-icon>${t("stock.add_item")}</button>
      </div>
      <div id="item-table"></div>`;
  }

  _renderItemTable() {
    const container = this.shadowRoot.getElementById("item-table");
    if (!container) return;
    const items = this._filteredItems();
    // Auswahl auf sichtbare Artikel beschränken, damit keine versteckten Artikel mitgeändert werden
    const visible = new Set(items.map((i) => i.id));
    for (const id of this._selected) if (!visible.has(id)) this._selected.delete(id);
    const bulkBar = this._selecting ? this._renderBulkBar(items) : "";
    if (!items.length) {
      container.innerHTML = `${bulkBar}<div class="card empty small"><ha-icon icon="mdi:magnify"></ha-icon>${esc(this._t("stock.no_items"))}</div>`;
      return;
    }
    const groups = this._data.categories
      .map((cat) => ({ cat, items: items.filter((i) => i.category === cat.id) }))
      .filter((g) => g.items.length);
    const orphan = items.filter((i) => !this._data.categories.some((c) => c.id === i.category));
    if (orphan.length) groups.push({ cat: this._category("sonstiges"), items: orphan });

    const sortKey = (i) => (i.days_left === null ? 1e9 : i.days_left);
    container.innerHTML = bulkBar + groups
      .map(
        ({ cat, items: gi }) => `
        <section class="card group">
          <div class="group-head"><ha-icon icon="${esc(cat.icon)}"></ha-icon>${esc(this._catName(cat))}<span class="count">${gi.length}</span></div>
          ${gi
            .sort((a, b) => sortKey(a) - sortKey(b) || a.name.localeCompare(b.name, this._locale))
            .map((i) => this._renderItemRow(i))
            .join("")}
        </section>`,
      )
      .join("");
  }

  _renderBulkBar(items) {
    const t = (key, params) => esc(this._t(key, params));
    const count = this._selected.size;
    const all = items.length > 0 && items.every((i) => this._selected.has(i.id));
    const action = (id, icon, label, cls = "") =>
      `<button class="${cls}" data-action="bulk" data-id="${id}" ${count ? "" : "disabled"}><ha-icon icon="${icon}"></ha-icon>${label}</button>`;
    return `
      <div class="card bulk-bar">
        <label class="toggle"><input type="checkbox" data-action="select-all" ${all ? "checked" : ""}> ${t("stock.select_all")}</label>
        <span class="grow sub">${t("stock.selected", { count })}</span>
        ${action("buy", "mdi:cart-check", t("stock.bulk_buy"))}
        ${action("list_id", "mdi:folder-move-outline", t("stock.bulk_move"))}
        ${action("category", "mdi:shape-outline", t("stock.bulk_category"))}
        ${action("location", "mdi:map-marker-outline", t("stock.bulk_location"))}
        ${action("delete", "mdi:delete", t("stock.bulk_delete"), "danger")}
      </div>`;
  }

  _renderItemRow(i) {
    const t = (key, params) => esc(this._t(key, params));
    const sub = [!this._listId ? i.list_name : "", i.location, i.notes].filter(Boolean).map(esc).join(" · ");
    const target = i.target_quantity ? ` / ${this._fmtNum(i.target_quantity)}` : "";
    const missing =
      i.missing > 0
        ? `<div class="sub warn-text">${t("stock.missing_qty", { quantity: `${this._fmtNum(i.missing)} ${i.unit}` })}</div>`
        : "";
    return `
      <div class="item-row status-${i.status} ${this._selecting ? "selecting" : ""}">
        ${this._selecting ? `<input type="checkbox" class="item-check" data-action="select-item" data-id="${i.id}" ${this._selected.has(i.id) ? "checked" : ""}>` : ""}
        <div class="item-name">
          <div class="title">${esc(i.name)}</div>
          ${sub ? `<div class="sub">${sub}</div>` : ""}
        </div>
        <div class="item-qty">
          <button class="icon-btn small" data-action="dec" data-id="${i.id}" title="−1"><ha-icon icon="mdi:minus"></ha-icon></button>
          <div class="qty-text"><b>${this._fmtNum(i.quantity)}</b>${target} ${esc(i.unit)}${missing}</div>
          <button class="icon-btn small" data-action="inc" data-id="${i.id}" title="+1"><ha-icon icon="mdi:plus"></ha-icon></button>
        </div>
        <div class="item-date"><span class="label">${t("stock.purchased")}</span>${this._fmtDate(i.purchase_date)}</div>
        <div class="item-exp">
          <span class="badge ${i.status}">${esc(this._expiryText(i))}</span>
          ${i.effective_expiry ? `<div class="sub">${this._fmtDate(i.effective_expiry)}</div>` : ""}
          ${i.opened_date ? `<div class="sub opened"><ha-icon icon="mdi:package-variant"></ha-icon>${t("stock.opened_since", { date: this._fmtDate(i.opened_date) })}</div>` : ""}
        </div>
        <div class="item-actions">
          ${i.quantity > 0 && !i.opened_date ? `<button class="icon-btn" data-action="open-item" data-id="${i.id}" title="${t("stock.open")}"><ha-icon icon="mdi:package-variant"></ha-icon></button>` : ""}
          ${i.missing > 0 ? `<button class="icon-btn accent" data-action="buy" data-id="${i.id}" title="${t("stock.buy")}"><ha-icon icon="mdi:cart-check"></ha-icon></button>` : ""}
          <button class="icon-btn" data-action="edit-item" data-id="${i.id}" title="${t("stock.edit")}"><ha-icon icon="mdi:pencil"></ha-icon></button>
          <button class="icon-btn" data-action="dup-item" data-id="${i.id}" title="${t("stock.duplicate")}"><ha-icon icon="mdi:content-copy"></ha-icon></button>
          <button class="icon-btn danger" data-action="del-item" data-id="${i.id}" title="${t("stock.delete")}"><ha-icon icon="mdi:delete"></ha-icon></button>
        </div>
      </div>`;
  }

  // ----------------------------------------------------------- Vorlagen

  _renderTemplates() {
    const t = (key, params) => esc(this._t(key, params));
    const td = this._tplData;
    if (!td) return `<div class="loading">${t("panel.loading")}</div>`;
    const errors = td.errors.length
      ? `<div class="card error-box"><b>${t("templates.invalid")}</b><ul>${td.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></div>`
      : "";
    const cards = td.templates
      .map(
        (tpl) => `
        <button class="card tpl-card ${this._tpl.id === tpl.id ? "active" : ""}" data-action="select-tpl" data-id="${esc(tpl.id)}">
          <div class="tpl-head">
            <ha-icon icon="mdi:clipboard-list-outline"></ha-icon>
            <div class="title grow">${esc(tpl.name)}</div>
            <span class="pill">${t(tpl.source === "user" ? "templates.source_user" : "templates.source_builtin")}</span>
          </div>
          <div class="sub">${esc(tpl.description)}</div>
          <div class="sub">${t("common.positions", { count: tpl.item_count })}</div>
        </button>`,
      )
      .join("");

    const userDir = esc(this._t("templates.user_dir", { path: "\u0000" })).replace("\u0000", `<code>${esc(td.user_template_dir)}</code>`);
    return `
      <div class="tpl-intro">
        <div class="grow">
          <h2>${t("templates.title")}</h2>
          <div class="sub">${userDir}</div>
        </div>
        <button data-action="reload-tpl"><ha-icon icon="mdi:refresh"></ha-icon>${t("templates.reload")}</button>
      </div>
      ${errors}
      <div class="tpl-grid">${cards || `<div class="card empty small">${t("templates.none")}</div>`}</div>
      ${this._tpl.id ? this._renderTplConfig() : ""}`;
  }

  _defaultListName(tpl) {
    const s = this._tpl;
    return this._t("templates.list_name", {
      name: tpl.name,
      persons: this._t("common.persons", { count: s.persons }),
      days: this._t("common.days", { count: s.days }),
    });
  }

  _renderTplConfig() {
    const t = (key, params) => esc(this._t(key, params));
    const tpl = this._tplData.templates.find((x) => x.id === this._tpl.id);
    if (!tpl) return "";
    const s = this._tpl;
    const lists = this._data.lists;
    return `
      <section class="card tpl-config">
        <h2>${t("templates.calculate", { name: tpl.name })}</h2>
        <div class="tpl-form">
          <label>${t("templates.persons")}
            <div class="stepper">
              <button class="icon-btn small" data-action="tpl-persons" data-id="-1"><ha-icon icon="mdi:minus"></ha-icon></button>
              <input type="number" min="1" max="100" data-tpl="persons" value="${s.persons}">
              <button class="icon-btn small" data-action="tpl-persons" data-id="1"><ha-icon icon="mdi:plus"></ha-icon></button>
            </div>
          </label>
          <label>${t("templates.days")}
            <input type="number" min="1" max="3650" data-tpl="days" value="${s.days}">
            <div class="quick">${[3, 10, 14, 30, 90].map((d) => `<button class="chip small ${s.days === d ? "active" : ""}" data-action="tpl-days" data-id="${d}">${d}</button>`).join("")}</div>
          </label>
          <label>${t("templates.apply_to")}
            <select data-tpl="mode">
              <option value="new" ${s.mode === "new" ? "selected" : ""}>${t("templates.new_list")}</option>
              ${lists.length ? `<option value="existing" ${s.mode === "existing" ? "selected" : ""}>${t("templates.existing_list")}</option>` : ""}
            </select>
            ${
              s.mode === "existing" && lists.length
                ? `<select data-tpl="listId">${lists.map((l) => `<option value="${l.id}" ${s.listId === l.id ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select>`
                : `<input type="text" data-tpl="listName" placeholder="${esc(this._defaultListName(tpl))}" value="${esc(s.listName)}">`
            }
          </label>
        </div>
        <div id="tpl-preview">${this._renderTplPreview()}</div>
        <div class="row-actions end">
          <button class="primary" data-action="apply-tpl"><ha-icon icon="mdi:cart-plus"></ha-icon>${t("templates.apply")}</button>
        </div>
      </section>`;
  }

  _renderTplPreview() {
    const t = (key, params) => esc(this._t(key, params));
    const items = this._tpl.preview;
    if (!items) return `<div class="loading">${t("templates.calculating")}</div>`;
    if (!items.length) return `<div class="empty small">${t("templates.no_positions")}</div>`;
    const rows = this._data.categories
      .concat([{ id: "__other", name: this._t("category.sonstiges"), icon: "mdi:tag" }])
      .map((cat) => {
        const ci = items.filter((i) =>
          cat.id === "__other" ? !this._data.categories.some((c) => c.id === i.category) : i.category === cat.id,
        );
        if (!ci.length) return "";
        return `<tr class="cat"><td colspan="2"><ha-icon icon="${esc(cat.icon)}"></ha-icon>${esc(this._catName(cat))}</td></tr>
          ${ci.map((i) => `<tr><td>${esc(i.name)}${i.notes ? `<div class="sub">${esc(i.notes)}</div>` : ""}</td><td class="num">${this._fmtNum(i.quantity)} ${esc(i.unit)}</td></tr>`).join("")}`;
      })
      .join("");
    const summary = t("templates.preview_summary", {
      persons: this._t("common.persons", { count: this._tpl.persons }),
      days: this._t("common.days", { count: this._tpl.days }),
      positions: this._t("common.positions", { count: items.length }),
    });
    // Reichweite der berechneten Mengen für die gewählte Personenzahl
    const { kcal_per_day: kcalDay, water_per_day: waterDay } = this._data.settings;
    const persons = this._tpl.persons;
    const total = (key) => items.reduce((sum, i) => sum + i.quantity * (i[key] || 0), 0);
    const known = [
      total("kcal_per_unit") > 0 ? total("kcal_per_unit") / (persons * kcalDay) : null,
      total("water_per_unit") > 0 ? total("water_per_unit") / (persons * waterDay) : null,
    ].filter((d) => d !== null);
    const range = known.length
      ? ` · ${t("templates.preview_range", { days: this._i18n.rangeText(Math.min(...known)) })}`
      : "";
    return `<div class="sub">${summary}${range}</div>
      <table class="preview"><tbody>${rows}</tbody></table>`;
  }

  async _updatePreview() {
    const s = this._tpl;
    if (!s.id) return;
    const requestId = (this._previewRequest = (this._previewRequest || 0) + 1);
    try {
      const res = await this._hass.callWS({
        type: "prep_assistent/template/preview",
        template_id: s.id,
        persons: s.persons,
        days: s.days,
        language: this._lang,
      });
      if (requestId !== this._previewRequest) return;
      s.preview = res.items;
    } catch (err) {
      s.preview = [];
      this._toast(this._t("templates.preview_error", { error: this._errText(err) }));
    }
    const el = this.shadowRoot.getElementById("tpl-preview");
    if (el) el.innerHTML = this._renderTplPreview();
  }

  _schedulePreview() {
    clearTimeout(this._previewTimer);
    this._previewTimer = setTimeout(() => this._updatePreview(), 250);
  }

  // ----------------------------------------------------------- Verwalten

  _renderManage() {
    const t = (key, params) => esc(this._t(key, params));
    const items = this._data.items;
    const cats = this._data.categories;
    const catRows = cats
      .map((cat, index) => {
        const count = items.filter((i) => i.category === cat.id).length;
        return `
          <div class="manage-row">
            <ha-icon icon="${esc(cat.icon)}"></ha-icon>
            <div class="grow">
              <div class="title">${esc(this._catName(cat))}</div>
              <div class="sub">${t("common.items", { count })}</div>
            </div>
            <button class="icon-btn small" data-action="cat-up" data-id="${esc(cat.id)}" title="${t("manage.move_up")}" ${index === 0 ? "disabled" : ""}><ha-icon icon="mdi:arrow-up"></ha-icon></button>
            <button class="icon-btn small" data-action="cat-down" data-id="${esc(cat.id)}" title="${t("manage.move_down")}" ${index === cats.length - 1 ? "disabled" : ""}><ha-icon icon="mdi:arrow-down"></ha-icon></button>
            <button class="icon-btn" data-action="edit-cat" data-id="${esc(cat.id)}" title="${t("stock.edit")}"><ha-icon icon="mdi:pencil"></ha-icon></button>
            ${cat.id === "sonstiges" ? `<span class="icon-placeholder"></span>` : `<button class="icon-btn danger" data-action="del-cat" data-id="${esc(cat.id)}" title="${t("stock.delete")}"><ha-icon icon="mdi:delete"></ha-icon></button>`}
          </div>`;
      })
      .join("");
    const locRows = this._data.locations
      .map((loc) => {
        const count = items.filter((i) => i.location?.toLowerCase() === loc.toLowerCase()).length;
        return `
          <div class="manage-row">
            <ha-icon icon="mdi:map-marker-outline"></ha-icon>
            <button class="grow plain" data-action="goto-location" data-id="${esc(loc)}">
              <div class="title">${esc(loc)}</div>
              <div class="sub">${t("common.items", { count })}</div>
            </button>
            <button class="icon-btn" data-action="edit-loc" data-id="${esc(loc)}" title="${t("stock.edit")}"><ha-icon icon="mdi:pencil"></ha-icon></button>
            <button class="icon-btn danger" data-action="del-loc" data-id="${esc(loc)}" title="${t("stock.delete")}"><ha-icon icon="mdi:delete"></ha-icon></button>
          </div>`;
      })
      .join("");
    return `
      <div class="columns even">
        <section class="card">
          <div class="section-head"><h2 class="grow">${t("manage.categories")}</h2>
            <button data-action="add-cat"><ha-icon icon="mdi:plus"></ha-icon>${t("manage.add_category")}</button></div>
          <div class="sub hint">${t("manage.categories_hint")}</div>
          ${catRows}
        </section>
        <section class="card">
          <div class="section-head"><h2 class="grow">${t("manage.locations")}</h2>
            <button data-action="add-loc"><ha-icon icon="mdi:plus"></ha-icon>${t("manage.add_location")}</button></div>
          <div class="sub hint">${t("manage.locations_hint")}</div>
          ${locRows || `<div class="empty small">${t("manage.no_locations")}</div>`}
        </section>
      </div>`;
  }

  _openCategoryDialog(cat) {
    const t = (key, params) => esc(this._t(key, params));
    this._dialog = { kind: "category", categoryId: cat?.id || null };
    this._showDialog(
      this._t(cat ? "dialog.edit_category" : "dialog.new_category"),
      `
      <label class="span2">${t("dialog.name")}<input name="name" required maxlength="200" value="${esc(cat ? this._catName(cat) : "")}"></label>
      <label class="span2">${t("dialog.icon")}
        <div class="icon-input"><ha-icon icon="${esc(cat?.icon || "mdi:tag")}" id="icon-preview"></ha-icon>
        <input name="icon" maxlength="100" value="${esc(cat?.icon || "mdi:tag")}" placeholder="mdi:tag" data-icon-preview></div>
        <span class="sub">${t("dialog.icon_help")}</span>
      </label>`,
    );
  }

  _openLocationDialog(name) {
    const t = (key, params) => esc(this._t(key, params));
    this._dialog = { kind: "location", old: name || null };
    this._showDialog(
      this._t(name ? "dialog.edit_location" : "dialog.new_location"),
      `<label class="span2">${t("dialog.name")}<input name="name" required maxlength="100" value="${esc(name)}" placeholder="${t("dialog.location_placeholder")}"></label>`,
    );
  }

  _openBulkDialog(field) {
    const t = (key, params) => esc(this._t(key, params));
    this._dialog = { kind: "bulk", field };
    const count = this._selected.size;
    let input;
    if (field === "list_id") {
      input = `<select name="value">${this._data.lists.map((l) => `<option value="${l.id}">${esc(l.name)}</option>`).join("")}</select>`;
    } else if (field === "category") {
      input = `<select name="value">${this._data.categories.map((c) => `<option value="${esc(c.id)}">${esc(this._catName(c))}</option>`).join("")}</select>`;
    } else {
      input = `<input name="value" maxlength="100" list="locations" placeholder="${t("dialog.location_clear")}">
        <datalist id="locations">${this._data.locations.map((l) => `<option value="${esc(l)}">`).join("")}</datalist>`;
    }
    this._showDialog(this._t(`dialog.bulk_${field}`, { count }), `<label class="span2">${t(`stock.bulk_${field === "list_id" ? "move" : field}`)}${input}</label>`);
  }

  async _bulk(action, extra = {}) {
    const ids = [...this._selected];
    if (!ids.length) return;
    const res = await this._ws({ type: "prep_assistent/items/bulk", item_ids: ids, action, ...extra });
    this._toast(this._t(action === "buy" ? "toast.bought" : action === "delete" ? "toast.items_deleted" : "toast.bulk_done", { count: res.count }));
    this._selected.clear();
  }

  async _moveCategory(id, delta) {
    const ids = this._data.categories.map((c) => c.id);
    const index = ids.indexOf(id);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    await this._ws({ type: "prep_assistent/category/reorder", category_ids: ids }).catch(() => {});
  }

  // ------------------------------------------------------------- Dialoge

  _openItemDialog(mode, item) {
    const t = (key, params) => esc(this._t(key, params));
    const today = this._data.today;
    const listId = item?.list_id || this._listId || this._data.lists[0]?.id;
    const v = { ...(item || {}) };
    if (mode === "buy") {
      v.quantity = Math.max(item.target_quantity ?? 0, item.quantity);
      v.purchase_date = today;
      v.opened_date = "";
      if (item.shelf_life_days) v.expiry_date = addDays(today, item.shelf_life_days);
    } else if (mode === "duplicate") {
      v.quantity = 1;
      v.target_quantity = null;
      v.purchase_date = today;
      v.opened_date = "";
      v.expiry_date = item.shelf_life_days ? addDays(today, item.shelf_life_days) : "";
    } else if (mode === "create") {
      v.category = this._filter.category || "lebensmittel";
      v.unit = this._t("unit.pcs");
      v.quantity = 1;
      v.purchase_date = today;
    }
    const titles = { create: "dialog.add_item", edit: "dialog.edit_item", buy: "dialog.buy_item", duplicate: "dialog.duplicate_item" };
    this._dialog = { kind: "item", mode, itemId: mode === "edit" || mode === "buy" ? item.id : null };
    const extras = ["shelf_life_days", "opened_date", "opened_shelf_life_days", "kcal_per_unit", "water_per_unit"];
    const openExtras = mode === "edit" && extras.some((k) => v[k] !== null && v[k] !== undefined && v[k] !== "");
    this._showDialog(
      this._t(titles[mode]),
      `
      <label class="span2">${t("dialog.name")}<input name="name" required maxlength="200" value="${esc(v.name)}"></label>
      <label>${t("dialog.list")}<select name="list_id">${this._data.lists.map((l) => `<option value="${l.id}" ${l.id === listId ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select></label>
      <label>${t("dialog.category")}<select name="category">${this._data.categories.map((c) => `<option value="${esc(c.id)}" ${c.id === v.category ? "selected" : ""}>${esc(this._catName(c))}</option>`).join("")}</select></label>
      <label>${t("dialog.quantity")}<input name="quantity" type="number" step="any" min="0" required value="${v.quantity ?? 0}"></label>
      <label>${t("dialog.unit")}<input name="unit" maxlength="30" list="units" value="${esc(v.unit ?? this._t("unit.pcs"))}"></label>
      <label>${t("dialog.target_quantity")}<input name="target_quantity" type="number" step="any" min="0" value="${v.target_quantity ?? ""}" placeholder="${t("dialog.optional")}"></label>
      <label>${t("dialog.location")}<input name="location" maxlength="100" list="locations" value="${esc(v.location)}" placeholder="${t("dialog.location_placeholder")}"></label>
      <label>${t("dialog.purchase_date")}<input name="purchase_date" type="date" value="${esc(v.purchase_date)}"></label>
      <label>${t("dialog.expiry_date")}<input name="expiry_date" type="date" value="${esc(v.expiry_date)}"></label>
      <label class="span2">${t("dialog.notes")}<textarea name="notes" rows="2" maxlength="1000">${esc(v.notes)}</textarea></label>
      <details class="span2 more" ${openExtras ? "open" : ""}>
        <summary>${t("dialog.more")}</summary>
        <div class="form-grid">
          <label>${t("dialog.shelf_life_days")}<input name="shelf_life_days" type="number" min="0" step="1" value="${v.shelf_life_days ?? ""}" placeholder="${t("dialog.optional")}"></label>
          <label>${t("dialog.opened_shelf_life_days")}<input name="opened_shelf_life_days" type="number" min="0" step="1" value="${v.opened_shelf_life_days ?? ""}" placeholder="${t("dialog.optional")}"></label>
          <label>${t("dialog.opened_date")}<input name="opened_date" type="date" value="${esc(v.opened_date)}"></label>
          <span></span>
          <label>${t("dialog.kcal_per_unit")}<input name="kcal_per_unit" type="number" min="0" step="any" value="${v.kcal_per_unit ?? ""}" placeholder="${t("dialog.optional")}"></label>
          <label>${t("dialog.water_per_unit")}<input name="water_per_unit" type="number" min="0" step="any" value="${v.water_per_unit ?? ""}" placeholder="${t("dialog.optional")}"></label>
          <div class="span2 sub">${t("dialog.range_help")}</div>
        </div>
      </details>
      <datalist id="units">${DIALOG_UNITS.map((u) => `<option value="${t(`unit.${u}`)}">`).join("")}</datalist>
      <datalist id="locations">${this._data.locations.map((l) => `<option value="${esc(l)}">`).join("")}</datalist>`,
    );
  }

  _openListDialog(list) {
    const t = (key, params) => esc(this._t(key, params));
    this._dialog = { kind: "list", listId: list?.id || null };
    this._showDialog(
      this._t(list ? "dialog.edit_list" : "dialog.new_list"),
      `
      <label class="span2">${t("dialog.name")}<input name="name" required maxlength="200" value="${esc(list?.name)}" placeholder="${t("dialog.list_name_placeholder")}"></label>
      <label class="span2">${t("dialog.description")}<textarea name="description" rows="2" maxlength="500">${esc(list?.description)}</textarea></label>`,
    );
  }

  _showDialog(title, fields) {
    this.shadowRoot.getElementById("dialog").innerHTML = `
      <div class="overlay" data-overlay>
        <form class="dialog" id="dialog-form" novalidate>
          <h2>${esc(title)}</h2>
          <div class="form-grid">${fields}</div>
          <div class="form-error" id="form-error"></div>
          <div class="row-actions end">
            <button type="button" data-action="close-dialog">${esc(this._t("dialog.cancel"))}</button>
            <button type="submit" class="primary">${esc(this._t("dialog.save"))}</button>
          </div>
        </form>
      </div>`;
    this.shadowRoot.querySelector("#dialog-form input, #dialog-form select")?.focus();
  }

  _closeDialog() {
    this._dialog = null;
    this.shadowRoot.getElementById("dialog").innerHTML = "";
  }

  async _onSubmit(ev) {
    ev.preventDefault();
    const form = ev.target;
    const errorEl = this.shadowRoot.getElementById("form-error");
    if (!form.checkValidity()) {
      errorEl.textContent = this._t("dialog.check_required");
      form.reportValidity();
      return;
    }
    const data = Object.fromEntries(new FormData(form).entries());
    const d = this._dialog;
    try {
      if (d.kind === "list") {
        if (d.listId) {
          await this._hass.callWS({ type: "prep_assistent/list/update", list_id: d.listId, ...data });
        } else {
          const list = await this._hass.callWS({ type: "prep_assistent/list/create", ...data });
          this._listId = list.id;
          this._tab = "stock";
        }
      } else if (d.kind === "category") {
        if (d.categoryId) {
          const cat = this._category(d.categoryId);
          const changes = { icon: data.icon };
          // Unveränderte (übersetzte) Namen von Standardkategorien nicht als Umbenennung speichern
          if (data.name !== this._catName(cat)) changes.name = data.name;
          await this._hass.callWS({ type: "prep_assistent/category/update", category_id: d.categoryId, ...changes });
        } else {
          await this._hass.callWS({ type: "prep_assistent/category/create", name: data.name, icon: data.icon });
        }
      } else if (d.kind === "location") {
        if (d.old) await this._hass.callWS({ type: "prep_assistent/location/rename", old: d.old, new: data.name.trim() });
        else await this._hass.callWS({ type: "prep_assistent/location/create", name: data.name.trim() });
      } else if (d.kind === "bulk") {
        await this._bulk("update", { [d.field]: data.value ?? "" });
        this._closeDialog();
        return;
      } else {
        const optional = (value) => (value === "" || value === undefined ? null : Number(value));
        const payload = {
          ...data,
          quantity: Number(data.quantity || 0),
          target_quantity: optional(data.target_quantity),
          purchase_date: data.purchase_date || null,
          expiry_date: data.expiry_date || null,
          opened_date: data.opened_date || null,
          shelf_life_days: optional(data.shelf_life_days),
          opened_shelf_life_days: optional(data.opened_shelf_life_days),
          kcal_per_unit: optional(data.kcal_per_unit),
          water_per_unit: optional(data.water_per_unit),
        };
        if (d.itemId) {
          await this._hass.callWS({ type: "prep_assistent/item/update", item_id: d.itemId, ...payload });
        } else {
          await this._hass.callWS({ type: "prep_assistent/item/create", ...payload });
        }
      }
    } catch (err) {
      errorEl.textContent = this._errText(err);
      return;
    }
    this._closeDialog();
    this._toast(this._t("toast.saved"));
  }

  // ------------------------------------------------------------ Events

  async _onClick(ev) {
    if (ev.target.matches?.("[data-overlay]")) {
      this._closeDialog();
      return;
    }
    const el = ev.target.closest?.("[data-action]");
    if (!el) return;
    const { action, id } = el.dataset;
    const item = () => this._data.items.find((i) => i.id === id);

    switch (action) {
      case "tab":
        this._tab = id;
        this._render();
        if (id === "templates" && this._tpl.id) this._schedulePreview();
        break;
      case "goto-status":
        this._tab = "stock";
        this._listId = "";
        this._filter = { ...EMPTY_FILTER, status: id };
        this._render();
        break;
      case "goto-category":
        this._tab = "stock";
        this._listId = "";
        this._filter = { ...EMPTY_FILTER, category: id };
        this._render();
        break;
      case "open-list":
      case "select-list":
        this._tab = "stock";
        this._listId = id;
        this._render();
        break;
      case "add-list":
        this._openListDialog(null);
        break;
      case "edit-list":
        this._openListDialog(this._list(id));
        break;
      case "del-list": {
        const list = this._list(id);
        const count = this._data.items.filter((i) => i.list_id === id).length;
        if (confirm(this._t("confirm.delete_list", { name: list.name, count }))) {
          await this._ws({ type: "prep_assistent/list/delete", list_id: id }, this._t("toast.list_deleted")).catch(() => {});
          this._listId = "";
        }
        break;
      }
      case "add-item":
        if (!this._data.lists.length) this._openListDialog(null);
        else this._openItemDialog("create");
        break;
      case "edit-item":
        this._openItemDialog("edit", item());
        break;
      case "buy":
        this._openItemDialog("buy", item());
        break;
      case "dup-item":
        this._openItemDialog("duplicate", item());
        break;
      case "del-item":
        if (confirm(this._t("confirm.delete_item", { name: item().name }))) {
          await this._ws({ type: "prep_assistent/item/delete", item_id: id }, this._t("toast.item_deleted")).catch(() => {});
        }
        break;
      case "inc":
      case "dec":
        await this._ws({ type: "prep_assistent/item/adjust", item_id: id, delta: action === "inc" ? 1 : -1 }).catch(() => {});
        break;
      case "close-dialog":
        this._closeDialog();
        break;
      case "open-item": {
        const opened = await this._ws({ type: "prep_assistent/item/open", item_id: id }).catch(() => null);
        if (opened) this._toast(this._t("toast.opened", { name: opened.name }));
        break;
      }
      case "toggle-select":
        this._selecting = !this._selecting;
        this._selected.clear();
        this._render();
        break;
      case "select-item":
        if (el.checked) this._selected.add(id);
        else this._selected.delete(id);
        this._renderItemTable();
        break;
      case "select-all": {
        const ids = this._filteredItems().map((i) => i.id);
        this._selected = el.checked ? new Set(ids) : new Set();
        this._renderItemTable();
        break;
      }
      case "bulk":
        if (!this._selected.size) break;
        if (id === "buy") await this._bulk("buy").catch(() => {});
        else if (id === "delete") {
          if (confirm(this._t("confirm.bulk_delete", { count: this._selected.size }))) await this._bulk("delete").catch(() => {});
        } else this._openBulkDialog(id);
        break;
      case "range-persons":
        this._rangePersons = Math.min(100, Math.max(1, (this._rangePersons || this._data.range.persons) + Number(id)));
        this._render();
        break;
      case "add-cat":
        this._openCategoryDialog(null);
        break;
      case "edit-cat":
        this._openCategoryDialog(this._category(id));
        break;
      case "del-cat": {
        const cat = this._category(id);
        const count = this._data.items.filter((i) => i.category === id).length;
        if (confirm(this._t("confirm.delete_category", { name: this._catName(cat), count }))) {
          await this._ws({ type: "prep_assistent/category/delete", category_id: id }, this._t("toast.saved")).catch(() => {});
        }
        break;
      }
      case "cat-up":
      case "cat-down":
        await this._moveCategory(id, action === "cat-up" ? -1 : 1);
        break;
      case "add-loc":
        this._openLocationDialog(null);
        break;
      case "edit-loc":
        this._openLocationDialog(id);
        break;
      case "del-loc": {
        const count = this._data.items.filter((i) => i.location?.toLowerCase() === id.toLowerCase()).length;
        if (confirm(this._t("confirm.delete_location", { name: id, count }))) {
          await this._ws({ type: "prep_assistent/location/delete", name: id }, this._t("toast.saved")).catch(() => {});
        }
        break;
      }
      case "goto-location":
        this._tab = "stock";
        this._listId = "";
        this._filter = { ...EMPTY_FILTER, location: id };
        this._render();
        break;
      case "select-tpl": {
        const tpl = this._tplData.templates.find((x) => x.id === id);
        this._tpl = { ...this._tpl, id, persons: tpl.default_persons, days: tpl.default_days, listName: "", preview: null };
        this._render();
        this._updatePreview();
        this.shadowRoot.querySelector(".tpl-config")?.scrollIntoView({ behavior: "smooth", block: "start" });
        break;
      }
      case "tpl-persons":
        this._tpl.persons = Math.min(100, Math.max(1, this._tpl.persons + Number(id)));
        this._render();
        this._schedulePreview();
        break;
      case "tpl-days":
        this._tpl.days = Number(id);
        this._render();
        this._schedulePreview();
        break;
      case "reload-tpl":
        await this._loadTemplates(true);
        if (this._tpl.id) this._schedulePreview();
        break;
      case "apply-tpl":
        await this._applyTemplate();
        break;
    }
  }

  _onInput(ev) {
    const el = ev.target;
    if (el.dataset && "iconPreview" in el.dataset) {
      this.shadowRoot.getElementById("icon-preview")?.setAttribute("icon", el.value.trim() || "mdi:tag");
      return;
    }
    if (el.dataset?.range === "persons") {
      const n = parseInt(el.value, 10);
      if (!Number.isFinite(n) || n < 1) return;
      this._rangePersons = Math.min(n, 100);
      if (ev.type === "change") this._render();
      return;
    }
    if (el.dataset?.filter) {
      const key = el.dataset.filter;
      this._filter[key] = el.type === "checkbox" ? el.checked : el.value;
      this._renderItemTable();
      return;
    }
    if (el.dataset?.tpl) {
      const key = el.dataset.tpl;
      if (key === "persons" || key === "days") {
        const n = parseInt(el.value, 10);
        if (!Number.isFinite(n) || n < 1) return;
        this._tpl[key] = Math.min(n, key === "persons" ? 100 : 3650);
        if (ev.type === "change") this._render();
        this._schedulePreview();
      } else if (key === "mode") {
        this._tpl.mode = el.value;
        if (el.value === "existing" && !this._tpl.listId) this._tpl.listId = this._data.lists[0]?.id || "";
        this._render();
      } else {
        this._tpl[key] = el.value;
      }
    }
  }

  async _applyTemplate() {
    const s = this._tpl;
    const msg = {
      type: "prep_assistent/template/apply",
      template_id: s.id,
      persons: s.persons,
      days: s.days,
      language: this._lang,
    };
    if (s.mode === "existing" && s.listId) msg.list_id = s.listId;
    else if (s.listName.trim()) msg.list_name = s.listName.trim();
    let res;
    try {
      res = await this._ws(msg);
    } catch {
      return;
    }
    this._toast(this._t("templates.applied", { name: res.list_name, created: res.created, updated: res.updated }));
    this._tab = "stock";
    this._listId = res.list_id;
    this._filter = { ...EMPTY_FILTER, shopping: true };
    await this._load();
  }
}

const STYLES = `
  :host {
    display: block;
    min-height: 100vh;
    background: var(--primary-background-color);
    color: var(--primary-text-color);
    font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
    --pa-radius: var(--ha-card-border-radius, 12px);
    --pa-warning: var(--warning-color, #ffa600);
    --pa-error: var(--error-color, #db4437);
    --pa-success: var(--success-color, #43a047);
    --pa-info: var(--info-color, #039be5);
  }
  * { box-sizing: border-box; }
  .toolbar {
    display: flex; align-items: center; gap: 8px;
    height: var(--header-height, 56px); padding: 0 12px;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, #fff);
    border-bottom: var(--app-header-border-bottom, none);
  }
  .main-title { font-size: 20px; flex: 1; margin-left: 4px; }
  .toolbar-info { font-size: 13px; opacity: .8; }
  .tabs {
    display: flex; gap: 4px; padding: 0 12px; overflow-x: auto;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, #fff);
  }
  .tab {
    display: flex; align-items: center; gap: 6px; padding: 10px 14px;
    background: none; border: none; color: inherit; opacity: .75; cursor: pointer;
    border-bottom: 3px solid transparent; font: inherit; font-size: 14px; white-space: nowrap;
  }
  .tab.active { opacity: 1; border-bottom-color: currentColor; }
  main { padding: 16px; max-width: 1200px; margin: 0 auto; }
  h2 { font-size: 18px; font-weight: 500; margin: 0 0 12px; }
  .section-title { margin: 24px 0 12px; }
  .card {
    background: var(--card-background-color, #fff);
    border-radius: var(--pa-radius);
    box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.12));
    border: 1px solid var(--ha-card-border-color, var(--divider-color, transparent));
    padding: 16px; color: inherit;
  }
  button { font: inherit; color: inherit; }
  button.card { text-align: left; cursor: pointer; width: 100%; }
  .grow { flex: 1; min-width: 0; }
  .title { font-weight: 500; overflow-wrap: anywhere; }
  .sub { font-size: 12.5px; color: var(--secondary-text-color); margin-top: 2px; }
  .warn-text { color: var(--pa-warning); }
  .loading, .empty { padding: 32px; text-align: center; color: var(--secondary-text-color); }
  .empty ha-icon { --mdc-icon-size: 40px; display: block; margin: 0 auto 8px; }
  .empty.small { padding: 16px; display: flex; align-items: center; gap: 8px; justify-content: center; }
  .empty.small ha-icon { --mdc-icon-size: 22px; display: inline-block; margin: 0; }

  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
  .stat {
    display: flex; align-items: center; gap: 14px; padding: 16px; cursor: pointer; text-align: left;
    background: var(--card-background-color, #fff); border-radius: var(--pa-radius);
    border: 1px solid var(--ha-card-border-color, var(--divider-color, transparent));
    box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.12));
  }
  .stat ha-icon { --mdc-icon-size: 32px; color: var(--primary-color); }
  .stat.warning ha-icon { color: var(--pa-warning); }
  .stat.error ha-icon { color: var(--pa-error); }
  .stat.info ha-icon { color: var(--pa-info); }
  .stat-value { font-size: 28px; font-weight: 500; line-height: 1.1; }
  .stat-label { font-size: 13px; color: var(--secondary-text-color); }

  .columns { display: grid; grid-template-columns: 3fr 2fr; gap: 16px; align-items: start; }
  .attention-row, .cat-row {
    display: flex; align-items: center; gap: 12px; width: 100%; padding: 10px 4px;
    background: none; border: none; border-bottom: 1px solid var(--divider-color); cursor: pointer; text-align: left;
  }
  .attention-row:last-of-type, .cat-row:last-of-type { border-bottom: none; }
  .attention-row ha-icon, .cat-row ha-icon { color: var(--secondary-text-color); }
  .link { background: none; border: none; color: var(--primary-color); cursor: pointer; padding: 8px 4px; }

  .badge {
    display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 12px; white-space: nowrap;
    background: var(--secondary-background-color, #eee); color: var(--secondary-text-color);
  }
  .badge.expired { background: var(--pa-error); color: #fff; }
  .badge.expiring { background: var(--pa-warning); color: #000; }
  .badge.ok { background: color-mix(in srgb, var(--pa-success) 18%, transparent); color: var(--pa-success); }

  .progress { height: 8px; border-radius: 4px; background: var(--secondary-background-color, #eee); overflow: hidden; }
  .progress.thin { height: 5px; }
  .progress > div { height: 100%; background: var(--primary-color); border-radius: inherit; }
  .progress-label { display: flex; justify-content: space-between; font-size: 13px; margin: 8px 0 4px; }
  .cat-row .progress-label { margin-top: 0; }

  .list-grid, .tpl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
  .list-head, .tpl-head { display: flex; align-items: center; gap: 10px; }
  .list-head ha-icon, .tpl-head ha-icon { color: var(--primary-color); }
  .list-card.add {
    display: flex; align-items: center; justify-content: center; gap: 8px;
    color: var(--primary-color); border: 2px dashed var(--divider-color); box-shadow: none; background: none;
  }

  .chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
  .chip {
    display: inline-flex; align-items: center; gap: 4px; padding: 6px 14px; border-radius: 999px; cursor: pointer;
    background: var(--card-background-color, #fff); border: 1px solid var(--divider-color);
  }
  .chip ha-icon { --mdc-icon-size: 16px; }
  .chip.small { padding: 2px 10px; font-size: 12px; }
  .chip.active { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .chip.add { border-style: dashed; color: var(--primary-color); }
  .list-info { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
  .list-info h2 { margin: 0; }

  .filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }
  .filters input[type=search] { flex: 1; min-width: 160px; }
  input, select, textarea {
    font: inherit; color: var(--primary-text-color); padding: 8px 10px; border-radius: 8px;
    border: 1px solid var(--divider-color); background: var(--card-background-color, #fff); width: 100%;
  }
  .filters select, .filters input { width: auto; }
  input:focus, select:focus, textarea:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
  .toggle { display: flex; align-items: center; gap: 6px; font-size: 14px; cursor: pointer; }
  .toggle input { width: auto; }

  button.primary, .row-actions button, .tpl-intro > button, .filters > button, .bulk-bar > button, .section-head > button {
    display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; border-radius: 8px; cursor: pointer;
    border: 1px solid var(--divider-color); background: var(--card-background-color, #fff);
  }
  button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  button.primary ha-icon, .tpl-intro > button ha-icon, .filters > button ha-icon, .bulk-bar > button ha-icon, .section-head > button ha-icon { --mdc-icon-size: 18px; }
  .filters > button.active { border-color: var(--primary-color); color: var(--primary-color); }
  button:disabled { opacity: .45; cursor: default; }
  .bulk-bar > button.danger:not(:disabled):hover { color: var(--pa-error); border-color: var(--pa-error); }
  .row-actions { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; margin-top: 12px; }
  .row-actions.end { justify-content: flex-end; }
  .icon-btn {
    display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px;
    border-radius: 50%; border: none; background: none; cursor: pointer; color: var(--secondary-text-color);
  }
  .icon-btn:hover { background: var(--secondary-background-color, rgba(0,0,0,.06)); }
  .icon-btn.small { width: 28px; height: 28px; }
  .icon-btn.small ha-icon { --mdc-icon-size: 18px; }
  .icon-btn.danger:hover { color: var(--pa-error); }
  .icon-btn.accent { color: var(--primary-color); }

  .group { padding: 0; margin-bottom: 12px; overflow: hidden; }
  .group-head {
    display: flex; align-items: center; gap: 8px; padding: 12px 16px; font-weight: 500;
    border-bottom: 1px solid var(--divider-color);
  }
  .group-head ha-icon { color: var(--primary-color); }
  .count { margin-left: auto; font-size: 12px; color: var(--secondary-text-color); }
  .item-row {
    /* Feste Breite der Aktionsspalte (bis zu 5 Knöpfe), damit die Spalten aller Zeilen fluchten */
    display: grid; grid-template-columns: minmax(0, 2.2fr) 1.4fr 1fr 1.3fr 184px; gap: 12px; align-items: center;
    padding: 10px 16px; border-bottom: 1px solid var(--divider-color); border-left: 4px solid transparent;
  }
  .item-row:last-child { border-bottom: none; }
  .item-row.selecting { grid-template-columns: auto minmax(0, 2.2fr) 1.4fr 1fr 1.3fr 184px; }
  .item-check { width: 18px; height: 18px; margin: 0; cursor: pointer; }
  .sub.opened { display: flex; align-items: center; gap: 3px; justify-content: flex-end; }
  .sub.opened ha-icon { --mdc-icon-size: 14px; }
  .bulk-bar {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 16px; margin-bottom: 12px;
    position: sticky; top: 0; z-index: 2;
  }
  .item-row.status-expired { border-left-color: var(--pa-error); }
  .item-row.status-expiring { border-left-color: var(--pa-warning); }
  .item-qty { display: flex; align-items: center; gap: 4px; }
  .qty-text { min-width: 70px; text-align: center; font-size: 14px; }
  .item-date { font-size: 13px; }
  .item-date .label { display: block; font-size: 11px; color: var(--secondary-text-color); }
  .item-actions { display: flex; justify-content: flex-end; }

  .range-card { margin-bottom: 16px; }
  .range-head { display: flex; align-items: flex-start; gap: 16px; }
  .range-head h2 { margin-bottom: 4px; }
  .range-value { font-size: 28px; font-weight: 500; color: var(--pa-success); }
  .range-value.low { color: var(--pa-warning); }
  .range-persons { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--secondary-text-color); }
  .range-persons input { width: 64px; text-align: center; }
  .range-row { display: flex; gap: 12px; align-items: flex-start; margin-top: 8px; }
  .range-row ha-icon { color: var(--secondary-text-color); margin-top: 8px; }
  .progress.low > div { background: var(--pa-warning); }

  .columns.even { grid-template-columns: 1fr 1fr; }
  .section-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
  .section-head h2 { margin: 0; }
  .hint { margin-bottom: 8px; }
  .manage-row { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--divider-color); }
  .manage-row:last-child { border-bottom: none; }
  .manage-row > ha-icon { color: var(--primary-color); }
  button.plain { background: none; border: none; padding: 0; text-align: left; cursor: pointer; }
  .icon-placeholder { width: 36px; }
  .icon-input { display: flex; align-items: center; gap: 8px; }
  .icon-input ha-icon { color: var(--primary-color); }
  details.more { border-top: 1px solid var(--divider-color); padding-top: 8px; }
  details.more summary { cursor: pointer; font-size: 14px; color: var(--primary-color); margin-bottom: 8px; }

  .tpl-intro { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
  .tpl-intro h2 { margin: 0; }
  code { font-size: 12px; background: var(--secondary-background-color, #eee); padding: 1px 6px; border-radius: 4px; }
  .tpl-card { display: flex; flex-direction: column; gap: 6px; }
  .tpl-card.active { outline: 2px solid var(--primary-color); }
  .pill { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: var(--secondary-background-color, #eee); color: var(--secondary-text-color); }
  .tpl-config { margin-top: 16px; scroll-margin-top: 16px; }
  .tpl-form { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 16px; }
  .tpl-form label, .form-grid label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--secondary-text-color); }
  .tpl-form label > select + input, .tpl-form label > select + select { margin-top: 4px; }
  .stepper { display: flex; align-items: center; gap: 6px; }
  .stepper input { text-align: center; }
  .quick { display: flex; gap: 4px; flex-wrap: wrap; }
  table.preview { width: 100%; border-collapse: collapse; margin-top: 8px; }
  .preview td { padding: 8px 4px; border-bottom: 1px solid var(--divider-color); vertical-align: top; }
  .preview td.num { text-align: right; white-space: nowrap; font-weight: 500; }
  .preview tr.cat td { font-weight: 500; color: var(--primary-color); padding-top: 16px; }
  .preview tr.cat ha-icon { --mdc-icon-size: 18px; margin-right: 6px; vertical-align: -3px; }
  .error-box { border-left: 4px solid var(--pa-error); margin-bottom: 12px; }

  .overlay {
    position: fixed; inset: 0; z-index: 10; display: flex; align-items: center; justify-content: center;
    background: rgba(0,0,0,.45); padding: 16px;
  }
  .dialog {
    width: min(560px, 100%); max-height: calc(100vh - 32px); overflow-y: auto;
    background: var(--card-background-color, #fff); border-radius: var(--pa-radius); padding: 20px;
    box-shadow: 0 10px 40px rgba(0,0,0,.3);
  }
  .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .form-grid .span2 { grid-column: span 2; }
  .form-error { color: var(--pa-error); font-size: 13px; min-height: 18px; margin-top: 8px; }

  @media (max-width: 900px) {
    .stats { grid-template-columns: repeat(2, 1fr); }
    .columns, .columns.even { grid-template-columns: 1fr; }
    .tpl-form { grid-template-columns: 1fr; }
    .item-row { grid-template-columns: 1fr auto; grid-template-areas: "name exp" "qty actions"; row-gap: 6px; }
    .item-row.selecting { grid-template-columns: auto 1fr auto; grid-template-areas: "check name exp" "check qty actions"; }
    .item-check { grid-area: check; }
    .item-name { grid-area: name; }
    .item-exp { grid-area: exp; text-align: right; }
    .item-qty { grid-area: qty; }
    .item-actions { grid-area: actions; flex-wrap: wrap; }
    .item-actions .icon-btn { width: 32px; height: 32px; }
    .item-row > * { min-width: 0; }
    .item-date { display: none; }
    .toolbar-info { display: none; }
  }
  @media (max-width: 480px) {
    main { padding: 12px; }
    .form-grid { grid-template-columns: 1fr; }
    .form-grid .span2 { grid-column: auto; }
    .stat { padding: 12px; gap: 10px; }
    .stat-value { font-size: 22px; }
  }
`;

if (!customElements.get("prep-assistent-panel")) {
  customElements.define("prep-assistent-panel", PrepAssistentPanel);
}
