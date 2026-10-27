#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
flow = json.loads((ROOT / "node-red" / "hpvc_flow.json").read_text(encoding="utf-8"))
by = {n.get("id"): n for n in flow if n.get("id")}

main = by["49ecf8749ba7c0be"]
assert str(main.get("repeat")) == "10", "PV control cadence must remain 10 seconds"

journal = by["0da39e01b8f2bc7c"]
assert str(journal.get("repeat")) == "60", "runtime journal must not run on every control wake"
assert float(journal.get("onceDelay") or 0) >= 20, "journal startup should be offset from the 10s control wake"

recovery = by["9b8bd06ffa4f3eb6"]
assert str(recovery.get("repeat")) == "60", "report storage recovery should use reduced background cadence"

core = by["6498f50f6fea77b9"].get("func", "")
for token in ["stableForRateLimit", "RATE_LIMIT_FULL_EVERY_MS = 30000", "return null;"]:
    assert token in core, f"missing stable-input fast-path token: {token}"

writes = by["7b758196fe8a7359"].get("func", "")
assert "if(target.changed!==true&&!forceRefresh)continue;" in writes, "inverter writes must remain change-based"

persist_sources=[]
for n in flow:
    for outs in n.get("wires", []):
        if "a531bbe8d15a6096" in outs:
            persist_sources.append(n.get("id"))
assert "d724735e5f1de18b" in persist_sources, "safety-critical override persistence path must remain immediate"

print("PASS issue #9 runtime-load regression")

# Active price-zone limiting must never be downgraded to the idle stable-cycle path.
assert "if (flow.get('homePvControlPriceLimitingActive') === true) return true;" in core
print('PASS active price limiting preserves 10-second full-control cadence')
