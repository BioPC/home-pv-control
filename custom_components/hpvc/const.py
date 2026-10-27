"""Foundation constants; there is deliberately no actuator capability."""

DOMAIN = "hpvc"
VERSION = "2.0.0-dev.3"
PLATFORMS = ("sensor", "binary_sensor", "switch", "number", "select", "text")
MAIN_INTERVAL = 10.0
STARTUP_DELAY = 5.0
FORCED_FULL_INTERVAL = 30.0
STORE_SCHEMA = 1
LEDGER_SCHEMA = 1
MAX_EVIDENCE = 128
MAX_TERMINAL_OPERATIONS = 128
MAX_CONTROLLERS = 10
FOUNDATION_WRITE_BLOCK = "foundation_phase_no_actuator_implementation"
