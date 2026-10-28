# Dev.8 audit corrections

This patch stays on the dev.8 read-only architecture. It does not implement the
separate dev.9 dashboard request. Production transport remains permanently false.
The manifest remains `2.0.0-dev.8`; `DEVELOPMENT.json` identifies this patch as
`audit-fixes.1`. Use the package SHA-256 and tested commit to distinguish builds.

## Optional Action JSON

Only missing, empty or whitespace-only optional JSON helper text uses defaults:
`fixed_data_json` and `target_json` become `{}`; `pre_actions_json` and
`post_actions_json` become `[]`. This applies consistently to all ten slots and
both methods. Supplied nonblank strings retain their exact contents. Strict JSON
parsing, object/array shape checks, duplicate-key rejection, finite-value checks,
and sequence action/payload validation still apply. `unknown` and `unavailable`
are errors, not empty configuration. Captured raw legacy values and transaction
fingerprints retain the exported text; only candidate configuration is normalized.
No configured action is invoked by import preview.

## Discovery exclusion

Auto-discovery rejects identities whose object ID starts with `hpvc_fake_`, using
the current entity ID, original registry entity ID and unique ID. It also rejects
literal boolean `hpvc_test_fixture: true` or `hpvc_test_transport: true` state
attributes, and the exact reserved executor test targets listed in
`inverter/detection.py`. Both metadata and fallback discovery, including Enphase
companion mode/enable entities, use the filter. These markers survive read-only
export projection. Arbitrary names containing `hpvc` are not filtered. Manual
bindings, adapters and executor behavior are unchanged.

## Legacy registry proof

`site_audit/legacy_ownership.json` pins the approved shipped
`home assistant/hpvc_config.yaml` by SHA-256 and its 100 exact template
domain/platform/unique-ID triples. Automatic recognition requires an exact triple,
no config-entry ownership and no duplicate identity. Renamed entity IDs are
supported because the name is not ownership evidence. A supplied package hash,
match flag or reference that conflicts with the approved package vetoes proof.
The exact-copy CLI `--hpvc-package` proof contract is unchanged.

The existing dev.8 explicitly supplied `legacy.registry_ownership` manifest
channel is retained: it asserts an exact entity-ID/unique-ID/platform/config-entry
tuple, rather than inference from names. Package mismatches, duplicate identities
and ownership by any supplied config entry veto this channel too. This channel
is operator-supplied provenance; copying a registry row does not authenticate the
deployment. The automatic catalogue path never infers YAML ownership for an entity
with a config-entry ID.

New `registry_ownership[].classification` and collision
`ownership_classification` fields distinguish `proven_legacy_hpvc_owned`,
`unproven_collision`, and `unrelated`. Renamed entities appear in the inventory
even when they no longer occupy an intended native ID. Existing blocked collision
`ownership` strings remain for dev.8 consumer compatibility. Only proven rows can
reach the existing preview proposal builder. No native replacement installed means
no CAS moves can yet be planned. No proposal is applied.

## Production regression evidence

`tests/fixtures/site-audit-production-redacted.json` is an allowlisted subset of
the supplied production snapshot, with provenance SHA-256. It preserves the 40
blank helpers and real controller/configuration facts needed for these regressions.
Device and registry identifiers are pseudonymized. Network addresses, serials,
credentials, unrelated personal entities and raw production audit files are absent.
It includes three representative proven template collisions; synthetic tests add
unproven and conflicting cases without presenting them as production observations.
The complete supplied snapshot is rerun locally, never published with this patch.

The fixed audit is still a historical observation. Missing Node-RED inventory,
fence evidence, live independent metadata and other readiness gaps are not cured
by these corrections. A fresh site export remains necessary for a later review.
No live collection, install, disable, handoff or hardware action is part of this work.

## Validation

Run `python -B scripts/test_foundation.py`, all scripts in the preserved legacy
validation workflow, and `python -m pytest tests/ha -v` in the exact HA 2025.12.0
and 2026.10.4 environments. The new tests cover the production-derived subset,
strict blank/nonblank handling, discovery provenance, renamed registry identities,
conflicting entries, wrong domain/platform, duplicate IDs, and mutation traps.
