"""Synthetic two-controller production-shaped export; never site evidence."""

from custom_components.hpvc.site_audit.schema import EXPECTED, SCHEMA
from custom_components.hpvc.control.models import ControlSettings
from custom_components.hpvc.migration.detector import APPROVED_FINGERPRINT


def sample(now=1800000000.0):
    states = []

    def put(name, value, attrs=None):
        states.append(
            dict(
                entity_id=name,
                state=str(value),
                last_reported=now,
                last_updated=now,
                attributes=attrs or {},
            )
        )

    put("input_number.hpvc_inverter_count", 0)
    put("input_boolean.hpvc_enabled", "on")
    put("input_boolean.hpvc_control_hbc_strategy", "on")
    put("input_boolean.hpvc_negative_price_hbc_charge", "on")
    for key in ControlSettings.__dataclass_fields__:
        put("input_number.hpvc_" + key, getattr(ControlSettings(), key))
    for key, value in [
        ("pv_power", 2500),
        ("grid_power", -500),
        ("market_price", 0.1),
        ("all_in_price", 0.2),
    ]:
        put("input_text.hpvc_" + key + "_sensor", "sensor.site_" + key)
        put("sensor.site_" + key, value)
    for name, value in [
        ("input_select.house_battery_strategy", "Self Consumption"),
        ("input_select.house_battery_strategy_charge_goal", "adaptive"),
        ("input_text.house_battery_strategy_active_sub_strategy", "Self Consumption"),
        ("input_number.house_battery_count", 1),
        ("sensor.marstek_m1_ac_power", 0),
        ("sensor.marstek_m1_battery_state_of_charge", 60),
    ]:
        put(name, value)
    registry = []
    devices = []
    api = []
    for i, (entity, power, serial) in enumerate(
        zip(EXPECTED, (2000, 1000), ("112233445566", "223344556677")), 1
    ):
        put(
            entity,
            power,
            {"min": 0, "max": 9999, "step": 1, "unit_of_measurement": "W"},
        )
        registry.append(
            dict(
                entity_id=entity,
                registry_id="registry-" + str(i),
                device_id="device-" + str(i),
                platform="mqtt",
                config_entry_id="mqtt-entry",
                unique_id=serial + "_limit_nonpersistent_absolute",
                original_name="Limit nonpersistent absolute",
                translation_key="",
                original_entity_id=entity,
                disabled_by=None,
            )
        )
        url = "http://opendtu-" + str(i) + ".example"
        devices.append(
            dict(
                device_id="device-" + str(i),
                manufacturer="Hoymiles",
                model="HMS",
                model_id="",
                name="OpenDTU " + serial,
                configuration_url=url,
                identifiers=[["mqtt", serial]],
                config_entries=["mqtt-entry"],
            )
        )
        api.append(
            dict(
                device_id="device-" + str(i),
                endpoint=url + "/api/limit/status",
                poll_started_at_utc=now - 0.5,
                received_at_utc=now,
                payload={
                    serial: dict(
                        max_power=power, limit_relative=100, limit_set_status="Ok"
                    )
                },
            )
        )
    return dict(
        schema=SCHEMA,
        source="production_export",
        collected_at_utc=now,
        ha={"version": "2026.10.4"},
        states=states,
        entity_registry=registry,
        device_registry=devices,
        config_entries=[
            dict(
                entry_id="mqtt-entry",
                domain="mqtt",
                title="MQTT",
                state="loaded",
                source="user",
                version=1,
                disabled_by=None,
            )
        ],
        native_configuration=None,
        native_runtime={},
        legacy=dict(
            version="1.6.0",
            fingerprint=APPROVED_FINGERPRINT,
            flow_inventory_complete=True,
            foreign_hpvc_candidates=[],
            managed_tabs=["exact-owned-tab"],
            runtime=dict(
                reachable=True,
                observed_at_utc=now,
                runtime_owner="legacy-runtime",
                pending_update=False,
                recovery_pending=False,
            ),
            bridge=dict(
                schema="hpvc-migration/1.6.0/1",
                complete=True,
                runtime_owner="legacy-runtime",
                flow_fingerprint=APPROVED_FINGERPRINT,
                observed_at_utc=now,
                active=[],
                queued=[],
                potentially_issued=[],
                pending_verification=[],
                restore_obligations=[],
                recovery_required=False,
                hbc_override_owned=False,
                hbc_originals=["Self Consumption", "adaptive"],
            ),
        ),
        opendtu=api,
        references=[],
        coverage=dict(
            states=True,
            entity_registry=True,
            device_registry=True,
            config_entries=True,
            reference_files=[],
        ),
        collection_errors=[],
        redactions=[],
    )
