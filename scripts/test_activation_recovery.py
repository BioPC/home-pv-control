#!/usr/bin/env python3
"""Behavioral regression checks for HPVC Smart Update activation recovery.

Runs the shipped embedded Node.js recovery/finish logic against temporary mocked
Home Assistant state so interruption/concurrency regressions are caught in CI.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / "node-red" / "hpvc_flow.json"
NODES = json.loads(FLOW.read_text(encoding="utf-8"))
BY_ID = {str(node.get("id")): node for node in NODES}


def heredoc(node_id: str) -> str:
    command = str(BY_ID[node_id].get("command", ""))
    match = re.search(r"node - <<'NODE'\n(.*?)\nNODE", command, re.S)
    if not match:
        raise AssertionError(f"No embedded Node.js heredoc in {node_id}")
    return match.group(1)


def run_node(source: str, timeout: float = 8.0) -> dict:
    result = subprocess.run(["node", "-e", source], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or f"node exited {result.returncode}")
    try:
        return json.loads(result.stdout.strip())
    except Exception as exc:
        raise AssertionError(f"Invalid JSON output: {result.stdout!r}") from exc


def patch_base_dir(source: str, directory: Path) -> str:
    replacement = f"function baseDir(){{return {json.dumps(directory.as_posix())};}}\nfunction readJson"
    patched, count = re.subn(r"function baseDir\(\)\{.*?\}\nfunction readJson", replacement, source, count=1, flags=re.S)
    if count != 1:
        raise AssertionError("Could not patch baseDir in phase checker")
    return patched


def phase_case(tx: dict, spec: dict | None = None, lock: dict | None = None) -> dict:
    source = heredoc("hpvcrecoveryphasecheck155")
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td)
        recovery = cfg / "hpvc-data" / "update-recovery"
        recovery.mkdir(parents=True)
        (recovery / "transaction.json").write_text(json.dumps(tx), encoding="utf-8")
        if spec is not None:
            (recovery / "reload-readiness.json").write_text(json.dumps(spec), encoding="utf-8")
        if lock is not None:
            lock_dir = recovery / "activation.lock"
            lock_dir.mkdir()
            (lock_dir / "owner.json").write_text(json.dumps(lock), encoding="utf-8")
        return run_node(patch_base_dir(source, cfg))


def test_phase_recovery() -> None:
    now = int(time.time() * 1000)
    tx = {"state": "complete", "tag": "v1.5.5", "commit": "abc", "transactionId": "t1", "activationComplete": False}
    base = {"schema": 4, "tag": "v1.5.5", "commit": "abc", "transactionId": "t1", "phase": "awaiting_quick_reload"}
    assert phase_case(tx, base)["run"] is False, "awaiting_quick_reload must remain user-authorized only"
    assert phase_case(tx, {**base, "phase": "checking"})["run"] is True, "abandoned checking must recover"
    fresh = {"transactionId": "t1", "startedAt": now, "heartbeatAt": now}
    active = phase_case(tx, {**base, "phase": "checking"}, fresh)
    assert active["run"] is False and active.get("reason") == "activation-owned", "live checking owner must not overlap"
    stale = {"transactionId": "t1", "startedAt": 1, "heartbeatAt": 1}
    assert phase_case(tx, {**base, "phase": "checking"}, stale)["run"] is True, "stale checking owner must recover"
    assert phase_case({**tx, "activationComplete": True}, {**base, "phase": "finalizing"})["run"] is True, "durable completion must reconcile finalization"
    done = phase_case({**tx, "activationComplete": True, "activationFinalized": True})
    assert done["run"] is False and done.get("reason") == "already-finalized", "finalized activation must stay idempotent"


def finish_case(payload: dict) -> dict:
    func = str(BY_ID["2eb9a6910674ac6d"].get("func", ""))
    wrapper = f"""
const statuses=[]; const node={{status:(v)=>statuses.push(v)}};
const msg={{payload:{json.dumps(json.dumps(payload))}}};
function run(msg){{{func}}}
const out=run(msg); console.log(JSON.stringify({{out,statuses}}));
"""
    return run_node(wrapper)


def test_finish_stale_results() -> None:
    busy = finish_case({"ok": False, "busy": True, "ignore": True})
    assert busy["out"] == [None, None], "busy duplicate must not publish helper changes"
    pending = finish_case({"ok": False, "activationComplete": True, "finalizationPending": True, "ignore": True})
    assert pending["out"] == [None, None], "finalization-pending retry must not re-arm reload state"
    failure = finish_case({"ok": False, "error": "synthetic failure", "attemptId": "old-attempt"})
    assert failure["out"] == [None, None], "delayed ordinary failure must never publish helper changes after lease release"
    encoded = json.dumps(failure)
    assert "input_boolean.turn_on" not in encoded and "hpvc_update_reload_required" not in encoded, "stale failure output must not re-arm activation gate"


def patch_readiness_for_lock_test(source: str, directory: Path) -> str:
    patched, count = re.subn(
        r"function baseDir\(\)\{.*?\}\nfunction apiRequest",
        f"function baseDir(){{return {json.dumps(directory.as_posix())};}}\nfunction apiRequest",
        source,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise AssertionError("Could not patch readiness baseDir")
    mock = "function apiRequest(method,apiPath,body){return new Promise(resolve=>{if(method==='GET')setTimeout(()=>resolve([]),5000);else resolve(null);});}\nasync function requestStates"
    patched, count = re.subn(r"function apiRequest\(method,apiPath,body\)\{.*?\}\nasync function requestStates", mock, patched, count=1, flags=re.S)
    if count != 1:
        raise AssertionError("Could not patch readiness API")
    return patched


def test_exclusive_activation_lease() -> None:
    source = heredoc("hpvcreloadreadiness155")
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td)
        recovery = cfg / "hpvc-data" / "update-recovery"
        recovery.mkdir(parents=True)
        tx = {"state": "complete", "tag": "v1.5.5", "commit": "abc", "transactionId": "t1", "resumeEnabled": True, "activationComplete": False}
        spec = {"schema": 4, "tag": "v1.5.5", "commit": "abc", "transactionId": "t1", "resumeEnabled": True, "phase": "awaiting_quick_reload", "entities": ["input_boolean.hpvc_test"]}
        (recovery / "transaction.json").write_text(json.dumps(tx), encoding="utf-8")
        (recovery / "reload-readiness.json").write_text(json.dumps(spec), encoding="utf-8")
        patched = patch_readiness_for_lock_test(source, cfg)
        first = subprocess.Popen(["node", "-e", patched], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(0.4)
            second = run_node(patched, timeout=3.0)
            assert second.get("busy") is True and second.get("ignore") is True, "overlapping activation must be rejected as busy"
        finally:
            first.terminate()
            try:
                first.wait(timeout=2)
            except subprocess.TimeoutExpired:
                first.kill()



def test_create_before_write_boundary() -> None:
    """A freshly created lock directory without owner.json is busy, never stale."""
    source = heredoc("hpvcreloadreadiness155")
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td)
        recovery = cfg / "hpvc-data" / "update-recovery"
        recovery.mkdir(parents=True)
        tx = {"state": "complete", "tag": "v1.5.5", "commit": "abc", "transactionId": "t1", "resumeEnabled": True, "activationComplete": False}
        spec = {"schema": 4, "tag": "v1.5.5", "commit": "abc", "transactionId": "t1", "resumeEnabled": True, "phase": "awaiting_quick_reload", "entities": ["input_boolean.hpvc_test"]}
        (recovery / "transaction.json").write_text(json.dumps(tx), encoding="utf-8")
        (recovery / "reload-readiness.json").write_text(json.dumps(spec), encoding="utf-8")
        (recovery / "activation.lock").mkdir()  # interleave: mkdir completed, owner.json not yet written
        patched = patch_readiness_for_lock_test(source, cfg)
        result = run_node(patched, timeout=3.0)
        assert result.get("busy") is True and result.get("ignore") is True, "fresh uninitialized lock must be treated as busy"


def test_delayed_failure_after_newer_finalization() -> None:
    """A delayed failure payload cannot re-arm helpers after a newer success."""
    delayed = finish_case({"ok": False, "error": "late synthetic failure", "transactionId": "t1", "attemptId": "attempt-a"})
    assert delayed["out"] == [None, None], "delayed stale failure must be side-effect free at publication boundary"


def main() -> int:
    test_phase_recovery()
    print("PASS activation phase interruption/recovery")
    test_finish_stale_results()
    print("PASS stale/finalization result handling")
    test_exclusive_activation_lease()
    print("PASS exclusive activation lease")
    test_create_before_write_boundary()
    print("PASS create-before-write lock boundary")
    test_delayed_failure_after_newer_finalization()
    print("PASS delayed stale failure is side-effect free")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
