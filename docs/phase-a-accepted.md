# Phase A passed before adapter expansion

Run https://github.com/BioPC/home-pv-control/actions/runs/40553564521
Commit 551db26556de0072bb11c9bd797b40f3adc4a78c.

- HA 2025.12.0 / Python 3.13.16: 14 real HA tests passed; 70 foundation tests passed.
- HA 2026.10.4 / Python 3.14.8: 14 real HA tests passed; 70 foundation tests passed.

Native production source at this checkpoint is byte-identical to the approved foundation. Corrections were limited to real-test instrumentation and the historical DNS dependency constraint, with no weakened authorization or cleanup assertions. See phase-a-first-run.md for failed initial attempts. No control-policy conflict was observed.
