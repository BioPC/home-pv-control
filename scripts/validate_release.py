#!/usr/bin/env python3
"""Static release-integrity checks for Home PV Control.

Designed to run both locally and in GitHub Actions. It intentionally avoids
simulating Home Assistant/Node-RED runtime behavior; it validates deterministic
release artifacts and flow/package structure instead.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

import yaml


class UniqueKeyLoader(yaml.SafeLoader):
    """PyYAML SafeLoader variant that rejects duplicate mapping keys."""


def _construct_unique_mapping(loader: UniqueKeyLoader, node: yaml.nodes.MappingNode, deep: bool = False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"found unhashable key ({exc})", key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"found duplicate key {key!r}", key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_yaml_unique(text: str):
    return yaml.load(text, Loader=UniqueKeyLoader)


ROOT = Path(__file__).resolve().parents[1]
FLOW_PATH = ROOT / "node-red" / "hpvc_flow.json"
PACKAGE_PATH = ROOT / "home assistant" / "hpvc_config.yaml"
DASHBOARD_PATH = ROOT / "home assistant" / "hpvc_dashboard.yaml"
RELEASE_NOTES = ROOT / "RELEASE_NOTES.md"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"

errors: list[str] = []
notes: list[str] = []
skipped: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


def ok(message: str) -> None:
    notes.append(message)

def skip(message: str) -> None:
    skipped.append(message)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        fail(f"Cannot read {path.relative_to(ROOT)}: {exc}")
        return ""


def canonical_version() -> str:
    text = read_text(RELEASE_NOTES)
    match = re.search(r"^# Home PV Control v(\d+\.\d+\.\d+)\s*$", text, re.M)
    if not match:
        fail("RELEASE_NOTES.md must start with '# Home PV Control vX.Y.Z'.")
        return "0.0.0"
    return match.group(1)


VERSION = canonical_version()
RELEASE_DOC = ROOT / "releases" / f"v{VERSION}" / "release.md"

# 1) Release metadata/version consistency.
release_notes_text = read_text(RELEASE_NOTES)
release_doc_text = read_text(RELEASE_DOC)
changelog_text = read_text(CHANGELOG)
readme_text = read_text(README)
dashboard_text = read_text(DASHBOARD_PATH)

if release_notes_text != release_doc_text:
    fail(f"RELEASE_NOTES.md and releases/v{VERSION}/release.md must be byte-for-byte identical.")
else:
    ok("Release notes are synchronized.")

if not re.search(rf"^## v{re.escape(VERSION)}\s+[—-]\s+\d{{4}}-\d{{2}}-\d{{2}}\s*$", changelog_text, re.M):
    fail(f"CHANGELOG.md is missing a dated v{VERSION} section.")

# Keep the GitHub-visible release intro clean: release date first, then prose/sections.
release_lines = release_notes_text.splitlines()
first_nonempty_after_title = next((line for line in release_lines[1:] if line.strip()), "")
if not first_nonempty_after_title.startswith("**Release date:**"):
    fail("RELEASE_NOTES.md must place the release date immediately after the title, before bullets or sections.")

if "### Runtime and maintenance fixes" in release_notes_text:
    fail("Runtime/maintenance release notes must not be nested under Upgrade.")

# Current CHANGELOG section must begin with a subheading rather than loose bullets.
current_change = re.search(rf"^## v{re.escape(VERSION)}[^\n]*\n(?P<body>.*?)(?=^## v\d|\Z)", changelog_text, re.M | re.S)
if current_change:
    body_lines = [line for line in current_change.group("body").splitlines() if line.strip()]
    if body_lines and not body_lines[0].startswith("### "):
        fail(f"CHANGELOG.md v{VERSION} must start with a subsection heading, not a loose bullet or paragraph.")
    bullets = [line.strip() for line in body_lines if line.lstrip().startswith("- ")]
    duplicates = sorted({b for b in bullets if bullets.count(b) > 1})
    if duplicates:
        fail(f"CHANGELOG.md v{VERSION} contains duplicate bullet(s): " + "; ".join(duplicates[:3]))

for label, text, pattern in [
    ("README.md", readme_text, rf"releases/v{re.escape(VERSION)}/release\.md"),
    ("home assistant/hpvc_dashboard.yaml", dashboard_text, rf"Home PV Control \(v{re.escape(VERSION)}\)"),
]:
    if not re.search(pattern, text):
        fail(f"{label} does not reference v{VERSION} as expected.")

# 2) YAML parse + installed-version marker + deterministic HPVC template IDs.
try:
    package = load_yaml_unique(read_text(PACKAGE_PATH))
    if not isinstance(package, dict):
        raise ValueError("top-level YAML is not a mapping")
    ok("hpvc_config.yaml parses as YAML.")
except Exception as exc:
    package = {}
    fail(f"hpvc_config.yaml YAML parse failed: {exc}")

try:
    dashboard = load_yaml_unique(dashboard_text)
    if not isinstance(dashboard, dict):
        raise ValueError("top-level YAML is not a mapping")
    ok("hpvc_dashboard.yaml parses as YAML.")
except Exception as exc:
    dashboard = {}
    fail(f"hpvc_dashboard.yaml YAML parse failed: {exc}")

installed_version = None
template_count = 0
default_ids: set[str] = set()
for block in package.get("template", []) if isinstance(package, dict) else []:
    if not isinstance(block, dict):
        continue
    # Template integration entity platforms are represented as list-valued
    # keys (sensor, binary_sensor, switch, number, button, select, etc.).
    # Walk every platform generically so future HPVC template domains are
    # validated automatically instead of requiring validator maintenance.
    for domain, items in block.items():
        if not isinstance(domain, str) or not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            unique_id = str(item.get("unique_id", "")).strip()
            if not unique_id.startswith("hpvc_"):
                continue
            template_count += 1
            default_id = str(item.get("default_entity_id", "")).strip()
            if not default_id:
                fail(f"Template {domain} unique_id={unique_id!r} is missing default_entity_id.")
            elif not default_id.startswith(domain + ".hpvc_"):
                fail(f"Template {domain} unique_id={unique_id!r} has unexpected default_entity_id={default_id!r}.")
            elif default_id in default_ids:
                fail(f"Duplicate template default_entity_id: {default_id}")
            else:
                default_ids.add(default_id)
            if unique_id == "hpvc_installed_version":
                installed_version = str(item.get("state", "")).strip().strip('"\'')

if template_count == 0:
    fail("No HPVC template entities were found.")
elif len(default_ids) == template_count:
    ok(f"All {template_count} HPVC template entities across all template domains have deterministic default_entity_id values.")

if installed_version != VERSION:
    fail(f"sensor.hpvc_installed_version state is {installed_version!r}; expected {VERSION!r}.")
else:
    ok(f"Installed-version marker matches v{VERSION}.")



# Package-defined ownership inventory used to enforce full-uninstall parity.
# Runtime uninstall remains an explicit allowlist; CI proves that allowlist
# matches the package exactly so future entities cannot be forgotten.
PACKAGE_ENTITY_DOMAINS = (
    "input_boolean",
    "input_number",
    "input_text",
    "input_select",
    "input_button",
    "input_datetime",
    "counter",
    "timer",
)


def collect_package_ownership(package_data: dict) -> tuple[set[str], set[str]]:
    entity_ids: set[str] = set()
    unique_ids: set[str] = set()

    if not isinstance(package_data, dict):
        return entity_ids, unique_ids

    # YAML helpers have deterministic entity IDs from their mapping keys.
    for domain in PACKAGE_ENTITY_DOMAINS:
        entries = package_data.get(domain, {})
        if not isinstance(entries, dict):
            continue
        for key in entries:
            key = str(key).strip()
            if key.startswith("hpvc_"):
                entity_ids.add(f"{domain}.{key}")

    # Package scripts also have deterministic entity IDs from their keys.
    scripts = package_data.get("script", {})
    if isinstance(scripts, dict):
        for key in scripts:
            key = str(key).strip()
            if key.startswith("hpvc_"):
                entity_ids.add(f"script.{key}")

    # Template entities are registry-backed: default_entity_id is the owned
    # entity ID and unique_id preserves ownership if a user renames it. Walk
    # every list-valued template platform generically so future domains such
    # as switch/button/number/select are covered automatically.
    for block in package_data.get("template", []) or []:
        if not isinstance(block, dict):
            continue
        for domain, items in block.items():
            if not isinstance(domain, str) or not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                unique_id = str(item.get("unique_id", "")).strip()
                default_entity_id = str(item.get("default_entity_id", "")).strip()
                if not unique_id.startswith("hpvc_"):
                    continue
                unique_ids.add(unique_id)
                if not default_entity_id:
                    fail(f"Template {domain} unique_id={unique_id!r} cannot be uninstall-owned without default_entity_id.")
                elif not default_entity_id.startswith(domain + ".hpvc_"):
                    fail(f"Template {domain} unique_id={unique_id!r} has non-HPVC default_entity_id={default_entity_id!r}.")
                else:
                    entity_ids.add(default_entity_id)

    # Home Assistant automation registry ownership is stable through the YAML
    # automation id (used as unique_id). Entity IDs may be renamed by users,
    # so uninstall must match these by unique ID rather than guessed entity ID.
    automations = package_data.get("automation", []) or []
    if isinstance(automations, list):
        for item in automations:
            if not isinstance(item, dict):
                continue
            unique_id = str(item.get("unique_id") or item.get("id") or "").strip()
            if unique_id.startswith("hpvc_"):
                unique_ids.add(unique_id)

    return entity_ids, unique_ids


def parse_uninstall_ownership(source: str) -> tuple[set[str], set[str]]:
    entity_match = re.search(r"const exactEntityIds = new Set\((\[.*?\])\);", source, re.S)
    unique_match = re.search(r"const exactUniqueIds = new Set\((\[.*?\])\);", source, re.S)
    if not entity_match or not unique_match:
        fail("Could not parse explicit HPVC uninstall ownership sets.")
        return set(), set()
    try:
        return set(json.loads(entity_match.group(1))), set(json.loads(unique_match.group(1)))
    except Exception as exc:
        fail(f"Could not decode explicit HPVC uninstall ownership sets: {exc}")
        return set(), set()

# 2b) Desktop Maintenance action-row alignment.
def walk_mappings(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_mappings(child)

# The Maintenance section intentionally uses the proven desktop widths shipped by HPVC.
# Validate that exact structure so future edits do not recreate the compressed live layout.
maintenance_rows = []
for candidate in walk_mappings(dashboard):
    if candidate.get("type") != "grid" or candidate.get("columns") != 3:
        continue
    cards = candidate.get("cards")
    if not isinstance(cards, list) or len(cards) < 6:
        continue
    direct_entities = [
        str(card.get("entity", "")) if isinstance(card, dict) and card.get("type") == "tile" else ""
        for card in cards[3:6]
    ]
    if direct_entities == [
        "input_button.hpvc_check_update",
        "input_button.hpvc_remove_flows",
        "input_button.hpvc_uninstall",
    ]:
        maintenance_rows.append(candidate)

if len(maintenance_rows) != 1:
    fail(f"Expected exactly one desktop Maintenance three-column action grid; found {len(maintenance_rows)}.")
else:
    maintenance = maintenance_rows[0]
    cards = maintenance["cards"]
    expected_titles = ["HPVC updates", "Manual upgrade", "Uninstall HPVC"]
    for index, expected_title in enumerate(expected_titles):
        card = cards[index]
        content = str(card.get("content", "")) if isinstance(card, dict) else ""
        if not isinstance(card, dict) or card.get("type") != "markdown" or f'title="{expected_title}"' not in content:
            fail(f"Desktop Maintenance column {index + 1} must start with the {expected_title!r} alert.")
    expected_entities = [
        "input_button.hpvc_check_update",
        "input_button.hpvc_remove_flows",
        "input_button.hpvc_uninstall",
    ]
    for index, expected_entity in enumerate(expected_entities, start=3):
        card = cards[index]
        if not isinstance(card, dict) or card.get("type") != "tile" or card.get("entity") != expected_entity:
            fail(f"Desktop Maintenance action row position {index - 2} must be direct tile {expected_entity}.")
            continue
        rows = card.get("grid_options", {}).get("rows") if isinstance(card.get("grid_options"), dict) else None
        if rows != 1:
            fail(f"Desktop Maintenance tile {expected_entity} must use grid_options.rows: 1.")
    grid_columns = maintenance.get("grid_options", {}).get("columns") if isinstance(maintenance.get("grid_options"), dict) else None
    if grid_columns != 27:
        fail(f"Desktop Maintenance action grid must use the proven desktop width 27; got {grid_columns!r}.")
    if not any("Desktop Maintenance" in message for message in errors):
        ok("Desktop Maintenance top action buttons are aligned as direct single-row peers.")

# 3) Node-RED JSON, IDs, wires, versioned tabs.
try:
    nodes = json.loads(read_text(FLOW_PATH))
    if not isinstance(nodes, list):
        raise ValueError("root must be a JSON array")
    ok("hpvc_flow.json parses as JSON.")
except Exception as exc:
    nodes = []
    fail(f"hpvc_flow.json parse failed: {exc}")

ids: dict[str, dict] = {}
for node in nodes:
    if not isinstance(node, dict):
        fail("Node-RED flow contains a non-object entry.")
        continue
    node_id = str(node.get("id", "")).strip()
    if not node_id:
        fail(f"Node-RED node without id: {node.get('name') or node.get('type')}")
        continue
    if node_id in ids:
        fail(f"Duplicate Node-RED node id: {node_id}")
    ids[node_id] = node

if nodes and len(ids) == len(nodes):
    ok(f"Node-RED node IDs are unique ({len(nodes)} nodes).")

broken_wires: list[tuple[str, str]] = []
for node_id, node in ids.items():
    wires = node.get("wires", [])
    if not isinstance(wires, list):
        continue
    for output in wires:
        if not isinstance(output, list):
            continue
        for target in output:
            if target and target not in ids:
                broken_wires.append((node_id, str(target)))
if broken_wires:
    for src, target in broken_wires[:20]:
        fail(f"Broken Node-RED wire: {src} -> {target}")
    if len(broken_wires) > 20:
        fail(f"...and {len(broken_wires) - 20} more broken wires.")
else:
    ok("Node-RED wire targets are valid.")

expected_tabs = {
    f"HPVC Inputs v{VERSION}",
    f"HPVC Engine v{VERSION}",
    f"HPVC Outputs v{VERSION}",
    f"HPVC Reports v{VERSION}",
}
actual_tabs = {str(n.get("label", "")) for n in nodes if n.get("type") == "tab" and str(n.get("label", "")).startswith("HPVC ")}
if actual_tabs != expected_tabs:
    fail(f"Versioned HPVC tabs mismatch. Expected {sorted(expected_tabs)}, got {sorted(actual_tabs)}")
else:
    ok("Versioned HPVC tab labels match the release version.")

# 4) Function-node JavaScript syntax.
function_nodes = [n for n in nodes if n.get("type") == "function"]
js_failures = 0
js_sources = [(node, "func") for node in function_nodes]
js_sources += [(node, field) for node in function_nodes for field in ["initialize", "finalize"] if str(node.get(field, "")).strip()]
for node, field in js_sources:
    source = str(node.get(field, ""))
    # Function node bodies can contain top-level return; wrap as a normal function.
    wrapped = "function __hpvc_node_red_function__() {\n" + source + "\n}\n"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tmp:
        tmp.write(wrapped)
        temp_path = Path(tmp.name)
    try:
        result = subprocess.run(["node", "--check", str(temp_path)], text=True, capture_output=True)
        if result.returncode != 0:
            js_failures += 1
            fail(f"Function-node JS syntax failed for {node.get('name') or node.get('id')} ({field}): {result.stderr.strip()}")
    finally:
        temp_path.unlink(missing_ok=True)
if function_nodes and js_failures == 0:
    ok(f"JavaScript syntax passed for all {len(function_nodes)} Function nodes.")
    ok(f"JavaScript syntax passed for all {len(js_sources)-len(function_nodes)} Function-node initialization/finalization bodies.")

# 4b) Exec-node shell syntax and embedded Node.js heredoc syntax.
exec_nodes = [n for n in nodes if n.get("type") == "exec" and str(n.get("command", "")).strip()]
exec_shell_failures = 0
embedded_node_failures = 0
embedded_node_count = 0
bash_available = True
for node in exec_nodes:
    command = str(node.get("command", ""))
    if bash_available:
        try:
            shell_result = subprocess.run([os.environ.get("HPVC_BASH", "bash"), "-n"], input=command, text=True, capture_output=True)
        except FileNotFoundError:
            bash_available = False
            skip("Exec-node shell syntax check skipped because bash is unavailable on this host.")
        else:
            if shell_result.returncode != 0:
                exec_shell_failures += 1
                fail(f"Exec-node shell syntax failed for {node.get('name') or node.get('id')}: {shell_result.stderr.strip()}")
    match = re.search(r"node - <<'NODE'\n(.*?)\nNODE", command, re.S)
    if match:
        embedded_node_count += 1
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tmp:
            tmp.write(match.group(1))
            temp_path = Path(tmp.name)
        try:
            result = subprocess.run(["node", "--check", str(temp_path)], text=True, capture_output=True)
            if result.returncode != 0:
                embedded_node_failures += 1
                fail(f"Embedded Node.js syntax failed for {node.get('name') or node.get('id')}: {result.stderr.strip()}")
        finally:
            temp_path.unlink(missing_ok=True)
if exec_nodes and bash_available and exec_shell_failures == 0:
    ok(f"Shell syntax passed for all {len(exec_nodes)} Exec nodes.")
if embedded_node_count and embedded_node_failures == 0:
    ok(f"JavaScript syntax passed for all {embedded_node_count} embedded Node.js Exec scripts.")

# 5) Smart Updater / Recovery Probe parity.
def by_name(name: str) -> dict | None:
    matches = [n for n in nodes if n.get("name") == name]
    if len(matches) != 1:
        fail(f"Expected exactly one Node-RED node named {name!r}; found {len(matches)}.")
        return None
    return matches[0]


def embedded_updater(command: str) -> str | None:
    start_marker = 'cat > "$SCRIPT" <<\'NODE\'\n'
    end_marker = "\nNODE\n"
    start = command.find(start_marker)
    if start < 0:
        return None
    start += len(start_marker)
    end = command.find(end_marker, start)
    if end < 0:
        return None
    return command[start:end]

normal = by_name("Launch detached Smart Updater")
recovery = by_name("Launch Smart Updater Recovery Probe")
if normal and recovery:
    normal_script = embedded_updater(str(normal.get("command", "")))
    recovery_script = embedded_updater(str(recovery.get("command", "")))
    if normal_script is None or recovery_script is None:
        fail("Could not extract embedded Smart Updater source from both launcher nodes.")
    elif normal_script != recovery_script:
        fail("Normal Smart Updater and Recovery Probe embed different updater source.")
    else:
        ok("Normal Smart Updater and Recovery Probe embed identical updater source.")
    normal_command = str(normal.get("command", ""))
    recovery_command = str(recovery.get("command", ""))
    normal_launch = next((line.strip() for line in normal_command.splitlines() if line.strip().startswith("nohup node ")), "")
    recovery_launch = next((line.strip() for line in recovery_command.splitlines() if line.strip().startswith("nohup node ")), "")
    if "--recovery-only" not in recovery_launch:
        fail("Recovery Probe launch line is missing --recovery-only.")
    if "--recovery-only" in normal_launch:
        fail("Normal Smart Updater launch line unexpectedly uses --recovery-only.")
    if normal_launch and recovery_launch and "--recovery-only" in recovery_launch and "--recovery-only" not in normal_launch:
        ok("Updater launcher arguments correctly distinguish normal and recovery modes.")


# 5b) Activation/recovery behavioral invariants and uninstall ownership.
readiness_node = ids.get("hpvcreloadreadiness155")
phase_check_node = ids.get("hpvcrecoveryphasecheck155")
phase_guard_node = ids.get("hpvcrecoveryphaseguard155")
pending_guard_node = ids.get("hpvcpendingreloadguard155")
update_eval_node = ids.get("e5bf3761b93e4564")
uninstall_selector = ids.get("f70ac93a57286f3e")
uninstall_defaults = ids.get("2cf211e5923758ad")
accuracy_publish_node = ids.get("411af491012c6308")
report_accuracy_node = ids.get("9bda2984728ce979")

if not all([readiness_node, phase_check_node, phase_guard_node, pending_guard_node, update_eval_node, uninstall_selector, uninstall_defaults, accuracy_publish_node, report_accuracy_node]):
    fail("Smart Update recovery/uninstall validation nodes are incomplete.")
else:
    readiness_source = str(readiness_node.get("command", ""))
    phase_source = str(phase_check_node.get("command", ""))
    phase_guard_source = str(phase_guard_node.get("func", ""))
    pending_source = str(pending_guard_node.get("func", ""))
    update_source = str(update_eval_node.get("func", ""))
    uninstall_source = str(uninstall_selector.get("func", ""))

    parser_source = normal_script or ""
    parser_required = [
        "require.resolve('yaml'",
        "require.resolve('js-yaml'",
        "Node-RED 5 (js-yaml)",
        "strictYamlParser();",
    ]
    missing_parser = [fragment for fragment in parser_required if fragment not in parser_source]
    if missing_parser:
        fail("Smart Updater must have a no-extra-install Node-RED 5 YAML parser fallback and preflight: " + ", ".join(missing_parser))
    parser_preflight = parser_source.find("strictYamlParser();")
    tx_launch = parser_source.find("tx={schema:1,state:'launched'")
    if parser_preflight < 0 or tx_launch < 0 or parser_preflight > tx_launch:
        fail("YAML parser preflight must run before a fresh update transaction is created.")

    updater_hardening_required = [
        "for(const [domain,rawEntries] of Object.entries(block))",
        "function isPreInstallNoChange(tx)",
        "async function reconcilePreInstallNoChange(tx,dir,detail)",
        "pre-install prerequisite/API",
        "input_boolean.hpvc_update_reload_required",
    ]
    missing_updater_hardening = [fragment for fragment in updater_hardening_required if fragment not in parser_source]
    if missing_updater_hardening:
        fail("Smart Updater is missing pre-install/domain-generic hardening: " + ", ".join(missing_updater_hardening))
    if "for(const domain of ['sensor','binary_sensor'])" in parser_source:
        fail("Smart Updater activation inventory is still hard-coded to sensor/binary_sensor template domains.")

    if "phase:'awaiting_quick_reload'" not in (normal_script or ""):
        fail("Smart Updater readiness metadata must start in awaiting_quick_reload phase.")
    # Automatic recovery may resume only after the user-authorized Quick Reload boundary.
    # checking is recoverable only when its exclusive activation lease is no longer fresh.
    required_phase_fragments = [
        "['restart_required','activating','checking','finalizing'].includes(phase)",
        "awaiting_quick_reload is intentionally excluded",
        "activation.lock",
        "lockFresh",
    ]
    if not all(fragment in phase_source for fragment in required_phase_fragments):
        fail("Startup activation recovery must support stale checking/finalizing attempts while preserving the awaiting_quick_reload boundary and live-owner lease.")
    if "hpvc_update_status" in pending_source:
        fail("Pending activation retry guard must not depend on mutable update-status prose.")
    if "states['input_boolean.hpvc_update_reload_required']" in pending_source:
        fail("Pending activation retry guard must not require reload_required; durable transaction metadata is authoritative.")
    stale_reconcile_fragments = [
        "value.reason==='already-finalized'",
        "input_boolean.hpvc_update_reload_required",
        "input_boolean.hpvc_update_in_progress",
        "flow.get('hpvc_update_in_progress')===true",
    ]
    if not all(fragment in phase_guard_source for fragment in stale_reconcile_fragments):
        fail("Finalized activation recovery must reconcile stale HA/Node-RED update latches.")
    orphan_source = str(ids.get("hpvcorphanreconcile156", {}).get("command", ""))
    orphan_finish_source = str(ids.get("hpvcorphanfinish156", {}).get("func", ""))
    orphan_required = [
        "value.reason==='transaction-missing'",
        "managed-v1.6.0-package-not-verified",
        "updater.lock",
        "updater.reclaim.lock",
        "input_boolean.hpvc_update_in_progress",
        "input_boolean.hpvc_update_reload_required",
        "orphan reconciliation verification failed",
    ]
    if not all(fragment in (phase_guard_source + orphan_source) for fragment in orphan_required):
        fail("Missing-transaction orphan activation recovery must be conservative and verified.")
    progress_clear = orphan_source.find("if(progress==='on')await service('input_boolean','turn_off',{entity_id:'input_boolean.hpvc_update_in_progress'})")
    reload_clear = orphan_source.find("if(reload==='on')await service('input_boolean','turn_off',{entity_id:'input_boolean.hpvc_update_reload_required'})")
    if progress_clear < 0 or reload_clear < 0 or progress_clear > reload_clear:
        fail("Orphan activation recovery must clear update_in_progress before the runtime reload_required gate.")
    if not all(fragment in orphan_finish_source for fragment in ["flow.set('hpvc_update_in_progress',false)","flow.set('hpvc_update_started_at',0)","flow.set('hpvc_update_recovery_probe_at',0)","flow.set('hpvc_update_phase','')"]):
        fail("Successful orphan activation recovery must clear Node-RED-local Smart Update latches.")
    readiness_required = [
        "fs.mkdirSync(lockFile,{mode:0o700})",
        "uninitialized locks as live",
        "quarantineStaleLock",
        "crypto.randomUUID()",
        "result.busy=true;result.ignore=true",
        "spec.phase='checking'",
        "spec.phase='activating'",
        "spec.phase='finalizing'",
        "tx.activationComplete=true",
        "tx.activationFinalized=true",
        "hpvc_update_reload_required expected on during activation preparation",
        "Activation preparation acknowledgement failed",
        "Activation finalization acknowledgement failed",
        "currentTx.activationFinalized===true",
        "currentTx.activationComplete===true",
        "beganFinalized=tx.activationFinalized===true",
        "if(tx.activationComplete===true||tx.activationFinalized===true)",
        "tx.activationComplete!==true&&tx.activationFinalized!==true",
        "entity_id:'input_boolean.hpvc_update_in_progress'",
        "hpvc_update_in_progress expected off",
        "currentTx.activationFinalized===true&&!beganFinalized",
    ]
    missing_readiness = [fragment for fragment in readiness_required if fragment not in readiness_source]
    if missing_readiness:
        fail("Activation runner is missing lease/finalization invariants: " + ", ".join(missing_readiness))
    tx_mark = readiness_source.find("tx.activationComplete=true")
    finalized_mark = readiness_source.rfind("tx.activationFinalized=true")
    unlink_mark = readiness_source.rfind("fs.unlinkSync(file)")
    if tx_mark < 0 or finalized_mark < 0 or unlink_mark < 0 or not (tx_mark < finalized_mark < unlink_mark):
        fail("reload-readiness metadata must be deleted only after durable activation completion and finalization acknowledgement.")
    finish_source = str(ids.get("2eb9a6910674ac6d", {}).get("func", ""))
    if "result.busy===true||result.ignore===true" not in finish_source or "Never publish from a delayed result here" not in finish_source:
        fail("Activation finish handler must ignore duplicate/stale attempts and keep delayed failure results side-effect free.")
    local_cleanup_fragments = [
        "flow.set('hpvc_update_in_progress',false)",
        "flow.set('hpvc_update_started_at',0)",
        "flow.set('hpvc_update_recovery_probe_at',0)",
        "flow.set('hpvc_update_phase','')",
    ]
    if not all(fragment in finish_source for fragment in local_cleanup_fragments):
        fail("Successful activation finalization must clear Node-RED-local Smart Update latches.")
    delayed_marker = finish_source.find("Never publish from a delayed result here")
    delayed_tail = finish_source[delayed_marker:] if delayed_marker >= 0 else finish_source
    if "action(" in delayed_tail or "notify(" in delayed_tail or "persistent_notification.create" in delayed_tail:
        fail("Activation finish handler must not publish failure helper/notification state after the lease has been released.")
    safety_source = str(ids.get("bf031913c0a1facd", {}).get("func", ""))
    if "updateActivationPending" not in safety_source or "hpvc_update_reload_required" not in safety_source or "Update activation pending" not in safety_source:
        fail("Normal control must be gated while update activation remains pending.")
    # In the reloadRequired branch routine GitHub checks may update latest/check time,
    # but must not rewrite activation status or clear reload_required.
    reload_branch = re.search(r"if\(reloadRequired\)\{(.*?)\}else if\(relation>0\)", update_source, re.S)
    if not reload_branch:
        fail("Could not inspect pending-activation branch in update availability evaluator.")
    else:
        body = reload_branch.group(1)
        if "hpvc_update_status" in body or "hpvc_update_reload_required" in body:
            fail("Routine release checks must preserve pending activation status/reload state.")
    if not any("activation" in message.lower() for message in errors):
        ok("Smart Update activation recovery is transaction-bound, acknowledged, retryable and idempotent.")

    # Full uninstall must remain an explicit allowlist, but the allowlist must
    # match every HPVC-owned package entity/unique ID exactly. This catches
    # both forgotten future entities and stale deletion permissions.
    package_entities, package_unique_ids = collect_package_ownership(package)
    owned_entities, owned_unique_ids = parse_uninstall_ownership(uninstall_source)
    if owned_entities or owned_unique_ids:
        missing_entities = sorted(package_entities - owned_entities)
        extra_entities = sorted(owned_entities - package_entities)
        missing_unique_ids = sorted(package_unique_ids - owned_unique_ids)
        extra_unique_ids = sorted(owned_unique_ids - package_unique_ids)

        if missing_entities:
            fail("Full uninstall is missing package-owned entity IDs: " + ", ".join(missing_entities))
        if extra_entities:
            fail("Full uninstall has stale/extra entity ownership not defined by the package: " + ", ".join(extra_entities))
        if missing_unique_ids:
            fail("Full uninstall is missing package-owned unique IDs: " + ", ".join(missing_unique_ids))
        if extra_unique_ids:
            fail("Full uninstall has stale/extra unique-ID ownership not defined by the package: " + ", ".join(extra_unique_ids))

        if not (missing_entities or extra_entities or missing_unique_ids or extra_unique_ids):
            ok(
                "Full uninstall ownership exactly matches the package inventory "
                f"({len(package_entities)} entity IDs, {len(package_unique_ids)} unique IDs)."
            )

    # Full uninstall must reset the opt-in Insights helper to the shipped default
    # before deleting helpers, preventing RestoreEntity state from re-enabling it
    # on a later fresh install.
    uninstall_defaults_source = str(uninstall_defaults.get("func", ""))
    turn_off_match = re.search(r"add\('input_boolean\.turn_off',\s*(\[.*?\])\);", uninstall_defaults_source, re.S)
    if not turn_off_match or '"input_boolean.hpvc_insights_enabled"' not in turn_off_match.group(1):
        fail("Full uninstall fresh-install reset must explicitly turn input_boolean.hpvc_insights_enabled off.")
    else:
        ok("Full uninstall resets Enable Insights to the shipped Off default.")

    # Support-report Accuracy must be one coherent publication snapshot. The
    # diagnostics payload carries the headline (ta) together with factors, and
    # the report consumes that same payload instead of independently-aged helpers.
    accuracy_publish_source = str(accuracy_publish_node.get("func", ""))
    report_accuracy_source = str(report_accuracy_node.get("func", ""))
    accuracy_required = [
        "ta: dailyTargetAccuracy",
        "ta: accuracyDiagnostics.ta",
    ]
    missing_accuracy = [fragment for fragment in accuracy_required if fragment not in accuracy_publish_source]
    if missing_accuracy:
        fail("Accuracy diagnostics must preserve the headline in full/reduced report snapshots: " + ", ".join(missing_accuracy))
    if "const targetAccuracy = finite(factors?.ta)" not in report_accuracy_source:
        fail("Support report must source headline Accuracy from the same diagnostics snapshot as its factors.")
    if "num('sensor.hpvc_daily_target_accuracy', null)" in report_accuracy_source and "!accuracySnapshotHasData" not in report_accuracy_source:
        fail("Support report may only fall back to sensor.hpvc_daily_target_accuracy when the diagnostics snapshot is entirely empty.")
    if not missing_accuracy and "const targetAccuracy = finite(factors?.ta)" in report_accuracy_source:
        ok("Support-report Accuracy headline and factors use one coherent diagnostics snapshot.")

    # Automatic Maintenance verification for Action/service adapters requires
    # real numeric readback; the preview warning must flag that before a user
    # starts Smart Update / flow removal / full uninstall.
    package_text = read_text(PACKAGE_PATH)
    maintenance_block = re.search(
        r"- name: HPVC Maintenance Inverter Warning(?P<body>.*?)(?=\n  - name: HPVC HBC Available)",
        package_text,
        re.S,
    )
    if not maintenance_block:
        fail("Could not inspect HPVC Maintenance Inverter Warning template.")
    else:
        maintenance_source = maintenance_block.group("body")
        required_maintenance = [
            "readback not in bad",
            "and is_number(states(readback))",
            "verification_unavailable_inverters:",
        ]
        missing_maintenance = [fragment for fragment in required_maintenance if fragment not in maintenance_source]
        if missing_maintenance:
            fail("Maintenance warning does not fully preview Action/service readback verification requirements: " + ", ".join(missing_maintenance))
        else:
            warning_title = 'title="Maintenance verification unavailable"'
            warning_body = "An inverter is unavailable or cannot be verified at full output."
            warning_night = "If Night Restore already confirmed full output"
            warning_cancel = "and cancel."
            if (
                dashboard_text.count(warning_title) != 2
                or dashboard_text.count(warning_body) != 2
                or dashboard_text.count(warning_night) != 2
                or dashboard_text.count(warning_cancel) < 2
            ):
                fail("Desktop and mobile Maintenance warnings must use the same Night Restore verification wording.")
            else:
                ok("Desktop and mobile Maintenance warnings use the same Night Restore verification wording.")

    # Destructive maintenance must apply the runtime freshness contract to
    # Action/service readback, not just accept a cached numeric state.
    maintenance_watcher_ids = ["eb9674e0d58dc6d1", "6e1516a98c6391ee", "b6d450b56fb931b3"]
    maintenance_freshness_required = [
        "sensor.hpvc_source_freshness",
        "ha_template_last_reported_snapshot",
        "pv${slot}_last_reported_ms",
        "Math.max(0, nowMs - observedMs) > 180000",
        "numericState(liveEntity, slot, method === 'Action/service')",
    ]
    missing_watchers = []
    for watcher_id in maintenance_watcher_ids:
        watcher = ids.get(watcher_id)
        source = str(watcher.get("func", "")) if watcher else ""
        if not source or any(fragment not in source for fragment in maintenance_freshness_required):
            missing_watchers.append(watcher_id)
    if missing_watchers:
        fail("Destructive maintenance watchers do not enforce fresh Action/service readback: " + ", ".join(missing_watchers))
    else:
        ok("All destructive Maintenance paths require fresh Action-service readback.")

    night_restore_maintenance_required = [
        "homePvControlNightRestoreFullConfirmation",
        "configuredInverterUnavailableBlocks",
        "disableRestoreBlocks",
    ]
    missing_night_restore = []
    for watcher_id in maintenance_watcher_ids:
        watcher = ids.get(watcher_id)
        source = str(watcher.get("func", "")) if watcher else ""
        if any(fragment not in source for fragment in night_restore_maintenance_required):
            missing_night_restore.append(watcher_id)
    safety_gate_source = str(ids.get("bf031913c0a1facd", {}).get("func", ""))
    if (
        "homePvControlNightRestoreFullConfirmation" not in safety_gate_source
        or "nightRestoreMaintenanceSignature" not in safety_gate_source
        or "configuredNightInverters.every(inv => nightInverterAtFull(inv, nightFullTolerance))" not in safety_gate_source
        or "nightRestoreFreshPartialObserved" not in safety_gate_source
        or "configuredNightInverters.some(inv => nightInverterVerificationState(inv, nightFullTolerance) === 'partial')" not in safety_gate_source
        or "source !== 'readback'" not in safety_gate_source
        or "readbackValid || source !== 'readback'" not in safety_gate_source
        or "command-cache/startup assumptions" not in safety_gate_source
        or "fixedDataRaw" not in safety_gate_source
        or "targetDataRaw" not in safety_gate_source
        or "valueField" not in safety_gate_source
        or "preActionsRaw" not in safety_gate_source
        or "postActionsRaw" not in safety_gate_source
    ):
        fail("Night Restore does not retain independently verified per-inverter full-output proof for Maintenance.")
    elif missing_night_restore:
        fail("Destructive Maintenance paths do not consume Night Restore full-output proof: " + ", ".join(missing_night_restore))
    else:
        complete_signature_fields = ["valueField", "fixedDataRaw", "targetDataRaw", "preActionsRaw", "postActionsRaw", "actionStep", "refreshSeconds", "minimum"]
        incomplete_signature_watchers = []
        for watcher_id in maintenance_watcher_ids:
            source = str(ids.get(watcher_id, {}).get("func", ""))
            if any(field not in source for field in complete_signature_fields):
                incomplete_signature_watchers.append(watcher_id)
        if incomplete_signature_watchers:
            fail("Maintenance proof signature does not cover complete adapter configuration in: " + ", ".join(incomplete_signature_watchers))
        else:
            ok("Night Restore confirmed-full proof is contradiction-safe and bound to complete adapter configuration.")

    update_guard_source = str(ids.get("247ad595e80b90f3", {}).get("func", ""))
    if "Update not started" not in update_guard_source:
        fail("Smart Update guard does not recognize successful pre-install stop status for fresh retry.")
    else:
        ok("Smart Update guard clears terminal pre-install reconciliation state for a fresh retry.")

    updater_source_text = str(ids.get("04dd6468527f5aad", {}).get("command", ""))
    recovery_pos = updater_source_text.find("if(recoveryOnly)")
    terminal_pos = updater_source_text.find("if(terminal)", recovery_pos)
    nochange_pos = updater_source_text.find("rollbackKind==='pre-install-no-changes'", terminal_pos)
    discover_pos = updater_source_text.find("api=await discoverNr();", terminal_pos)
    if (
        recovery_pos < 0
        or terminal_pos < 0
        or nochange_pos < 0
        or discover_pos < 0
        or nochange_pos > discover_pos
        or "verifyRolledBackTransaction(null,tx,recoveryDir,configPath,dashPath)" not in updater_source_text
        or "Pre-install no-change rollback cannot have deploymentAttempted=true" not in updater_source_text
    ):
        fail("Terminal pre-install/no-change recovery still depends on Node-RED Admin API or lacks no-change verification.")
    else:
        ok("Terminal pre-install/no-change recovery republishes intent before Admin API discovery and keeps activation unnecessary.")

    github_release_node = ids.get("3e6dda88c874e566")
    github_release_source = str(github_release_node.get("command", "")) if github_release_node else ""
    github_timeout_required = [
        "GitHub API overall timeout after 15 s",
        "GitHub API request timeout after 10 s",
        "GitHub API response timeout after 10 s",
    ]
    if not github_release_node or any(fragment not in github_release_source for fragment in github_timeout_required) or str(github_release_node.get("timer", "")) != "20":
        fail("GitHub release lookup must have bounded request/response/overall deadlines and a 20-second Exec limit.")
    else:
        ok("GitHub release lookup is bounded by internal and Exec timeouts.")

# 5c) Multi-inverter degraded configuration policy must isolate slot-local faults.
validation_node = ids.get("5c38544d8b43e7a8")
if not validation_node:
    fail("Missing inverter configuration validation node.")
else:
    source = str(validation_node.get("func", ""))
    required_fragments = [
        "isolatedInverterConfigurationProblems",
        "invalidInverterSlots",
        "isolateInverterConfiguration(inverter, problem)",
        "validConfiguredInverters",
        "No valid inverter configuration remains",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in source]
    if missing:
        fail("Per-inverter configuration isolation is incomplete: " + ", ".join(missing))
    else:
        ok("Slot-local inverter configuration faults are isolated while all-invalid/shared faults remain blocking.")

# 5d) Runtime documentation minimum for Node-RED 5.
for doc_path in [README, ROOT / "docs" / "01-installation.md", CHANGELOG]:
    text = read_text(doc_path)
    if "Node-RED 5.x requires Node.js 22 or newer" in text:
        fail(f"{doc_path.relative_to(ROOT)} still documents Node-RED 5 as Node.js 22+ instead of 22.9.0+.")
if not any("22.9.0" in message for message in errors):
    if "Node-RED 5.x requires Node.js 22.9.0 or newer" in readme_text and "Node-RED 5.x requires Node.js 22.9.0 or newer" in read_text(ROOT / "docs" / "01-installation.md"):
        ok("Node-RED 5 minimum runtime is documented as Node.js 22.9.0+.")

# 5e) CI coverage for v1.6.0 runtime regressions and user-visible documentation.
workflow_text = read_text(ROOT / ".github" / "workflows" / "validate-release.yml")
if "scripts/test_control_runtime_load.py" not in workflow_text:
    fail("GitHub Actions does not run scripts/test_control_runtime_load.py.")
if "node scripts/test_hbc_charge_priority.cjs" not in workflow_text:
    fail("GitHub Actions does not run scripts/test_hbc_charge_priority.cjs.")
if "node scripts/test_report_generation.cjs" not in workflow_text:
    fail("GitHub Actions does not run scripts/test_report_generation.cjs.")
else:
    ok("GitHub Actions runs the issue #9 runtime-load regression test.")

installation_text = read_text(ROOT / "docs" / "01-installation.md")
how_it_works_text = read_text(ROOT / "docs" / "03-how-it-works.md")
troubleshooting_text = read_text(ROOT / "docs" / "04-troubleshooting.md")
if "180 seconds" not in installation_text or "Night Restore" not in installation_text:
    fail("Installation docs are missing the Maintenance inverter-warning / 180-second safe-cancel behavior.")
elif "60 seconds" not in how_it_works_text or "View report" not in how_it_works_text or "60 seconds" not in troubleshooting_text:
    fail("Docs are missing the 60-second View report → Generate report fallback behavior.")
else:
    ok("Maintenance inverter warning and report Ready-state fallback are documented.")

footer_placement_checks = [
    (ROOT / "docs" / "01-installation.md", "Nighttime Maintenance can use a full-output confirmation", "## Next steps"),
    (ROOT / "docs" / "03-how-it-works.md", "### Maintenance readback freshness", "## Next steps"),
    (ROOT / "docs" / "04-troubleshooting.md", "### Maintenance waits even though the readback still shows 100%", "[← README]"),
]
misplaced = []
for path, section_marker, footer_marker in footer_placement_checks:
    doc = path.read_text(encoding="utf-8")
    section_pos = doc.find(section_marker)
    footer_pos = doc.rfind(footer_marker) if path.name == "04-troubleshooting.md" else doc.find(footer_marker)
    if section_pos < 0 or footer_pos < 0 or section_pos > footer_pos:
        misplaced.append(path.name)
if misplaced:
    fail("Night Restore Maintenance documentation is misplaced after footer/navigation in: " + ", ".join(misplaced))
else:
    ok("Night Restore Maintenance documentation is placed before footer/navigation.")


# 5f) GitHub repository readiness.
workflow_path = ROOT / ".github" / "workflows" / "validate-release.yml"
required_repo_files = [
    ROOT / "README.md",
    ROOT / "LICENSE",
    ROOT / ".gitignore",
    workflow_path,
]
missing_repo_files = [str(path.relative_to(ROOT)) for path in required_repo_files if not path.is_file()]
if missing_repo_files:
    fail("GitHub-ready repository files are missing: " + ", ".join(missing_repo_files))
else:
    workflow_text = read_text(workflow_path)
    required_workflow_fragments = [
        "actions/checkout@v7",
        "actions/setup-python@v7",
        "actions/setup-node@v7",
        "python scripts/validate_release.py",
        "python scripts/test_activation_recovery.py",
        "python scripts/test_insights_mode.py",
        "python scripts/test_control_runtime_load.py",
        "node scripts/test_control_baselines.cjs",
        "node scripts/test_control_safety.cjs",
        "node scripts/test_dispatch_lifecycle.cjs",
        "permissions:",
        "contents: read",
    ]
    missing_workflow = [fragment for fragment in required_workflow_fragments if fragment not in workflow_text]
    if missing_workflow:
        fail("GitHub Actions workflow is incomplete: " + ", ".join(missing_workflow))
    else:
        ok("GitHub Actions workflow and core repository files are present.")

# Validate repository-local Markdown links and images.
bad_links = []
md_target_re = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
for md_path in ROOT.rglob("*.md"):
    text = read_text(md_path)
    for match in md_target_re.finditer(text):
        raw_target = match.group(1).strip()
        if raw_target.startswith("<") and raw_target.endswith(">"):
            raw_target = raw_target[1:-1]
        raw_target = raw_target.split(" \"", 1)[0].split(" '", 1)[0].strip()
        if raw_target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path_part = unquote(raw_target.split("#", 1)[0])
        if not path_part:
            continue
        target = (md_path.parent / path_part).resolve()
        try:
            target.relative_to(ROOT.resolve())
        except ValueError:
            bad_links.append(f"{md_path.relative_to(ROOT)} -> {raw_target} (outside repository)")
            continue
        if not target.exists():
            bad_links.append(f"{md_path.relative_to(ROOT)} -> {raw_target}")
if bad_links:
    fail("Broken local Markdown links/images: " + "; ".join(bad_links[:10]))
else:
    ok("Local Markdown links and images resolve inside the repository.")

# Troubleshooting follows the same GitHub rendering structure as the other docs.
troubleshooting_text = read_text(ROOT / "docs" / "04-troubleshooting.md")
nonblank_lines = [line for line in troubleshooting_text.splitlines() if line.strip()]
first_nonblank = nonblank_lines[0] if nonblank_lines else ""
title_match = re.search(r"(?m)^# Troubleshooting\s*$", troubleshooting_text)
smart_update_match = re.search(r"(?m)^## Smart Update troubleshooting\s*$", troubleshooting_text)
maintenance_match = re.search(r"(?m)^### Maintenance waits even though the readback still shows 100%\s*$", troubleshooting_text)
bottom_nav_pos = troubleshooting_text.rfind("[← README]")
if (
    not first_nonblank.startswith("[← README]")
    or title_match is None
    or smart_update_match is None
    or maintenance_match is None
    or bottom_nav_pos <= maintenance_match.start()
    or not (title_match.start() < smart_update_match.start() < maintenance_match.start())
):
    fail("Troubleshooting document structure is invalid for GitHub rendering.")
else:
    ok("Troubleshooting document structure is GitHub-ready.")


# Current markers and the behavior suites must travel with this release.
for script in ["control_test_runtime.cjs", "test_control_baselines.cjs", "test_control_safety.cjs", "test_dispatch_lifecycle.cjs", "test_enphase_registry.cjs"]:
    if not (ROOT / "scripts" / script).is_file():
        fail(f"Missing behavioral control test artifact: {script}")
if "node scripts/test_enphase_registry.cjs" not in read_text(ROOT / ".github" / "workflows" / "validate-release.yml"):
    fail("GitHub Actions must run registry discovery/controller opt-out regressions.")
for node_id in ["e5bf3761b93e4564", "b4240d9c874b05aa", "411af491012c6308", "hpvcorphanreconcile156"]:
    source = str(ids.get(node_id, {}).get("func", "")) + str(ids.get(node_id, {}).get("command", ""))
    if VERSION not in source and VERSION.replace(".", "\\.") not in source:
        fail(f"Current version marker missing from node {node_id}")
if not any("behavioral control" in err for err in errors):
    ok("Behavioral control suites and current runtime/report version markers are present.")

# 6) Guard release-note date consistency.
def release_date(text: str) -> str | None:
    m = re.search(r"^\*\*Release date:\*\*\s+(\d{4}-\d{2}-\d{2})\s*$", text, re.M)
    return m.group(1) if m else None

note_date = release_date(release_notes_text)
changelog_match = re.search(rf"^## v{re.escape(VERSION)}\s+[—-]\s+(\d{{4}}-\d{{2}}-\d{{2}})\s*$", changelog_text, re.M)
change_date = changelog_match.group(1) if changelog_match else None
if not note_date:
    fail("RELEASE_NOTES.md is missing a release date.")
elif note_date != change_date:
    fail(f"Release date mismatch: RELEASE_NOTES={note_date}, CHANGELOG={change_date}.")
else:
    ok(f"Release date is consistent: {note_date}.")

print(f"HPVC release validation for v{VERSION}")
for message in notes:
    print(f"  PASS  {message}")
for message in skipped:
    print(f"  SKIP  {message}")
if errors:
    for message in errors:
        print(f"  FAIL  {message}", file=sys.stderr)
    print(f"Validation failed with {len(errors)} error(s); {len(notes)} checks passed, {len(skipped)} skipped.", file=sys.stderr)
    sys.exit(1)
print(f"Validation passed ({len(notes)} checks executed, {len(skipped)} skipped).")
