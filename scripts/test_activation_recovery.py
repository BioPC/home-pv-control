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



def updater_source(node_id: str) -> str:
    command = str(BY_ID[node_id].get("command", ""))
    match = re.search(r"cat > \"\$SCRIPT\" <<'NODE'\n(.*?)\nNODE\n", command, re.S)
    if not match:
        raise AssertionError(f"No embedded updater source in {node_id}")
    return match.group(1)

def run_node(source: str, timeout: float = 8.0) -> dict:
    result = subprocess.run(["node", "-e", source], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or f"node exited {result.returncode}")
    try:
        return json.loads(result.stdout.strip())
    except Exception as exc:
        raise AssertionError(f"Invalid JSON output: {result.stdout!r}") from exc


def run_function_node(source: str, msg: dict, global_values: dict | None = None, flow_values: dict | None = None) -> dict:
    wrapper = f"""
const globals=new Map(Object.entries({json.dumps(global_values or {})}));
const flows=new Map(Object.entries({json.dumps(flow_values or {})}));
const global={{get:(k)=>globals.get(k),set:(k,v)=>globals.set(k,v)}};
const flow={{get:(k)=>flows.get(k),set:(k,v)=>flows.set(k,v)}};
const statuses=[];
const node={{status:(v)=>statuses.push(v),warn:()=>{{}},error:()=>{{}}}};
let msg={json.dumps(msg)};
function run(){{{source}}}
const out=run();
console.log(JSON.stringify({{
  out,
  globals:Object.fromEntries(globals),
  flows:Object.fromEntries(flows),
  statuses,
  msg
}}));
"""
    return run_node(wrapper)


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
    tx = {"state": "complete", "tag": "v1.6.0", "commit": "abc", "transactionId": "t1", "activationComplete": False}
    base = {"schema": 4, "tag": "v1.6.0", "commit": "abc", "transactionId": "t1", "phase": "awaiting_quick_reload"}
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




def test_finalized_activation_reconciles_stale_latches() -> None:
    """A durable finalized transaction must repair stale HA/Node-RED update latches."""
    guard = str(BY_ID["hpvcrecoveryphaseguard155"].get("func", ""))
    payload = json.dumps({"run": False, "reason": "already-finalized"})

    clean_states = {
        "input_boolean.hpvc_update_reload_required": {"state": "off"},
        "input_boolean.hpvc_update_in_progress": {"state": "off"},
    }
    clean = run_function_node(guard, {"payload": payload}, {"homeassistant.homeAssistant.states": clean_states}, {"hpvc_update_in_progress": False})
    assert clean["out"] == [None, None], "clean finalized transaction must remain a no-op"

    stale_reload = dict(clean_states)
    stale_reload["input_boolean.hpvc_update_reload_required"] = {"state": "on"}
    reload_result = run_function_node(guard, {"payload": payload}, {"homeassistant.homeAssistant.states": stale_reload}, {"hpvc_update_in_progress": False})
    assert isinstance(reload_result["out"], list) and reload_result["out"][0] is not None and reload_result["out"][1] is None, "stale reload_required must rerun idempotent finalization"

    stale_helper = dict(clean_states)
    stale_helper["input_boolean.hpvc_update_in_progress"] = {"state": "on"}
    helper_result = run_function_node(guard, {"payload": payload}, {"homeassistant.homeAssistant.states": stale_helper}, {"hpvc_update_in_progress": False})
    assert isinstance(helper_result["out"], list) and helper_result["out"][0] is not None and helper_result["out"][1] is None, "stale HA update_in_progress must rerun idempotent finalization"

    local_result = run_function_node(guard, {"payload": payload}, {"homeassistant.homeAssistant.states": clean_states}, {"hpvc_update_in_progress": True})
    assert isinstance(local_result["out"], list) and local_result["out"][0] is not None and local_result["out"][1] is None, "stale Node-RED update latch must rerun idempotent finalization"

    # The early periodic guard must no longer trust a stale HA in-progress helper.
    pending_guard = str(BY_ID["hpvcpendingreloadguard155"].get("func", ""))
    pending = run_function_node(
        pending_guard,
        {},
        {"homeassistant.homeAssistant.states": {"input_boolean.hpvc_update_in_progress": {"state": "on"}}},
        {},
    )
    assert pending["out"] is not None, "durable transaction classifier must see through a stale HA in-progress helper"

    # Genuine unfinished transactions are still rejected by durable transaction state.
    unfinished = phase_case({"state": "installing", "tag": "v1.6.0", "commit": "abc", "transactionId": "t1"})
    assert unfinished["run"] is False and unfinished.get("reason") == "transaction-not-complete", "live/incomplete update must never be reconciled as finalized"

    finish_source = str(BY_ID["2eb9a6910674ac6d"].get("func", ""))
    finish = run_function_node(
        finish_source,
        {"payload": json.dumps({"ok": True, "activationComplete": True, "activationFinalized": True})},
        {},
        {
            "hpvc_update_in_progress": True,
            "hpvc_update_started_at": 12345,
            "hpvc_update_recovery_probe_at": 67890,
            "hpvc_update_phase": "detached",
        },
    )
    flows = finish["flows"]
    assert flows.get("hpvc_update_in_progress") is False
    assert flows.get("hpvc_update_started_at") == 0
    assert flows.get("hpvc_update_recovery_probe_at") == 0
    assert flows.get("hpvc_update_phase") == "", "successful finalization must clear Node-RED-local update state"

    readiness = heredoc("hpvcreloadreadiness155")
    required = [
        "beganFinalized=tx.activationFinalized===true",
        "if(tx.activationComplete===true||tx.activationFinalized===true)",
        "tx.activationComplete!==true&&tx.activationFinalized!==true",
        "entity_id:'input_boolean.hpvc_update_in_progress'",
        "hpvc_update_in_progress expected off",
        "currentTx.activationFinalized===true&&!beganFinalized",
    ]
    missing = [fragment for fragment in required if fragment not in readiness]
    assert not missing, f"finalized reconciliation runner is missing invariants: {missing}"

def finish_case(payload: dict) -> dict:
    func = str(BY_ID["2eb9a6910674ac6d"].get("func", ""))
    wrapper = f"""
const statuses=[]; const node={{status:(v)=>statuses.push(v)}};
const msg={{payload:{json.dumps(json.dumps(payload))}}};
function run(msg){{{func}}}
const out=run(msg); console.log(JSON.stringify({{out,statuses}}));
"""
    return run_node(wrapper)



def orphan_reconcile_case(*, reload_state="on", progress_state="off", package_version="1.6.0", transaction=None, updater_lock=False, fail_service=None) -> dict:
    """Run the shipped orphan reconciler with a temporary config and mocked HA API."""
    source = heredoc("hpvcorphanreconcile156")
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td)
        recovery = cfg / "hpvc-data" / "update-recovery"
        recovery.mkdir(parents=True)
        packages = cfg / "packages"
        packages.mkdir()
        (packages / "hpvc_config.yaml").write_text(
            f'template:\n  - sensor:\n      - unique_id: hpvc_installed_version\n        state: "{package_version}"\n',
            encoding="utf-8",
        )
        if transaction is not None:
            (recovery / "transaction.json").write_text(json.dumps(transaction), encoding="utf-8")
        if updater_lock:
            (recovery / "updater.lock").write_text(json.dumps({"txid": "stale", "pid": 999999}), encoding="utf-8")
        patched, count = re.subn(
            r"function baseDir\(\)\{.*?\}\nfunction apiRequest",
            f"function baseDir(){{return {json.dumps(cfg.as_posix())};}}\nfunction apiRequest",
            source, count=1, flags=re.S,
        )
        if count != 1:
            raise AssertionError("Could not patch orphan reconciler baseDir")
        initial_states = [
            {"entity_id": "input_boolean.hpvc_update_reload_required", "state": reload_state},
            {"entity_id": "input_boolean.hpvc_update_in_progress", "state": progress_state},
        ]
        mock = (
            "const __states=" + json.dumps(initial_states) + ";const __calls=[];\n"
            "function apiRequest(method,apiPath,body){\n"
            "  if(method==='GET'&&apiPath==='/core/api/states')return Promise.resolve(__states.map(x=>({...x})));\n"
            "  if(method==='POST'&&apiPath.startsWith('/core/api/services/')){\n"
            "    __calls.push({method,apiPath,body});\n"
            "    const entity=String(body?.entity_id||'');\n"
            + "    if(" + json.dumps(fail_service) + "&&entity===" + json.dumps(fail_service) + ")return Promise.reject(new Error('synthetic HA failure'));\n"
            "    if(apiPath.endsWith('/input_boolean/turn_off')){const row=__states.find(x=>x.entity_id===entity);if(row)row.state='off';}\n"
            "    return Promise.resolve([]);\n"
            "  }\n"
            "  return Promise.resolve(null);\n"
            "}\n"
        )
        patched, count = re.subn(
            r"function apiRequest\(method,apiPath,body\)\{.*?\}\nasync function requestStates",
            mock + "async function requestStates", patched, count=1, flags=re.S,
        )
        if count != 1:
            raise AssertionError("Could not patch orphan reconciler HA API")
        patched = patched.replace(
            "process.stdout.write(JSON.stringify({ok:true,orphanReconciled:true,alreadyClean:false}));",
            "process.stdout.write(JSON.stringify({ok:true,orphanReconciled:true,alreadyClean:false,calls:__calls}));",
        ).replace(
            "process.stdout.write(JSON.stringify({ok:true,orphanReconciled:true,alreadyClean:true}));",
            "process.stdout.write(JSON.stringify({ok:true,orphanReconciled:true,alreadyClean:true,calls:__calls}));",
        ).replace(
            "process.stdout.write(JSON.stringify({ok:false,orphanReconciled:false,error:String(e.message||e)}));",
            "process.stdout.write(JSON.stringify({ok:false,orphanReconciled:false,error:String(e.message||e),calls:__calls}));",
        )
        return run_node(patched)


def test_orphaned_activation_without_transaction() -> None:
    guard = str(BY_ID["hpvcrecoveryphaseguard155"].get("func", ""))
    payload = json.dumps({"run": False, "reason": "transaction-missing"})
    stale_states = {
        "input_boolean.hpvc_update_reload_required": {"state": "on"},
        "input_boolean.hpvc_update_in_progress": {"state": "on"},
    }
    candidate = run_function_node(
        guard, {"payload": payload},
        {"homeassistant.homeAssistant.states": stale_states, "homePvControlUninstallShutdownActive": False},
        {"hpvc_update_in_progress": True, "hpvc_update_phase": ""},
    )
    assert isinstance(candidate["out"], list) and candidate["out"][0] is None and candidate["out"][1] is not None, "missing transaction + stale latches must route only to orphan reconciliation"
    active_phase = run_function_node(
        guard, {"payload": payload},
        {"homeassistant.homeAssistant.states": stale_states, "homePvControlUninstallShutdownActive": False},
        {"hpvc_update_in_progress": True, "hpvc_update_phase": "shutdown"},
    )
    assert active_phase["out"] == [None, None], "ordinary safe-shutdown phase must never be auto-cleared as orphaned"
    repaired = orphan_reconcile_case(reload_state="on", progress_state="on")
    assert repaired["ok"] is True and repaired["orphanReconciled"] is True
    calls = repaired.get("calls", [])
    boolean_calls = [c for c in calls if "/input_boolean/turn_off" in c.get("apiPath", "")]
    assert [c["body"]["entity_id"] for c in boolean_calls] == [
        "input_boolean.hpvc_update_in_progress",
        "input_boolean.hpvc_update_reload_required",
    ], "orphan cleanup must clear runtime gate last"
    present = orphan_reconcile_case(transaction={"state": "complete"})
    assert present.get("ignore") is True and present.get("reason") == "transaction-present", "any durable transaction must refuse no-transaction orphan cleanup"
    locked = orphan_reconcile_case(updater_lock=True)
    assert locked.get("ignore") is True and locked.get("reason") == "lock-present", "ambiguous updater lock must refuse orphan cleanup"
    wrong_package = orphan_reconcile_case(package_version="1.5.5")
    assert wrong_package.get("ignore") is True and wrong_package.get("reason") == "managed-v1.6.0-package-not-verified", "orphan cleanup requires the managed v1.6.0 package marker"
    failed = orphan_reconcile_case(reload_state="on", progress_state="on", fail_service="input_boolean.hpvc_update_reload_required")
    assert failed["ok"] is False, "HA failure must remain retryable"
    failed_calls = failed.get("calls", [])
    assert any(c.get("body", {}).get("entity_id") == "input_boolean.hpvc_update_in_progress" for c in failed_calls)
    assert any(c.get("body", {}).get("entity_id") == "input_boolean.hpvc_update_reload_required" for c in failed_calls)
    finish = str(BY_ID["hpvcorphanfinish156"].get("func", ""))
    finished = run_function_node(
        finish, {"payload": json.dumps({"ok": True, "orphanReconciled": True})}, {},
        {"hpvc_update_in_progress": True, "hpvc_update_started_at": 1, "hpvc_update_recovery_probe_at": 2, "hpvc_update_phase": "detached"},
    )
    assert finished["flows"].get("hpvc_update_in_progress") is False
    assert finished["flows"].get("hpvc_update_started_at") == 0
    assert finished["flows"].get("hpvc_update_recovery_probe_at") == 0
    assert finished["flows"].get("hpvc_update_phase") == ""

def test_finish_stale_results() -> None:
    busy = finish_case({"ok": False, "busy": True, "ignore": True})
    assert busy["out"] == [None, None], "busy duplicate must not publish helper changes"
    pending = finish_case({"ok": False, "activationComplete": True, "finalizationPending": True, "ignore": True})
    assert pending["out"] == [None, None], "finalization-pending retry must not re-arm reload state"
    failure = finish_case({"ok": False, "error": "synthetic failure", "attemptId": "old-attempt"})
    assert failure["out"] == [None, None], "delayed ordinary failure must never publish helper changes after lease release"
    encoded = json.dumps(failure)
    assert "input_boolean.turn_on" not in encoded and "hpvc_update_reload_required" not in encoded, "stale failure output must not re-arm activation gate"



def finalized_readiness_case(tx: dict, fail_entity: str | None = None) -> dict:
    """Run the embedded finalizer with mocked HA states and no readiness file."""
    source = heredoc("hpvcreloadreadiness155")
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td)
        recovery = cfg / "hpvc-data" / "update-recovery"
        recovery.mkdir(parents=True)
        (recovery / "transaction.json").write_text(json.dumps(tx), encoding="utf-8")
        patched, count = re.subn(
            r"function baseDir\(\)\{.*?\}\nfunction apiRequest",
            f"function baseDir(){{return {json.dumps(cfg.as_posix())};}}\nfunction apiRequest",
            source,
            count=1,
            flags=re.S,
        )
        if count != 1:
            raise AssertionError("Could not patch readiness baseDir for finalized reconciliation")
        states = {
            "input_boolean.hpvc_update_resume_enabled": {"entity_id": "input_boolean.hpvc_update_resume_enabled", "state": "on"},
            "input_boolean.hpvc_update_in_progress": {"entity_id": "input_boolean.hpvc_update_in_progress", "state": "on"},
            "input_boolean.hpvc_update_reload_required": {"entity_id": "input_boolean.hpvc_update_reload_required", "state": "on"},
            "input_boolean.hpvc_enabled": {"entity_id": "input_boolean.hpvc_enabled", "state": "off"},
            "input_text.hpvc_update_status": {"entity_id": "input_text.hpvc_update_status", "state": "Update activation pending"},
        }
        mock = f"""const MOCK_STATES={json.dumps(states)};
function apiRequest(method,apiPath,body){{
 if(method==='GET'&&apiPath==='/core/api/states')return Promise.resolve(Object.values(MOCK_STATES));
 if(method==='POST'&&apiPath.startsWith('/core/api/services/')){{
  const parts=apiPath.split('/');const domain=parts[4],serviceName=parts[5];const eid=body&&body.entity_id?String(body.entity_id):'';
  if({json.dumps(fail_entity)}&&eid==={json.dumps(fail_entity)})return Promise.reject(new Error('synthetic service failure'));
  if(eid){{
   if(!MOCK_STATES[eid])MOCK_STATES[eid]={{entity_id:eid,state:'unknown'}};
   if(domain==='input_boolean'&&(serviceName==='turn_on'||serviceName==='turn_off'))MOCK_STATES[eid].state=serviceName==='turn_on'?'on':'off';
   if(domain==='input_text'&&serviceName==='set_value')MOCK_STATES[eid].state=String(body.value||'');
  }}
  return Promise.resolve(null);
 }}
 return Promise.resolve(null);
}}
async function requestStates"""
        patched, count = re.subn(r"function apiRequest\(method,apiPath,body\)\{.*?\}\nasync function requestStates", mock, patched, count=1, flags=re.S)
        if count != 1:
            raise AssertionError("Could not patch readiness API for finalized reconciliation")
        return run_node(patched)


def test_finalized_readiness_runner_reconciles_without_transient_metadata() -> None:
    base = {"state": "complete", "tag": "v1.6.0", "commit": "abc", "transactionId": "t1", "resumeEnabled": True}
    normal = finalized_readiness_case({**base, "activationComplete": True, "activationFinalized": True})
    assert normal.get("ok") is True and normal.get("alreadyComplete") is True, "finalized transaction must repair stale helpers without readiness metadata"

    implied_complete = finalized_readiness_case({**base, "activationFinalized": True})
    assert implied_complete.get("ok") is True and implied_complete.get("activationComplete") is True, "activationFinalized must be sufficient durable proof for idempotent cleanup"

    failure = finalized_readiness_case(
        {**base, "activationComplete": True, "activationFinalized": True},
        fail_entity="input_boolean.hpvc_update_reload_required",
    )
    assert failure.get("ok") is False and "synthetic service failure" in str(failure.get("error", "")), "new cleanup failure must remain retryable, not be hidden as stale success"

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
        tx = {"state": "complete", "tag": "v1.6.0", "commit": "abc", "transactionId": "t1", "resumeEnabled": True, "activationComplete": False}
        spec = {"schema": 4, "tag": "v1.6.0", "commit": "abc", "transactionId": "t1", "resumeEnabled": True, "phase": "awaiting_quick_reload", "entities": ["input_boolean.hpvc_test"]}
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
        tx = {"state": "complete", "tag": "v1.6.0", "commit": "abc", "transactionId": "t1", "resumeEnabled": True, "activationComplete": False}
        spec = {"schema": 4, "tag": "v1.6.0", "commit": "abc", "transactionId": "t1", "resumeEnabled": True, "phase": "awaiting_quick_reload", "entities": ["input_boolean.hpvc_test"]}
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



def extract_js_function(source: str, name: str) -> str:
    marker = f"async function {name}("
    start = source.find(marker)
    if start < 0:
        marker = f"function {name}("
        start = source.find(marker)
    if start < 0:
        raise AssertionError(f"Function {name} not found")
    brace = source.find("{", start)
    if brace < 0:
        raise AssertionError(f"Function {name} has no body")
    depth = 0
    quote = None
    escape = False
    i = brace
    while i < len(source):
        ch = source[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
        else:
            if ch in ("'", '"', '`'):
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return source[start:i + 1]
        i += 1
    raise AssertionError(f"Function {name} body is unterminated")



def extract_js_block(source: str, marker: str, start_at: int = 0) -> str:
    start = source.find(marker, start_at)
    if start < 0:
        raise AssertionError(f"Block marker not found: {marker}")
    brace = source.find("{", start)
    if brace < 0:
        raise AssertionError(f"Block marker has no body: {marker}")
    depth = 0
    quote = None
    escape = False
    i = brace
    while i < len(source):
        ch = source[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
        else:
            if ch in ("'", '"', '`'):
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return source[start:i + 1]
        i += 1
    raise AssertionError(f"Block marker is unterminated: {marker}")


def test_preinstall_no_change_recovery() -> None:
    """Pre-install failures restore/retain intent without arming activation."""
    updater = updater_source("04dd6468527f5aad")
    classify = extract_js_function(updater, "isPreInstallNoChange")
    reconcile = extract_js_function(updater, "reconcilePreInstallNoChange")
    wrapper = f"""
const calls=[]; let writes=[]; let resultPayloads=[];
let failIntent=false;
async function savedResumeIntent(){{if(failIntent)throw new Error('HA unavailable');return true;}}
function writeRecovery(dir,record){{writes.push(JSON.parse(JSON.stringify(record)));}}
async function haService(domain,service,data){{calls.push({{domain,service,data}});}}
async function setStatus(value){{calls.push({{status:value}});}}
function writeResultBestEffort(value){{resultPayloads.push(value);}}
async function publishRolledBackOutcome(record,dir,resume){{
  calls.push({{domain:'input_boolean',service:'turn_off',data:{{entity_id:'input_boolean.hpvc_update_reload_required'}}}});
  calls.push({{published:true,resume}});
}}
{classify}
{reconcile}
(async()=>{{
 const classifications=[
   isPreInstallNoChange(null),
   isPreInstallNoChange({{state:'launched',deploymentAttempted:false}}),
   isPreInstallNoChange({{state:'prepared',deploymentAttempted:false}}),
   isPreInstallNoChange({{state:'installing',deploymentAttempted:false}})
 ];
 const first=await reconcilePreInstallNoChange(null,'/tmp','missing parser/package');
 const firstCalls=calls.splice(0); const firstWrites=writes.splice(0);
 failIntent=true;
 const second=await reconcilePreInstallNoChange({{schema:1,state:'launched',resumeCaptured:false,deploymentAttempted:false}},'/tmp','initial HA state failed');
 const secondCalls=calls.splice(0); const secondWrites=writes.splice(0);
 console.log(JSON.stringify({{classifications,first,firstCalls,firstWrites,second,secondCalls,secondWrites}}));
}})().catch(e=>{{console.error(e);process.exit(1);}});
"""
    result = run_node(wrapper)
    assert result["classifications"] == [True, True, True, False], "only no-change stages may use pre-install recovery"
    assert result["first"]["pending"] is False, "parser/path preflight failure should reconcile immediately when HA is reachable"
    assert result["firstWrites"][-1]["state"] == "rolled-back" and result["firstWrites"][-1]["rollbackKind"] == "pre-install-no-changes"
    assert not any(c.get("service") == "turn_on" and c.get("data", {}).get("entity_id") == "input_boolean.hpvc_update_reload_required" for c in result["firstCalls"]), "pre-install failure must never arm activation"
    assert result["second"]["pending"] is True, "initial HA API failure must remain retryable without inventing disabled intent"
    assert result["secondWrites"][-1].get("resumeCaptured") is False, "unknown resume intent must remain uncaptured for retry"
    assert any(c.get("service") == "turn_off" and c.get("data", {}).get("entity_id") == "input_boolean.hpvc_update_reload_required" for c in result["secondCalls"]), "pending pre-install recovery must explicitly keep activation gate off"
    recovery_branch = updater.find("if(isPreInstallNoChange(tx))", updater.find("if(recoveryOnly)"))
    discover_after = updater.find("api=await discoverNr();", recovery_branch)
    assert recovery_branch >= 0 and discover_after > recovery_branch, "recovery-only must reconcile pre-install no-change before Node-RED API discovery"



def test_terminal_nochange_publication_retry_without_admin() -> None:
    """Terminal pre-install/no-change publication retry must never need Node-RED Admin API."""
    updater = updater_source("04dd6468527f5aad")
    reconcile = extract_js_function(updater, "reconcilePreInstallNoChange")
    verify = extract_js_function(updater, "verifyRolledBackTransaction")
    publish = extract_js_function(updater, "publishRolledBackOutcome")

    recovery_pos = updater.find("if(recoveryOnly)")
    terminal_block = extract_js_block(updater, "if(terminal)", recovery_pos)
    assert "rollbackKind==='pre-install-no-changes'" in terminal_block
    assert terminal_block.find("rollbackKind==='pre-install-no-changes'") < terminal_block.find("api=await discoverNr()"), \
        "verified no-change terminal recovery must occur before Admin API discovery"

    # The real terminal-failure catch must still gate genuine installed/rollback
    # outcomes whose files/flows cannot be verified.
    attention_pos = updater.find("if(terminalReconcileAttempt)")
    attention_block = extract_js_block(updater, "if(terminalReconcileAttempt)", attention_pos)
    assert "input_boolean.hpvc_update_reload_required" in attention_block
    assert "turn_on" in attention_block, "genuine terminal verification failure must still inhibit unsafe resumption"

    def case(resume_enabled: bool) -> dict:
        wrapper = f"""
const calls=[]; let writes=[]; let results=[]; let statuses=[]; let discoverCalls=0; let failEnabledPublish=true;
const fs={{unlinkSync:()=>{{}}}};
const path={{join:(...parts)=>parts.join('/')}};
async function savedResumeIntent(){{return {str(resume_enabled).lower()};}}
function writeRecovery(dir,record){{writes.push(JSON.parse(JSON.stringify(record)));}}
async function haService(domain,service,data){{
  calls.push({{domain,service,data}});
  if(failEnabledPublish && data && data.entity_id==='input_boolean.hpvc_enabled'){{
    failEnabledPublish=false;
    throw new Error('synthetic HA enabled-state publication failure');
  }}
}}
async function setStatus(value){{statuses.push(value);}}
function writeResultBestEffort(value){{results.push(value);}}
async function notifyBestEffort(){{}}
function acknowledgeTerminalPublication(dir,tx,kind){{
  tx.publicationAcknowledged=true;tx.publicationKind=kind;writeRecovery(dir,tx);
}}
async function liveResumeIntent(){{return false;}}
async function discoverNr(){{discoverCalls++;throw new Error('Node-RED Admin API unavailable');}}
{verify}
{publish}
{reconcile}

(async()=>{{
  // Phase 1: prerequisite/no-change recovery reaches terminal rolled-back state,
  // but publishing hpvc_enabled fails. This mirrors the reproduced audit sequence.
  const first=await reconcilePreInstallNoChange(
    {{schema:1,state:'launched',resumeEnabled:{str(resume_enabled).lower()},resumeCaptured:true,terminalPolicyVersion:2,deploymentAttempted:false}},
    '/recovery',
    'synthetic prerequisite failure'
  );
  const terminal=first.record;
  const phase1={{pending:first.pending,terminal:JSON.parse(JSON.stringify(terminal)),calls:calls.splice(0),writes:writes.splice(0)}};

  // Phase 2: HA publication is healthy again, but Admin API remains unavailable.
  // Execute the exact shipped recovery-only terminal block.
  let terminalReconcileAttempt=false,terminalOutcomeVerified=false,tx=null,resumeEnabled=false,api=null;
  const recoveryDir='/recovery',configPath='/config/packages/hpvc_config.yaml',dashPath='/config/hpvc_dashboard.yaml';
  const process={{stderr:{{write:()=>{{}}}},exitCode:0}};
  failEnabledPublish=false;
  async function runTerminal(){{
    {terminal_block}
  }}
  await runTerminal();
  console.log(JSON.stringify({{
    phase1,
    discoverCalls,
    calls,
    writes,
    terminal,
    terminalReconcileAttempt,
    terminalOutcomeVerified,
    exitCode:process.exitCode
  }}));
}})().catch(e=>{{console.error(e);process.exit(1);}});
"""
        return run_node(wrapper)

    for resume in (True, False):
        result = case(resume)
        assert result["phase1"]["pending"] is True, "failed enabled-state publication must leave terminal outcome retryable"
        tx = result["phase1"]["terminal"]
        assert tx["state"] == "rolled-back"
        assert tx["rollbackKind"] == "pre-install-no-changes"
        assert tx["rollbackVerified"] is True
        assert tx["deploymentAttempted"] is False
        assert result["discoverCalls"] == 0, "no-change terminal retry must not access Node-RED Admin API"
        assert result["terminalOutcomeVerified"] is True
        assert result["terminal"].get("publicationAcknowledged") is True
        assert result["exitCode"] == 0

        # Activation must stay Off throughout retry publication.
        assert not any(
            c.get("service") == "turn_on"
            and c.get("data", {}).get("entity_id") == "input_boolean.hpvc_update_reload_required"
            for c in result["calls"]
        ), "no-change terminal retry must never arm activation"

        enabled_calls = [
            c for c in result["calls"]
            if c.get("data", {}).get("entity_id") == "input_boolean.hpvc_enabled"
        ]
        assert enabled_calls, "retry must republish saved HPVC enabled intent"
        expected_service = "turn_on" if resume else "turn_off"
        assert enabled_calls[-1]["service"] == expected_service, "saved enabled/disabled intent must survive publication retry"



def test_domain_generic_activation_inventory() -> None:
    updater = updater_source("04dd6468527f5aad")
    fn = extract_js_function(updater, "packageActivationInventory")
    doc = {
        "input_boolean": {"hpvc_test": {"name": "Test"}},
        "template": [{
            "sensor": [{"unique_id": "hpvc_new_sensor", "default_entity_id": "sensor.hpvc_new_sensor"}],
            "switch": [{"unique_id": "hpvc_new_switch", "default_entity_id": "switch.hpvc_new_switch"}],
            "trigger": [{"platform": "state", "entity_id": "sensor.x"}],
        }],
    }
    wrapper = f"""
const DOC={json.dumps(doc)};
const HPVC_RELOAD_HELPER_DOMAINS=new Set(['input_boolean','input_number','input_text','input_select','input_button','input_datetime','counter','timer','script']);
function parseYamlStrict(){{return DOC;}}
{fn}
const out=packageActivationInventory(Buffer.from('x'),'synthetic',true);
console.log(JSON.stringify({{helpers:out.helpers,templates:[...out.templateIds.entries()]}}));
"""
    result = run_node(wrapper)
    templates = dict(result["templates"])
    assert templates.get("hpvc_new_sensor") == "sensor.hpvc_new_sensor"
    assert templates.get("hpvc_new_switch") == "switch.hpvc_new_switch", "activation inventory must include non-sensor template domains"


def maintenance_case(node_id: str, readback: str, freshness: str, value: str = "100") -> dict:
    source = str(BY_ID[node_id].get("func", ""))
    fn = extract_js_function(source, "configuredInverterVerification")
    now = int(time.time() * 1000)
    states = {
        "input_number.hpvc_inverter_count": {"state": "1"},
        "input_number.hpvc_pv_adjust_deadband": {"state": "25"},
        "input_select.hpvc_pv1_control_method": {"state": "Action/service"},
        "input_text.hpvc_pv1_limit_number": {"state": ""},
        "input_text.hpvc_pv1_action": {"state": "script.test"},
        "input_text.hpvc_pv1_readback_entity": {"state": "sensor.test_readback"},
        "input_select.hpvc_pv1_limit_unit": {"state": "Percent"},
        "input_number.hpvc_pv1_full_limit": {"state": "100"},
    }
    if readback == "available":
        states["sensor.test_readback"] = {"state": value}
    elif readback == "unavailable":
        states["sensor.test_readback"] = {"state": "unavailable"}
    if freshness != "missing":
        observed = now - (200000 if freshness == "stale" else 1000)
        states["sensor.hpvc_source_freshness"] = {"state": "ok", "attributes": {
            "freshness_transport": "ha_template_last_reported_snapshot",
            "snapshot_epoch_ms": now - 500,
            "pv1_last_reported_ms": observed,
        }}
    wrapper = f"""
const states={json.dumps(states)};
const stateOf=(entity,fallback='')=>states[entity]&&states[entity].state!==undefined?String(states[entity].state):fallback;
const global={{get:()=>undefined}};
{fn}
const out=configuredInverterVerification(states,stateOf);
console.log(JSON.stringify(out));
"""
    return run_node(wrapper)


def test_maintenance_requires_fresh_action_readback() -> None:
    for node_id in ["eb9674e0d58dc6d1", "6e1516a98c6391ee", "b6d450b56fb931b3"]:
        stale = maintenance_case(node_id, "available", "stale")
        missing = maintenance_case(node_id, "available", "missing")
        unavailable = maintenance_case(node_id, "unavailable", "fresh")
        partial = maintenance_case(node_id, "available", "fresh", "50")
        full = maintenance_case(node_id, "available", "fresh", "100")
        assert stale["unavailable"], f"{node_id}: stale numeric readback must not authorize maintenance"
        assert missing["unavailable"], f"{node_id}: missing freshness snapshot must not authorize maintenance"
        assert unavailable["unavailable"], f"{node_id}: unavailable readback must not authorize maintenance"
        assert partial["notFull"], f"{node_id}: fresh partial readback must block maintenance"
        assert full["unavailable"] == [] and full["notFull"] == [], f"{node_id}: fresh full readback should authorize maintenance verification"



def test_night_restore_maintenance_confirmation() -> None:
    safety_source = str(BY_ID["bf031913c0a1facd"].get("func", ""))
    assert "configuredNightInverters.every(inv => nightInverterAtFull(inv, nightFullTolerance))" in safety_source
    assert "nightRestoreFreshPartialObserved" in safety_source
    assert "configuredNightInverters.some(inv => nightInverterVerificationState(inv, nightFullTolerance) === 'partial')" in safety_source

    # Per-inverter verification must be independently trustworthy.
    fn_state = extract_js_function(safety_source, "nightInverterVerificationState")
    fn_full = extract_js_function(safety_source, "nightInverterAtFull")
    wrapper = f"""
{fn_state}
{fn_full}
const global={{get:()=>undefined}};
const tolerance=25;
const cases={{
 actionFreshFull:{{control_method:'Action/service',current_source:'readback',readback_entity_valid:true,full_power:1000,current:1000}},
 actionCachedFull:{{control_method:'Action/service',current_source:'command-cache',readback_entity_valid:false,full_power:1000,current:1000}},
 actionStartupFull:{{control_method:'Action/service',current_source:'startup-full-assumption',readback_entity_valid:false,full_power:1000,current:1000}},
 numberFreshFull:{{control_method:'Number entity',current_source:'readback',readback_entity_valid:false,full_power:2000,current:2000}},
 numberPartial:{{control_method:'Number entity',current_source:'readback',readback_entity_valid:false,full_power:2000,current:1950}}
}};
console.log(JSON.stringify(Object.fromEntries(Object.entries(cases).map(([k,v])=>[k,nightInverterVerificationState(v,tolerance)]))));
"""
    proof = run_node(wrapper)
    assert proof == {
        "actionFreshFull": "full",
        "actionCachedFull": "unverifiable",
        "actionStartupFull": "unverifiable",
        "numberFreshFull": "full",
        "numberPartial": "partial",
    }

    # Canonical proof signature must include every effective Action/service adapter field.
    required_signature_fields = [
        "valueField", "fixedDataRaw", "targetDataRaw", "preActionsRaw", "postActionsRaw",
        "actionStep", "actionStepRaw", "refreshSeconds", "minimum"
    ]
    for fragment in required_signature_fields:
        assert fragment in safety_source, f"safety signature missing {fragment}"

    for node_id in ["eb9674e0d58dc6d1", "6e1516a98c6391ee", "b6d450b56fb931b3"]:
        source = str(BY_ID[node_id].get("func", ""))
        for fragment in required_signature_fields:
            assert fragment in source, f"{node_id}: watcher signature missing {fragment}"

    # Sequence regression for the reproduced P1:
    # full/full -> partial/offline -> all offline. Contradictory partial telemetry
    # must permanently clear the proof, so it cannot reappear when telemetry vanishes.
    base_inv = {
        "control_method": "Number entity",
        "current_source": "readback",
        "readback_entity_valid": False,
        "limit_unit": "Watts",
        "full_power": 1000,
        "minimum_power": 0,
        "limit_entity": "",
        "action": "",
        "readback_entity": "",
        "value_field": "value",
        "fixed_data_raw": "{}",
        "target_data_raw": "{}",
        "pre_actions_raw": "[]",
        "post_actions_raw": "[]",
        "action_step": 1,
        "action_step_raw": 0,
        "refresh_seconds": 0,
    }

    common_hpvc = {
        "now": int(time.time() * 1000),
        "persistentNightRestore": True,
        "nightRestorePending": False,
        "deadband": 25,
        "thresholdConfigurationValid": True,
        "configured": True,
        "enabled": True,
        "pvPowerValid": False,
        "totalFull": 2000,
        "newInsights": [],
        "configurationProblems": [],
        "runtimeUnavailable": [],
        "configuredInverters": [],
        "inverters": [],
        "unavailableInverters": [],
    }

    def inv(slot: int, current, source="readback"):
        item = dict(base_inv)
        item.update({"slot": slot, "name": f"PV{slot}", "control_key": f"pv{slot}", "limit_entity": f"number.pv{slot}", "current": current, "current_source": source})
        return item

    # Mint proof with both full.
    hpvc1 = dict(common_hpvc)
    hpvc1["configuredInverters"] = [inv(1, 1000), inv(2, 1000)]
    hpvc1["inverters"] = [inv(1, 1000), inv(2, 1000)]
    first = run_function_node(safety_source, {"hpvc": hpvc1}, {"homeassistant.homeAssistant.states": {}})
    proof1 = first["globals"].get("homePvControlNightRestoreFullConfirmation")
    assert proof1 and proof1.get("confirmed") is True, "full/full must mint proof"

    # PV1 becomes partial while PV2 becomes unavailable.
    hpvc2 = dict(common_hpvc)
    hpvc2["configuredInverters"] = [inv(1, 500), inv(2, None, "unavailable")]
    hpvc2["inverters"] = [inv(1, 500)]
    hpvc2["unavailableInverters"] = [{"slot": 2, "name": "PV2"}]
    second = run_function_node(
        safety_source,
        {"hpvc": hpvc2},
        {"homeassistant.homeAssistant.states": {}, "homePvControlNightRestoreFullConfirmation": proof1},
    )
    assert second["globals"].get("homePvControlNightRestoreFullConfirmation") is None, "fresh partial must clear proof even while another inverter is offline"

    # Then both disappear: cleared proof must remain cleared.
    hpvc3 = dict(common_hpvc)
    hpvc3["configuredInverters"] = [inv(1, None, "unavailable"), inv(2, None, "unavailable")]
    hpvc3["inverters"] = []
    hpvc3["unavailableInverters"] = [{"slot": 1, "name": "PV1"}, {"slot": 2, "name": "PV2"}]
    third = run_function_node(
        safety_source,
        {"hpvc": hpvc3},
        {"homeassistant.homeAssistant.states": {}, "homePvControlNightRestoreFullConfirmation": None},
    )
    assert third["globals"].get("homePvControlNightRestoreFullConfirmation") is None, "cleared proof must not revive when all telemetry disappears"

    # Signature mutation regression: payload/control-path changes must invalidate proof.
    sig_fn = extract_js_function(safety_source, "maintenanceAdapterSignature")
    signature_wrapper = f"""
{sig_fn}
const base={{slot:1,control_method:'Action/service',limit_entity:'',action:'script.limit',readback_entity:'sensor.limit',value_field:'value',fixed_data_raw:'{{}}',target_data_raw:'{{}}',pre_actions_raw:'[]',post_actions_raw:'[]',limit_unit:'Percent',action_step:1,action_step_raw:0,refresh_seconds:0,full_power:1000,minimum_power:0}};
const keys=['fixed_data_raw','target_data_raw','value_field','pre_actions_raw','post_actions_raw'];
const baseSig=JSON.stringify(maintenanceAdapterSignature(base));
const changed=Object.fromEntries(keys.map(k=>{{const x={{...base}};x[k]=k.includes('actions')?'[{{"action":"x"}}]':k==='value_field'?'limit':'{{"device":2}}';return [k,JSON.stringify(maintenanceAdapterSignature(x))!==baseSig];}}));
console.log(JSON.stringify(changed));
"""
    changed = run_node(signature_wrapper)
    assert all(changed.values()), f"adapter configuration mutations must alter proof signature: {changed}"


def test_update_guard_retries_fresh_after_preinstall_stop() -> None:
    source = str(BY_ID["247ad595e80b90f3"].get("func", ""))
    assert "Update not started" in source, "guard must recognize the post-reconciliation terminal status"

    # Reproduce the state after successful pre-install reconciliation: HA helper is
    # off, status is terminal, but the Node-RED local latch/phase still says detached.
    states = {
        "input_boolean.hpvc_update_in_progress": {"state": "off"},
        "input_text.hpvc_update_status": {"state": "Update not started: missing parser/package"},
        "input_boolean.hpvc_update_available": {"state": "on"},
        "input_boolean.hpvc_enabled": {"state": "on"},
    }
    result = run_function_node(
        source,
        {},
        {"homeassistant.homeAssistant.states": states},
        {
            "hpvc_update_in_progress": True,
            "hpvc_update_phase": "detached",
            "hpvc_update_started_at": int(time.time() * 1000) - 5000,
            "hpvc_update_recovery_probe_at": 0,
        },
    )
    flows = result["flows"]
    out = result["out"]
    assert flows.get("hpvc_update_in_progress") is True, "new update should acquire a fresh latch"
    assert flows.get("hpvc_update_phase") == "shutdown", "retry must start a fresh ordinary shutdown, not recovery-only"
    assert isinstance(out, list) and out[0] is not None, "fresh retry must use ordinary update output"
    assert not (out[1] and out[1].get("hpvcUpdateRecoveryRetry")), "fresh retry must not be recovery-only"



def test_github_release_lookup_has_deadline() -> None:
    node = BY_ID["3e6dda88c874e566"]
    command = str(node.get("command", ""))
    assert "GitHub API overall timeout after 15 s" in command
    assert "GitHub API request timeout after 10 s" in command
    assert "GitHub API response timeout after 10 s" in command
    assert str(node.get("timer", "")) == "20", "Exec node must bound the child process beyond the internal 15 s deadline"

def main() -> int:
    test_phase_recovery()
    print("PASS activation phase interruption/recovery")
    test_finalized_activation_reconciles_stale_latches()
    print("PASS finalized activation reconciles stale HA/Node-RED latches")
    test_finalized_readiness_runner_reconciles_without_transient_metadata()
    print("PASS finalized readiness cleanup works without transient metadata")
    test_orphaned_activation_without_transaction()
    print("PASS orphaned activation without transaction reconciles safely")
    test_finish_stale_results()
    print("PASS stale/finalization result handling")
    test_exclusive_activation_lease()
    print("PASS exclusive activation lease")
    test_create_before_write_boundary()
    print("PASS create-before-write lock boundary")
    test_delayed_failure_after_newer_finalization()
    print("PASS delayed stale failure is side-effect free")
    test_preinstall_no_change_recovery()
    print("PASS pre-install no-change recovery keeps activation gate off")
    test_terminal_nochange_publication_retry_without_admin()
    print("PASS terminal no-change publication retry avoids Admin API and activation")
    test_domain_generic_activation_inventory()
    print("PASS domain-generic activation inventory")
    test_maintenance_requires_fresh_action_readback()
    print("PASS destructive maintenance requires fresh Action/service readback")
    test_night_restore_maintenance_confirmation()
    print("PASS Night Restore maintenance proof lifecycle and adapter binding")
    test_update_guard_retries_fresh_after_preinstall_stop()
    print("PASS pre-install reconciliation allows a fresh Smart Update retry")
    test_github_release_lookup_has_deadline()
    print("PASS GitHub release lookup is time-bounded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
