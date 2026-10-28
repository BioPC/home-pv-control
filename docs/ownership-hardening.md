# Local ownership hardening

This changes only the site-audit proof classifier and its regression evidence.
It does not change migration execution, ownership transitions, policy, allocation,
HBC, dispatcher, executor, coordinator, recovery, storage or physical authorization.

Both automatic and manifest-assisted proof require an exact approved catalogue
triple: entity domain, platform and stable unique ID. Current object names may
change. A nonempty config-entry ID blocks YAML legacy ownership: an absent or
ambiguous entry is unresolved; a resolved entry is a conflicting owner for these
catalogued YAML templates. Empty/absent entry ownership is the valid legacy case.
Duplicate registry identities and contradictory package evidence also block proof.

The explicit manifest remains a positive provenance source for exact matching
tuples, including renamed entities. It cannot replace any gate. A manifest row
claiming a different identity or entry owner for the same current entity is
contradictory evidence and blocks proof, even if another manifest row matches.
Rows for other entities do not supply ownership evidence for the current row.

The original positive preview test used uncatalogued `legacy-status` plus an
unresolved `legacy-entry` owner. Its assumption is incompatible with the approved
invariant. Only that test's fixture literals now use `sensor.hpvc_installed_version`,
unique ID `hpvc_installed_version`, no entry owner, and its matching native preview
identity. Its three assertions and entire AST structure remain equivalent under
the documented literal substitutions: two hypothetical moves, the intended
destination, and an unchanged native registry ID. No operation is executed.

`tests/fixtures/ownership-compatibility-change.json` records the old/new test bodies
and module hashes. The preservation manifest updates exactly this one approved
fixture change. A new AST/hash regression verifies all other module text and all
assertions are preserved. A separate negative case retains the old fabricated
identity and traps any attempt to call the preview proposal builder.

The expanded redacted production fixture is now included as
`tests/fixtures/site-audit-production-12-collisions-redacted.json`. It remains a
subset of the supplied historical snapshot, not a live capture. Tests require all
12 known collisions to remain proven, zero proposals without a native replacement,
zero import issues, both real Hoymiles controllers retained, no fake Enphase
controller, immutable input, UNKNOWN readiness and false production authorization.

The local strict checker and complete foundation results are recorded in the
ownership-hardening completion report. Successful local checks only establish
readiness for final publishing and the two-version HA matrix. They do not establish
`DEV8_AUDIT_FIXES_READY_FOR_SITE_RERUN` or permit any production action.
