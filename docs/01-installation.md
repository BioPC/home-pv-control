# Installation

Home PV Control is installed next to Home Battery Control. It does not modify HBC files.

## Requirements

- Home Assistant
- Node-RED add-on / integration
- Home Battery Control already installed if you want HBC strategy handoff
- PV inverter limit entities exposed in Home Assistant as writable `number` entities

## Step 1 - Copy Home Assistant package

Copy:

```text
home assistant/pv_ems_config.yaml
```

to:

```text
/config/packages/pv_ems_config.yaml
```

Make sure packages are enabled in Home Assistant:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Restart Home Assistant.

## Step 2 - Import Node-RED flow

Import:

```text
node-red/pv_ems_flow.json
```

into Node-RED.

After import, check that the Home Assistant server selected in the nodes is correct.

Deploy Node-RED.

## Step 3 - Add dashboard

Import or copy:

```text
home assistant/pv_ems_dashboard.yaml
```

as a separate dashboard/view.

Do not paste it into your existing HBC dashboard unless you explicitly want to modify HBC.

## Step 4 - Configure entities

Set these helpers from the dashboard:

- Grid power sensor
- Market/export price sensor
- All-in import price sensor
- Total PV power sensor
- PV inverter helpers

## Step 5 - Test

Start with conservative values:

- PV Limiting Price: `0.00`
- Start Limiting When Exporting More Than: `-200 W`
- Target Export Power: `-25 W`
- Import Recalculation Threshold: `200 W`
- Minimum Minutes Between PV Changes: `1`
- Deadband: `25 W`
