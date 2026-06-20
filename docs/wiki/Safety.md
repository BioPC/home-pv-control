# Safety notes

Home PV Control writes power limits to inverter entities.

Before enabling it:

- verify that every configured `limit_entity` is correct
- test with conservative values
- monitor first runs carefully
- keep a manual way to restore full PV
- understand your local export/import tariffs
- do not use settings that exceed inverter limits

You are responsible for your system configuration.
