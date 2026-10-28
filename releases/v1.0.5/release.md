# Home PV Control v1.0.5

Bugfix release for Node-RED logic and diagnostics.

## Fixed
- Configuration validation now stops the main logic and reports missing entities clearly.
- Negative-price mode now forces PV to minimum even when the home is importing.
- Removed unused Node-RED code (`lastChangedMs` and `currentTotal`).

## Included
- Home Assistant config
- Home Assistant dashboard
- Node-RED flow
