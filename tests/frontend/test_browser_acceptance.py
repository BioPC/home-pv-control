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
from urllib.parse import parse_qs, urlsplit

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
    ui_key,
)
from custom_components.hpvc.entity import HpvcEntity
from tests.dashboard import dashboard_fixture as fixtures

pytestmark = pytest.mark.asyncio
OUT = ROOT / "frontend-evidence"


def phase(name, output):
    (output / "phase.json").write_text(
        json.dumps({"phase": name, "at": time.time()}), encoding="utf-8"
    )
    print("HPVC_BROWSER_PHASE", name, flush=True)


def synthetic(name, priority="Off"):
    """Display fixture only; these are never production/physical evidence."""
    now = time.time()
    fixtures.NOW = now
    f = fixtures.fixture(name, native_data=True)
    # DOM fixtures do not run the native binary-sensor projections. Publish the
    # matching slot visibility explicitly for this isolated browser fixture.
    for slot in range(2, 11):
        f["states"][f"binary_sensor.hpvc_show_inverter_slot_{slot}"] = {
            "state": "on" if len(f["rows"]) >= slot else "off",
            "attributes": {},
        }
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
            "attributes": dict(row.get("attributes", {}))
            if row
            else dict(attrs.get("ui_source_attributes", {}).get(binding["source"], {})),
        }
    return f


def history_payload(f, entities=None):
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
            ui_binary_sensor_hpvc_pv_limited="unknown"
            if 65 <= i <= 75
            else "on"
            if (i // 24) % 3 == 2
            else "off",
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
    result = []
    by_source = {b["source"]: b for b in CATALOG["bindings"]}
    for entity in entities or ["sensor.hpvc_status"]:
        if entity == "sensor.hpvc_status":
            result.append(states)
            continue
        binding = by_source.get(entity, {})
        attribute = binding.get("attribute") or ui_key(entity)
        row = f["states"].get(entity, {"state": "unavailable", "attributes": {}})
        result.append(
            [
                {
                    **s,
                    "entity_id": entity,
                    "state": "unavailable"
                    if s["attributes"].get(attribute) is None
                    else str(s["attributes"][attribute]),
                    "attributes": row["attributes"],
                }
                for s in states
            ]
        )
    return result


@pytest.mark.parametrize(
    "case_group",
    ["interactions", "matrix-light", "matrix-dark", "fixtures-a", "fixtures-b"],
)
async def test_actual_ha_frontend(
    hass, hass_client, hass_access_token, socket_enabled, case_group
):
    out = OUT / case_group

    def mark(name):
        phase(name, out)

    logging.getLogger("homeassistant.core").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    out.mkdir(parents=True, exist_ok=True)
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
    failed_requests = []
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
        mark("real-ha-started-recorder-and-hpvc-loaded")
        origin = str(client.make_url("/")).rstrip("/")
        print("HPVC_BROWSER_SERVER", origin, flush=True)
        current = {"fixture": synthetic("hoymiles"), "enabled": True}

        def apply_entity(entity, row):
            old = hass.states.get(entity)
            attrs = dict(old.attributes) if old else {}
            attrs.update(row["attributes"])
            attrs["hpvc_test_fixture"] = True
            value = row["state"]
            if entity == "select.hpvc_selected_inverter":
                value = entry.runtime_data.configuration.selected_inverter
            if old is None or old.state != str(value) or dict(old.attributes) != attrs:
                hass.states.async_set(entity, value, attrs)

        def apply_fixture():
            for entity, row in current["fixture"]["states"].items():
                apply_entity(entity, row)

        # Display fixtures own presentation values during capture. Keep real
        # selection/configuration services and restore every native publication
        # callback before exercising the real unload/reload lifecycle.
        runtime_under_test = entry.runtime_data
        publication_swaps = []
        for callback in tuple(runtime_under_test.listeners):
            native_entity = getattr(callback, "__self__", None)
            if not isinstance(native_entity, HpvcEntity):
                continue

            def publish_display(callback=callback, native_entity=native_entity):
                row = current["fixture"]["states"].get(native_entity.entity_id)
                if current["enabled"] and row is not None:
                    apply_entity(native_entity.entity_id, row)
                else:
                    callback()

            runtime_under_test.listeners.remove(callback)
            runtime_under_test.listeners.add(publish_display)
            publication_swaps.append((callback, publish_display))

        def restore_publication():
            for callback, replacement in publication_swaps:
                runtime_under_test.listeners.discard(replacement)
                if not runtime_under_test.owner.closed:
                    runtime_under_test.listeners.add(callback)
            publication_swaps.clear()

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
                    page.on(
                        "pageerror",
                        lambda error: errors.append(error.stack or str(error)),
                    )
                    responses = []
                    page.on(
                        "response",
                        lambda response: (
                            responses.append(
                                {"url": response.url, "status": response.status}
                            )
                            if "/local/" in response.url
                            else None
                        ),
                    )
                    page.on(
                        "console",
                        lambda message: (
                            (errors if message.type == "error" else warnings).append(
                                message.text + " " + json.dumps(message.location)
                            )
                            if message.type in ("error", "warning")
                            else None
                        ),
                    )
                    page.on(
                        "requestfailed",
                        lambda request: failed_requests.append(
                            {
                                "url": request.url,
                                "failure": request.failure,
                                "type": request.resource_type,
                            }
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
                        query = parse_qs(urlsplit(route.request.url).query)
                        entities = query.get(
                            "filter_entity_id", ["sensor.hpvc_status"]
                        )[0].split(",")
                        await route.fulfill(
                            json=history_payload(current["fixture"], entities)
                        )

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
                        # Exercise HA's normal SPA navigation without tearing down
                        # an active state subscription on every display fixture.
                        if await page.evaluate(
                            "!!document.querySelector('home-assistant')?.hass"
                        ):
                            await page.evaluate(
                                "(url)=>{history.pushState(null,'',url);window.dispatchEvent(new Event('location-changed'));}",
                                url,
                            )
                        else:
                            await page.goto(url, wait_until="domcontentloaded")
                        await page.wait_for_selector("hui-sections-view", timeout=60000)
                        await page.wait_for_timeout(1500)
                        name = f"{label}-{scenario}-{theme}-{width}-view{view}"
                        await page.screenshot(
                            path=str(out / (name + ".png")), full_page=True
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
                        mark(name)
                        print("HPVC_BROWSER_CAPTURE", name, flush=True)
                        assert not info["errors"], info["errors"]
                        assert info["dark"] == (theme == "dark"), info
                        assert not info["pageOverflow"], name
                        assert not any(
                            "[object Object]" in text for text in info["text"]
                        ), name

                    if case_group == "interactions":
                        # Bootstrap first; remaining captures exercise both real views.
                        await capture("native", "hoymiles", "light", 1440, 1)
                        row = page.locator("hpvc-limit-entity-row:visible").first
                        await row.wait_for(timeout=30000)
                        assert (
                            await row.locator(".label").inner_text() == "Limit entity:"
                        )
                        assert (
                            await row.locator(".value").inner_text()
                            == fixtures.LONG_IDS[0]
                        )
                        assert await row.locator("input,textarea").count() == 0
                        assert (
                            await row.locator("ha-icon").get_attribute("icon")
                            == "mdi:lock-outline"
                        )
                        await row.screenshot(path=str(out / "limit-row-desktop.png"))
                        before = len(service_calls)
                        await page.locator(
                            'hpvc-inverter-navigation:visible button[aria-label="Next inverter"]'
                        ).click()
                        await page.wait_for_timeout(1000)
                        assert (
                            entry.runtime_data.configuration.selected_inverter == "PV2"
                        )
                        assert len(service_calls) == before + 1
                        await page.screenshot(
                            path=str(out / "selected-pv2.png"), full_page=True
                        )
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
                    if case_group.startswith("matrix-"):
                        for theme in (case_group.removeprefix("matrix-"),):
                            for width in (1440, 900, 390):
                                for view in (0, 1):
                                    for label in ("reference", "native"):
                                        await capture(
                                            label, "mixed", theme, width, view
                                        )
                    if case_group.startswith("fixtures-"):
                        for scenario in (
                            fixtures.SCENARIOS[:6]
                            if case_group == "fixtures-a"
                            else fixtures.SCENARIOS[6:]
                        ):
                            for view in (0, 1):
                                await capture("native", scenario, "light", 1440, view)
                    if case_group == "interactions":
                        await capture("native", "mixed", "light", 1440, 0)
                        sub_strategy = page.locator("hui-attribute-row").filter(
                            has_text="HBC sub-strategy"
                        )
                        await sub_strategy.wait_for()
                        # HA entity rows render their value inside open shadow DOM.
                        await sub_strategy.get_by_text("Balanced", exact=True).wait_for(
                            state="visible"
                        )
                        details = page.locator("details").filter(
                            has=page.locator('summary:text-is("Executive Summary")')
                        )
                        assert await details.get_attribute("open") is not None
                        assert await details.locator("p").count() > 0
                        assert await details.locator("p").first.is_visible()
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
                            assert await panel.locator("p").count() > 0, heading
                            assert not await panel.locator("p").first.is_visible(), (
                                heading
                            )
                            await panel.locator("summary").click()
                            assert await panel.locator("p").first.is_visible(), heading
                            await panel.locator("summary").click()
                            assert not await panel.locator("p").first.is_visible(), (
                                heading
                            )
                        await (
                            page.locator("hui-markdown-card")
                            .filter(has=details)
                            .screenshot(
                                path=str(out / "reports-initial-disclosures.png")
                            )
                        )
                        await page.locator(
                            'summary:text-is("HBC & Battery Status")'
                        ).click()
                        for priority in ("Off", "Waiting", "Active", "unknown"):
                            current["fixture"] = synthetic("mixed", priority)
                            apply_fixture()
                            await page.wait_for_timeout(500)
                            await page.screenshot(
                                path=str(out / f"priority-{priority}.png"),
                                full_page=True,
                            )
                        await capture("native", "hoymiles", "dark", 390, 1)
                        row = page.locator("hpvc-limit-entity-row:visible").first
                        value = row.locator(".value")
                        await value.focus()
                        assert await value.get_attribute("tabindex") == "0"
                        assert (
                            await value.get_attribute("title") == fixtures.LONG_IDS[0]
                        )
                        await value.hover()
                        await page.mouse.wheel(600, 0)
                        await page.wait_for_timeout(300)
                        scroll = await value.evaluate(
                            "(e)=>({left:e.scrollLeft,width:e.clientWidth,full:e.scrollWidth})"
                        )
                        assert (
                            scroll["full"] > scroll["width"] and scroll["left"] > 0
                        ), scroll
                        await row.screenshot(
                            path=str(out / "limit-row-mobile-scrolled.png")
                        )
                    expected = {
                        "interactions": 3,
                        "matrix-light": 12,
                        "matrix-dark": 12,
                        "fixtures-a": 12,
                        "fixtures-b": 10,
                    }
                    assert len(cases) == expected[case_group], (case_group, len(cases))
                    publisher.cancel()
                    await asyncio.gather(publisher, return_exceptions=True)
                    print("HPVC_BROWSER_DRAIN_BEFORE_RELOAD", flush=True)
                    mark("drain-before-browser-reload")
                    await asyncio.wait_for(hass.async_block_till_done(), 30)
                    await page.evaluate(
                        "document.querySelector('home-assistant').hass.connection.close()"
                    )
                    await page.wait_for_timeout(1000)
                    await page.reload(wait_until="domcontentloaded")
                    await page.wait_for_selector("hpvc-limit-entity-row", timeout=30000)
                    assert await page.evaluate(
                        "customElements.get('hpvc-limit-entity-row')!==undefined && customElements.get('hpvc-inverter-navigation')!==undefined"
                    )
                    assert await page.evaluate(
                        "customElements.get('apexcharts-card')!==undefined"
                    )
                    assert responses and all(r["status"] == 200 for r in responses), (
                        responses
                    )
                    print("HPVC_BROWSER_DRAIN_BEFORE_DISCONNECT", flush=True)
                    mark("drain-before-final-disconnect")
                    await asyncio.wait_for(hass.async_block_till_done(), 30)
                    await page.evaluate(
                        "document.querySelector('home-assistant').hass.connection.close()"
                    )
                    await page.wait_for_timeout(1000)
                    current["enabled"] = False
                    restore_publication()
                    runtime = entry.runtime_data
                    mark("unload-native-entry")
                    await asyncio.wait_for(
                        hass.config_entries.async_unload(entry.entry_id), 30
                    )
                    assert not runtime.owner.tasks
                    await page.wait_for_timeout(500)
                    mark("reload-native-entry")
                    assert await asyncio.wait_for(
                        hass.config_entries.async_setup(entry.entry_id), 30
                    )
                    print("HPVC_BROWSER_DRAIN_AFTER_RELOAD", flush=True)
                    await asyncio.wait_for(hass.async_block_till_done(), 30)
                    assert not entry.runtime_data.physical_writes_authorized
                    mark("close-browser-context")
                    await context.close()
                    mark("close-browser")
                    await browser.close()
                    mark("browser-closed-native-reload-verified")
        except BaseException:
            (out / "failure-traceback.txt").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            if "page" in locals() and not page.is_closed():
                try:
                    await page.screenshot(path=str(out / "failure.png"), full_page=True)
                    (out / "failure.html").write_text(
                        await page.content(), encoding="utf-8"
                    )
                except PlaywrightError as capture_error:
                    (out / "capture-error.txt").write_text(
                        str(capture_error), encoding="utf-8"
                    )
            raise
        finally:
            current["enabled"] = False
            publisher.cancel()
            await asyncio.gather(publisher, return_exceptions=True)
            restore_publication()
            (out / "browser-results.json").write_text(
                json.dumps(
                    {
                        "case_group": case_group,
                        "cases": cases,
                        "errors": errors,
                        "warnings": warnings,
                        "resources": requests,
                        "resource_responses": responses
                        if "responses" in locals()
                        else [],
                        "failed_requests": failed_requests,
                        "service_calls": service_calls,
                        "production_transport_authorized": False,
                        "fixture_context": "Synthetic UI states and historical HTTP fixtures on actual isolated HA/frontend; not physical evidence",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            if entry.runtime_data:
                mark("final-native-unload")
                await asyncio.wait_for(
                    hass.config_entries.async_unload(entry.entry_id), 30
                )
            mark("test-body-complete")
            mark("close-isolated-http-client")
            await asyncio.wait_for(client.close(), 30)
            # Stop the real Recorder and HA while the isolated HTTP test server
            # still exists, rather than leaving worker shutdown to fixture order.
            mark("stop-isolated-home-assistant")
            await asyncio.wait_for(hass.async_stop(), 30)
            mark("isolated-home-assistant-stopped")
    assert not errors, errors
