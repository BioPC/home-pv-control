# Phase A real Home Assistant acceptance

Run the exact foundation on isolated GitHub Actions branch `codex/hpvc-readonly-acceptance` in BioPC/home-pv-control. Do not merge, release, deploy, change Node-RED or enable actuation.

Matrix: HA 2025.12.0 / Python 3.13 / test plugin 0.13.298; HA 2026.10.4 / Python 3.14 / test plugin 0.13.375.

The matrix workflow is a concrete replacement for the previous current-only prepared workflow. Tests and all foundation integration sources are initially unchanged. Only genuine compatibility/lifecycle defects found by the real runtime may be repaired before adapter expansion. Capture exact commit SHA, dependency inventory, logs, and JUnit results. A green test result is not ownership handoff.
