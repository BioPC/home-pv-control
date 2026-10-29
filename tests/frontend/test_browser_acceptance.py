"""Actual HA frontend/Chromium acceptance with explicit synthetic UI fixtures."""

import asyncio
import json
import logging
import math
import shutil
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import ServiceRegistry
from homeassistant.setup import async_setup_component
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/ha"))
from test_foundation_acceptance import start

from custom_components.hpvc.dashboard.builder import REFERENCE, parity_dashboard
from custom_components.hpvc.dashboard.data import DashboardState, HistoryPoint, Insight
from custom_components.hpvc.dashboard.presentation import (
    CATALOG,
    CONDITION_KEYS,
    dashboard_attributes,
)
from tests.dashboard import dashboard_fixture as fixtures

pytestmark = pytest.mark.asyncio
OUT = ROOT / "frontend-evidence"


def synthetic(name, priority="Off"):
    """Display fixture only; these are never production/physical evidence."""
    now = time.time()
    fixtures.NOW = now
    f = fixtures.fixture(name, native_data=True)
    runtime = f["runtime"]
    strategy = runtime.state_reader("input_select.house_battery_strategy")
    if strategy is not None and priority in ("Waiting", "Active"):
        strategy.state = "Charge"
    observer = runtime.dashboard_observer
    date = datetime.fromtimestamp(now, UTC).date().isoformat()
    points = []
    for i in range(1440):
        at = now - 43200 + i * 30
        mode = ("Normal", "Charge", "Limit")[(i // 240) % 3]
        if 600 <= i <= 660 or name in ("stale", "unavailable") and i > 1400:
            mode = "unknown"
        points.append(
            HistoryPoint(
                at,
                mode,
                priority if mode != "unknown" else "unknown",
                evidence_ids=("synthetic-browser-fixture",)
                if mode != "unknown"
                else (),
                limited=mode == "Limit" if mode != "unknown" else None,
                reason="Synthetic browser fixture, not production evidence",
            )
        )
    observer.state = DashboardState(
        runtime.configuration.plant_uid,
        date,
        tuple(points),
        (
            Insight(
                now - 30,
                "Browser fixture",
                "Read-only synthetic observation; no command was executed.",
            ),
        ),
        measured=10,
        within=8,
        unavailable=2,
        absolute_error=100,
        squared_error=2000,
    )
    observer.latest = points[-1]
    prices = runtime.state_reader("sensor.hbc_energy_prices_data")
    if prices is not None:
        day = int(now // 86400) * 86400
        prices.attributes["marks"] = [
            {
                "start": datetime.fromtimestamp(day + i * 900, UTC).isoformat(),
                "price": round(10 + 8 * math.sin(i / 12), 2),
                "mark": "low" if i % 12 < 4 else "high" if i % 12 > 8 else "normal",
                "is_now": day + i * 900 <= now < day + (i + 1) * 900,
            }
            for i in range(192)
        ]
    attrs = dashboard_attributes(runtime, f["rows"], now=now)
    f["states"]["sensor.hpvc_status"]["attributes"] = attrs
    f["states"]["binary_sensor.hpvc_physical_writes_authorized"] = {
        "state": "off",
        "attributes": {"hpvc_test_fixture": True},
    }
    for key in CONDITION_KEYS:
        value = attrs.get(key)
        f["states"]["sensor.hpvc_dashboard_" + key] = {
            "state": "unknown" if value is None else str(value),
            "attributes": {},
        }
    # The canonical reference is served on the same HA, with fixture helpers only.
    for binding in CATALOG["bindings"]:
        row = f["states"].get(binding["target"]) if binding["target"] else None
        value = row["state"] if row else attrs.get(binding["attribute"])
        f["states"][binding["source"]] = {
            "state": "unavailable" if value is None else str(value),
            "attributes": dict(row.get("attributes", {})) if row else {},
        }
    return f


def history_payload(f):
    now = time.time()
    states = []
    for i in range(145):
        attrs = dict(f["states"]["sensor.hpvc_status"]["attributes"])
        attrs.pop("ui_dashboard_data", None)
        attrs.pop("ui_report_sections", None)
        attrs.update(
            ui_sensor_hpvc_diag_grid_power=None
            if 65 <= i <= 75
            else round(350 * math.sin(i / 9)),
            ui_sensor_hpvc_diag_pv_power=None
            if 65 <= i <= 75
            else round(1200 + 400 * math.sin(i / 14)),
            ui_sensor_hpvc_total_hbc_charging_power=None if 65 <= i <= 75 else 300,
        )
        at = datetime.fromtimestamp(now - 43200 + i * 300, UTC).isoformat()
        states.append(
            {
                "entity_id": "sensor.hpvc_status",
                "state": "Monitoring only",
                "attributes": attrs,
                "last_changed": at,
                "last_updated": at,
            }
        )
    return [states]


async def test_actual_ha_frontend(hass, hass_client, hass_access_token, socket_enabled):
    logging.getLogger("homeassistant.core").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    OUT.mkdir(exist_ok=True)
    www = Path(hass.config.path("www"))
    www.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "frontend/hpvc-dashboard.js", www / "hpvc-dashboard.js")
    shutil.copyfile(ROOT / "work/apexcharts-card.js", www / "apexcharts-card.js")
    for label, config in [("native", parity_dashboard()), ("reference", REFERENCE)]:
        Path(hass.config.path("hpvc-" + label + ".yaml")).write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8"
        )
    config = {
        "http": {},
        "frontend": {},
        "history": {},
        "recorder": {"db_url": "sqlite:///" + hass.config.path("frontend-fixture.db")},
        "lovelace": {
            "mode": "yaml",
            "resources": [
                {"url": "/local/hpvc-dashboard.js", "type": "module"},
                {"url": "/local/apexcharts-card.js", "type": "module"},
            ],
            "dashboards": {
                "hpvc-" + label: {
                    "mode": "yaml",
                    "title": "HPVC " + label,
                    "filename": "hpvc-" + label + ".yaml",
                    "show_in_sidebar": True,
                }
                for label in ("native", "reference")
            },
        },
    }
    errors = []
    warnings = []
    requests = []
    service_calls = []
    cases = []
    with patch(
        "homeassistant.components.onboarding.async_is_onboarded", return_value=True
    ):
        # The component-test HA fixture skips this real bootstrap helper.
        from homeassistant.helpers.recorder import (
            DATA_RECORDER,
            async_initialize_recorder,
        )

        if DATA_RECORDER not in hass.data:
            async_initialize_recorder(hass)
        assert await async_setup_component(hass, "frontend", config)
        assert await async_setup_component(hass, "history", config)
        for domain in ("persistent_notification", "labs"):
            assert await async_setup_component(hass, domain, config)
        from homeassistant.const import __version__ as ha_version

        if tuple(map(int, ha_version.split(".")[:2])) >= (2026, 2):
            assert await async_setup_component(hass, "brands", config)
        entry = await start(hass)
        if not hass.is_running:
            await hass.async_start()
        client = await hass_client()
        origin = str(client.make_url("/")).rstrip("/")
        print("HPVC_BROWSER_SERVER", origin, flush=True)
        current = {"fixture": synthetic("hoymiles"), "enabled": True}

        def apply_fixture():
            f = current["fixture"]
            for entity, row in f["states"].items():
                attrs = (
                    dict(hass.states.get(entity).attributes)
                    if hass.states.get(entity)
                    else {}
                )
                attrs.update(row["attributes"])
                attrs["hpvc_test_fixture"] = True
                value = row["state"]
                if entity == "select.hpvc_selected_inverter":
                    value = entry.runtime_data.configuration.selected_inverter
                hass.states.async_set(entity, value, attrs)

        async def publish_fixture():
            while current["enabled"]:
                apply_fixture()
                await asyncio.sleep(0.25)

        publisher = asyncio.create_task(
            publish_fixture(), name="hpvc-isolated-visual-fixtures"
        )
        original = ServiceRegistry.async_call

        async def guarded(self, domain, service, service_data=None, *args, **kwargs):
            data = service_data or {}
            # Real HA frontend diagnostics write only to this isolated HA log.
            if (domain, service) == ("system_log", "write"):
                return await original(
                    self, domain, service, service_data, *args, **kwargs
                )
            service_calls.append({"domain": domain, "service": service, "data": data})
            assert (domain, service, data.get("entity_id")) == (
                "select",
                "select_option",
                "select.hpvc_selected_inverter",
            ), service_calls[-1]
            return await original(self, domain, service, service_data, *args, **kwargs)

        try:
            with patch.object(ServiceRegistry, "async_call", guarded):
                async with async_playwright() as p:
                    browser = await p.chromium.launch(
                        headless=True, args=["--disable-dev-shm-usage"]
                    )
                    context = await browser.new_context(
                        viewport={"width": 1440, "height": 1000},
                        color_scheme="light",
                        device_scale_factor=1,
                    )
                    await context.add_init_script(
                        "localStorage.setItem('hassTokens',JSON.stringify("
                        + json.dumps(
                            {
                                "hassUrl": origin,
                                "clientId": origin + "/",
                                "access_token": hass_access_token,
                                "refresh_token": "isolated-unused",
                                "expires_in": 3600,
                                "expires": int((time.time() + 3600) * 1000),
                                "token_type": "Bearer",
                            }
                        )
                        + "));localStorage.setItem('selectedLanguage',JSON.stringify('en'));localStorage.setItem('dockedSidebar',JSON.stringify('always_hidden'));"
                    )
                    page = await context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda message: (
                            (errors if message.type == "error" else warnings).append(
                                message.text
                            )
                            if message.type in ("error", "warning")
                            else None
                        ),
                    )
                    page.on(
                        "request",
                        lambda request: (
                            requests.append(request.url)
                            if "/local/" in request.url
                            else None
                        ),
                    )

                    async def historical(route):
                        await route.fulfill(json=history_payload(current["fixture"]))

                    await page.route("**/api/history/period/**", historical)

                    async def capture(label, scenario, theme, width, view):
                        current["fixture"] = synthetic(scenario)
                        await page.set_viewport_size(
                            {"width": width, "height": 1000 if width > 600 else 844}
                        )
                        await page.emulate_media(color_scheme=theme)
                        url = (
                            origin
                            + "/hpvc-"
                            + label
                            + "/"
                            + REFERENCE["views"][view]["path"]
                        )
                        await page.goto(url, wait_until="domcontentloaded")
                        await page.wait_for_selector("hui-sections-view", timeout=60000)
                        await page.wait_for_timeout(1500)
                        name = f"{label}-{scenario}-{theme}-{width}-view{view}"
                        await page.screenshot(
                            path=str(OUT / (name + ".png")), full_page=True
                        )
                        info = await page.evaluate(
                            """() => {const all=[];function walk(root){for(const e of root.querySelectorAll('*')){all.push(e);if(e.shadowRoot)walk(e.shadowRoot)}}walk(document);return {title:document.title,tags:[...new Set(all.map(e=>e.localName))],errors:all.filter(e=>e.localName==='hui-error-card').map(e=>e.innerText),text:all.filter(e=>e.localName==='ha-markdown').map(e=>e.shadowRoot?.textContent||e.textContent),dark:document.querySelector('home-assistant')?.hass?.themes?.darkMode,pageOverflow:document.body.scrollWidth>innerWidth+2,resources:[...document.querySelectorAll('script[src]')].map(e=>e.src).filter(s=>s.includes('hpvc-dashboard')),charts:all.filter(e=>e.localName==='apexcharts-card').length}}"""
                        )
                        info.update(
                            name=name,
                            scenario=scenario,
                            theme=theme,
                            width=width,
                            view=view,
                            label=label,
                        )
                        cases.append(info)
                        assert not info["errors"], info["errors"]
                        assert info["dark"] == (theme == "dark"), info
                        assert not info["pageOverflow"], name
                        assert not any(
                            "[object Object]" in text for text in info["text"]
                        ), name

                    # Bootstrap first; remaining captures exercise both real views.
                    await capture("native", "hoymiles", "light", 1440, 1)
                    row = page.locator("hpvc-limit-entity-row:visible").first
                    await row.wait_for(timeout=30000)
                    assert await row.locator(".label").inner_text() == "Limit entity:"
                    assert (
                        await row.locator(".value").inner_text() == fixtures.LONG_IDS[0]
                    )
                    assert await row.locator("input,textarea").count() == 0
                    assert (
                        await row.locator("ha-icon").get_attribute("icon")
                        == "mdi:lock-outline"
                    )
                    await row.screenshot(path=str(OUT / "limit-row-desktop.png"))
                    before = len(service_calls)
                    await page.locator(
                        'hpvc-inverter-navigation:visible button[aria-label="Next inverter"]'
                    ).click()
                    await page.wait_for_timeout(1000)
                    assert entry.runtime_data.configuration.selected_inverter == "PV2"
                    assert len(service_calls) == before + 1
                    assert (
                        await page.locator(
                            "hpvc-limit-entity-row:visible .value"
                        ).inner_text()
                        == fixtures.LONG_IDS[1]
                    )
                    await page.locator(
                        'hpvc-inverter-navigation:visible button[aria-label="Previous inverter"]'
                    ).click()
                    await page.wait_for_timeout(500)
                    assert len(service_calls) == before + 2
                    for theme in ("light", "dark"):
                        for width in (1440, 900, 390):
                            for view in (0, 1):
                                for label in ("reference", "native"):
                                    await capture(label, "mixed", theme, width, view)
                    for scenario in fixtures.SCENARIOS:
                        for view in (0, 1):
                            await capture("native", scenario, "light", 1440, view)
                    await capture("native", "mixed", "light", 1440, 0)
                    details = page.locator("details").filter(
                        has=page.locator('summary:text-is("Executive Summary")')
                    )
                    assert await details.get_attribute("open") is not None
                    for heading in (
                        "Live Status",
                        "Decision Evaluation",
                        "Today’s Insights",
                        "Power Control",
                        "Today’s Accuracy",
                        "HBC & Battery Status",
                        "Inverters",
                        "Sensor Health",
                        "Control Settings",
                    ):
                        panel = page.locator("details").filter(
                            has=page.locator("summary").filter(has_text=heading)
                        )
                        assert await panel.get_attribute("open") is None, heading
                    await page.locator(
                        'summary:text-is("HBC & Battery Status")'
                    ).click()
                    for priority in ("Off", "Waiting", "Active", "unknown"):
                        current["fixture"] = synthetic("mixed", priority)
                        apply_fixture()
                        await page.wait_for_timeout(500)
                        await page.screenshot(
                            path=str(OUT / f"priority-{priority}.png"), full_page=True
                        )
                    await capture("native", "hoymiles", "dark", 390, 1)
                    row = page.locator("hpvc-limit-entity-row:visible").first
                    value = row.locator(".value")
                    await value.focus()
                    assert await value.get_attribute("tabindex") == "0"
                    assert await value.get_attribute("title") == fixtures.LONG_IDS[0]
                    await value.hover()
                    await page.mouse.wheel(600, 0)
                    await page.wait_for_timeout(300)
                    scroll = await value.evaluate(
                        "(e)=>({left:e.scrollLeft,width:e.clientWidth,full:e.scrollWidth})"
                    )
                    assert scroll["full"] > scroll["width"] and scroll["left"] > 0, (
                        scroll
                    )
                    await row.screenshot(
                        path=str(OUT / "limit-row-mobile-scrolled.png")
                    )
                    await page.reload(wait_until="domcontentloaded")
                    await page.wait_for_selector("hpvc-limit-entity-row", timeout=30000)
                    assert await page.evaluate(
                        "customElements.get('hpvc-limit-entity-row')!==undefined && customElements.get('hpvc-inverter-navigation')!==undefined"
                    )
                    current["enabled"] = False
                    publisher.cancel()
                    await asyncio.gather(publisher, return_exceptions=True)
                    runtime = entry.runtime_data
                    await hass.config_entries.async_unload(entry.entry_id)
                    assert not runtime.owner.tasks
                    await page.wait_for_timeout(500)
                    assert await hass.config_entries.async_setup(entry.entry_id)
                    await hass.async_block_till_done()
                    assert not entry.runtime_data.physical_writes_authorized
                    await browser.close()
        except BaseException:
            (OUT / "failure-traceback.txt").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            if "page" in locals() and not page.is_closed():
                try:
                    await page.screenshot(path=str(OUT / "failure.png"), full_page=True)
                    (OUT / "failure.html").write_text(
                        await page.content(), encoding="utf-8"
                    )
                except PlaywrightError as capture_error:
                    (OUT / "capture-error.txt").write_text(
                        str(capture_error), encoding="utf-8"
                    )
            raise
        finally:
            current["enabled"] = False
            publisher.cancel()
            await asyncio.gather(publisher, return_exceptions=True)
            (OUT / "browser-results.json").write_text(
                json.dumps(
                    {
                        "cases": cases,
                        "errors": errors,
                        "warnings": warnings,
                        "resources": requests,
                        "service_calls": service_calls,
                        "production_transport_authorized": False,
                        "fixture_context": "Synthetic UI states and historical HTTP fixtures on actual isolated HA/frontend; not physical evidence",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            if entry.runtime_data:
                await hass.config_entries.async_unload(entry.entry_id)
    assert not errors, errors
