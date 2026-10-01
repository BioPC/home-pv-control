[← Main README](../README.md)

# HPVC documentation

These guides document **Home PV Control v1.5.3**.

## What do you want to do?

- **Install HPVC or use Smart Update** → [Installation and upgrade](01-installation.md)
- **Configure sensors, thresholds or an inverter** → [Configuration](02-configuration.md) and [Inverter compatibility](05-inverter-compatibility.md)
- **Understand why HPVC acted** → [How HPVC works](03-how-it-works.md)
- **Fix a problem** → [Troubleshooting](04-troubleshooting.md)
- **Perform a manual HPVC upgrade** → [Manual upgrade](01-installation.md#manual-upgrade)
- **Remove HPVC completely** → [Full uninstall](01-installation.md#full-uninstall) (automatic HPVC cleanup, with manual fallback only when required)

## Start here

1. [Installation and upgrade](01-installation.md)
2. [Configuration](02-configuration.md)
3. [How HPVC works](03-how-it-works.md)
4. [Troubleshooting](04-troubleshooting.md)
5. [Inverter compatibility](05-inverter-compatibility.md)

## Guide map

| Guide | Use it for |
|---|---|
| [Installation](01-installation.md) | Requirements, fresh install, Smart Update/manual upgrade, dashboard setup, verification, the Manual upgrade flow-removal procedure and the authoritative full-uninstall procedure |
| [Configuration](02-configuration.md) | Entity IDs, thresholds, inverter adapters, HBC options and shipped defaults |
| [How it works](03-how-it-works.md) | Control sequence, safety gates, Night Restore, Charge Priority, safe shutdown, diagnostics and reporting |
| [Troubleshooting](04-troubleshooting.md) | Sensor failures, control issues, Node-RED problems, reports and uninstall recovery |
| [Inverter compatibility](05-inverter-compatibility.md) | Supported control methods and integration compatibility guidance |

## Release information

- [v1.5.3 release notes](../RELEASE_NOTES.md)
- [Full changelog](../CHANGELOG.md)
- [v1.5.3 release document](../releases/v1.5.3/release.md)

Smart Update and normal manual upgrades preserve existing HPVC helper values and saved data. Use the [full-uninstall procedure](01-installation.md#full-uninstall) only when you intend to remove HPVC completely and reset it for a clean reinstall.
