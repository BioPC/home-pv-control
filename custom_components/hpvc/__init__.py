"""HPVC 2.0 foundation. No inverter or HBC service executor is installed."""

from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from .const import DOMAIN, PLATFORMS


async def async_setup(hass, config):
    return True


async def async_setup_entry(hass, entry):
    from homeassistant.exceptions import ConfigEntryNotReady, ConfigEntryError
    from homeassistant.helpers import issue_registry as ir
    from homeassistant.core import callback
    from homeassistant.helpers.event import async_track_state_change_event
    from .codec import SchemaError
    from .control.models import PlantConfiguration, ImportTransaction
    from .execution.models import ExecutionLedger, OwnershipState
    from .coordinator import HpvcCoordinator, LifecycleOwner
    from .storage import (
        VersionedStore,
        ConfigurationState,
        HistoryState,
        LedgerRepository,
        StorageError,
    )
    from .legacy import detect_legacy, persist_preview
    from .config_flow import capture_legacy

    registry = hass.data.setdefault(DOMAIN, {})
    plant_uid = entry.data["plant_uid"]
    if any(
        runtime.configuration.plant_uid == plant_uid for runtime in registry.values()
    ):
        raise ConfigEntryError("HPVC plant already has an active config entry")
    owner = LifecycleOwner(
        lambda coro, name: entry.async_create_background_task(hass, coro, name)
    )
    prefix = Path(hass.config.path(".storage", f"hpvc_{entry.entry_id}"))
    config_store = VersionedStore(
        prefix.with_name(prefix.name + "_configuration.json"),
        "configuration",
        ConfigurationState,
    )
    history_store = VersionedStore(
        prefix.with_name(prefix.name + "_history.json"), "history", HistoryState
    )
    ledger = LedgerRepository(
        VersionedStore(
            prefix.with_name(prefix.name + "_execution.json"),
            "execution",
            ExecutionLedger,
        ),
        plant_uid,
    )
    forwarded = False
    try:
        state = await config_store.load()
        legacy_state = detect_legacy(capture_legacy(hass))
        await ledger.load()
        if state is not None and state.configuration.plant_uid != plant_uid:
            raise StorageError("Configuration belongs to another plant")
        if state is not None and ledger.store.revision == 0:
            raise StorageError(
                "Execution ledger missing for an existing installation; refusing empty recovery"
            )
        if state is None:
            initial = PlantConfiguration.from_dict(entry.data["initial_configuration"])
            if initial.plant_uid != plant_uid:
                raise SchemaError("Initial plant identity mismatch")
            initial = replace(initial, enabled_intent=False)
            await ledger.update(
                lambda value: replace(
                    value,
                    ownership=replace(
                        value.ownership, state=OwnershipState(legacy_state)
                    ),
                )
            )
            state = ConfigurationState(initial)
            if entry.data.get("legacy_import"):
                transaction = ImportTransaction.from_dict(entry.data["legacy_import"])
                state, _ = await persist_preview(
                    config_store, state, transaction, commit=True
                )
            else:
                await config_store.commit(state, config_store.revision)
        history = await history_store.load()
        if history is None:
            await history_store.commit(HistoryState(plant_uid), history_store.revision)
        elif history.plant_uid != plant_uid:
            raise StorageError("History belongs to another plant")
        # Restore uncertainty durably before starting any listeners or runtime workers.
        await ledger.reconcile_restart()
        coordinator = HpvcCoordinator(
            config_store, history_store, ledger, state, owner, hass.states.get
        )
        entry.runtime_data = coordinator
        registry[entry.entry_id] = coordinator
        current_unsub = [None]
        watched = [None]

        @callback
        def mark_telemetry_dirty(event):
            coordinator.scheduler.mark_telemetry_dirty()

        def resubscribe():
            config = coordinator.configuration
            entities = tuple(
                sorted(
                    {
                        getattr(config, key)
                        for key in (
                            "market_price_sensor",
                            "all_in_price_sensor",
                            "grid_power_sensor",
                            "pv_power_sensor",
                        )
                        if getattr(config, key)
                    }
                )
            )
            if entities == watched[0]:
                return
            if current_unsub[0]:
                current_unsub[0]()
            watched[0] = entities
            current_unsub[0] = (
                async_track_state_change_event(
                    hass, list(entities), mark_telemetry_dirty
                )
                if entities
                else None
            )

        def cleanup_subscription():
            if current_unsub[0]:
                current_unsub[0]()
                current_unsub[0] = None

        owner.add_cleanup(cleanup_subscription)
        owner.add_cleanup(coordinator.add_listener(resubscribe))
        resubscribe()
        forwarded = True
        await hass.config_entries.async_forward_entry_setups(entry, list(PLATFORMS))
        ir.async_create_issue(
            hass,
            DOMAIN,
            entry.entry_id + "_foundation_read_only",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="foundation_read_only",
        )
        coordinator.start()
        return True
    except BaseException as err:
        await owner.close()
        registry.pop(entry.entry_id, None)
        if forwarded:
            await hass.config_entries.async_unload_platforms(entry, list(PLATFORMS))
        entry.runtime_data = None
        if isinstance(err, (StorageError, SchemaError, OSError)):
            ir.async_create_issue(
                hass,
                DOMAIN,
                entry.entry_id + "_recovery_required",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="recovery_required",
            )
            raise ConfigEntryNotReady(
                f"HPVC storage/import requires recovery: {err}"
            ) from err
        raise


async def async_unload_entry(hass, entry):
    from homeassistant.helpers import issue_registry as ir

    runtime = entry.runtime_data
    # Close every owned listener/task even if a platform subsequently refuses unload.
    if runtime is not None:
        await runtime.close()
    unloaded = await hass.config_entries.async_unload_platforms(entry, list(PLATFORMS))
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        entry.runtime_data = None
        ir.async_delete_issue(hass, DOMAIN, entry.entry_id + "_foundation_read_only")
    return unloaded
