# Inverter examples

## Two Hoymiles / OpenDTU inverters

```json
[
  {
    "name": "HMS-2000",
    "limit_entity": "number.hms_2000_4t_limit_nonpersistent_absolute",
    "full_power": 2000,
    "minimum_power": 100,
    "enabled": true
  },
  {
    "name": "HMS-1000",
    "limit_entity": "number.hms_1000_2t_limit_nonpersistent_absolute",
    "full_power": 1000,
    "minimum_power": 50,
    "enabled": true
  }
]
```

## Three generic inverters

```json
[
  {
    "name": "East",
    "limit_entity": "number.east_inverter_limit",
    "full_power": 1500,
    "minimum_power": 80,
    "enabled": true
  },
  {
    "name": "South",
    "limit_entity": "number.south_inverter_limit",
    "full_power": 2000,
    "minimum_power": 100,
    "enabled": true
  },
  {
    "name": "West",
    "limit_entity": "number.west_inverter_limit",
    "full_power": 1000,
    "minimum_power": 50,
    "enabled": true
  }
]
```
