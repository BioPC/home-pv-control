/* Presentation only. No inverter, HBC, registry or production service calls. */
class HpvcLimitEntityRow extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: "open"}); }
  setConfig(config) {
    if (!/^sensor\.[a-z0-9_]+$/.test(config.entity || "") || !/^pv(?:[1-9]|10)_limit_entity$/.test(config.attribute || "")) throw Error("Invalid read-only limit binding");
    this.config = config;
    this.shadowRoot.innerHTML = `<style>:host{display:block}.row{display:grid;grid-template-columns:40px minmax(0,1fr);align-items:center;gap:8px;min-height:56px}.body{min-width:0}.label{font-size:14px}.value{display:block;max-width:100%;overflow-x:auto;white-space:nowrap;text-overflow:clip;font-size:13px;color:var(--secondary-text-color);font-family:var(--code-font-family,monospace);padding-bottom:3px}ha-icon{color:var(--state-icon-color)}</style><div class="row"><ha-icon></ha-icon><div class="body"><div class="label"></div><div class="value" tabindex="0" aria-label="Full read-only limit entity"></div></div></div>`;
    this.shadowRoot.querySelector("ha-icon").setAttribute("icon", config.icon || "mdi:lock-outline");
    this.shadowRoot.querySelector(".label").textContent = "Limit entity:";
  }
  set hass(hass) {
    if (!this.config) return;
    const value = hass.states[this.config.entity]?.attributes?.[this.config.attribute];
    const text = typeof value === "string" && value ? value : "Unavailable";
    const element = this.shadowRoot.querySelector(".value");
    element.textContent = text; element.title = text;
  }
}

class HpvcInverterNavigation extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: "open"}); }
  setConfig(config) {
    if (!/^select\.[a-z0-9_]+$/.test(config.entity || "") || !/^sensor\.[a-z0-9_]+$/.test(config.runtime_entity || "") || !["next", "previous"].includes(config.direction)) throw Error("Invalid selection binding");
    this.config = config;
    this.shadowRoot.innerHTML = `<style>:host{display:block}ha-card{height:100%;box-sizing:border-box}button{border:0;background:transparent;color:var(--primary-text-color);width:100%;min-height:56px;cursor:pointer}button:disabled{color:var(--disabled-text-color);cursor:default}</style><ha-card><button type="button"><ha-icon></ha-icon></button></ha-card>`;
    const button = this.shadowRoot.querySelector("button");
    button.setAttribute("aria-label", config.direction === "next" ? "Next inverter" : "Previous inverter");
    this.shadowRoot.querySelector("ha-icon").setAttribute("icon", config.icon);
    button.addEventListener("click", () => this.navigate());
  }
  set hass(value) {
    this._hass = value;
    if (this.config) this.shadowRoot.querySelector("button").disabled = this.count() < 2 || !/^PV(?:[1-9]|10)$/.test(value.states[this.config.entity]?.state || "");
  }
  count() {
    const n = Number(this._hass?.states[this.config.runtime_entity]?.state);
    return Number.isInteger(n) && n >= 0 && n <= 10 ? n : 0;
  }
  navigate() {
    const n = this.count(); if (n < 2 || !/^PV(?:[1-9]|10)$/.test(this._hass.states[this.config.entity]?.state || "")) return;
    const option = this._hass.states[this.config.entity]?.state || "PV1";
    const selected = Number(option.replace(/^PV/, ""));
    const current = Number.isInteger(selected) && selected >= 1 && selected <= n ? selected : 1;
    const next = ((current - 1 + (this.config.direction === "next" ? 1 : n - 1)) % n) + 1;
    // Native selected-inverter configuration only; never a physical control.
    this._hass.callService("select", "select_option", {entity_id: this.config.entity, option: `PV${next}`});
  }
  getCardSize() { return 1; }
  getGridOptions() { return {rows: 1, columns: 4}; }
}
if (!customElements.get("hpvc-limit-entity-row")) customElements.define("hpvc-limit-entity-row", HpvcLimitEntityRow);
if (!customElements.get("hpvc-inverter-navigation")) customElements.define("hpvc-inverter-navigation", HpvcInverterNavigation);
