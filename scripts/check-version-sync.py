#!/usr/bin/env python3
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

def ver_tuple(name):
    m = SEMVER.match(name)
    return tuple(map(int, m.groups())) if m else None

release_dirs = []
for p in (ROOT / "releases").iterdir():
    if p.is_dir() and ver_tuple(p.name):
        release_dirs.append((ver_tuple(p.name), p.name))
if not release_dirs:
    raise SystemExit("No versioned release directories found")
expected = max(release_dirs)[1].lstrip("v")
tag = "v" + expected
errors = []

def require(path, pattern, label, flags=0):
    text = (ROOT / path).read_text(encoding="utf-8")
    if not re.search(pattern, text, flags):
        errors.append(f"{path}: missing {label} for {expected}")

require("home assistant/hpvc_config.yaml", rf"unique_id:\s*hpvc_installed_version[\s\S]{{0,300}}state:\s*['\"]?{re.escape(expected)}['\"]?", "installed-version sensor")
require("home assistant/hpvc_dashboard.yaml", rf"Home PV Control \(v{re.escape(expected)}\)", "dashboard version")
flow = json.loads((ROOT / "node-red/hpvc_flow.json").read_text(encoding="utf-8"))
labels = {str(n.get("label", "")) for n in flow if n.get("type") == "tab"}
for part in ("Inputs", "Engine", "Outputs", "Reports"):
    label = f"HPVC {part} v{expected}"
    if label not in labels:
        errors.append(f"node-red/hpvc_flow.json: missing tab {label}")
require("CHANGELOG.md", rf"^## v{re.escape(expected)}(?:\s|$)", "latest changelog heading", re.M)
require("RELEASE_NOTES.md", rf"v{re.escape(expected)}", "release-notes version")
if not (ROOT / f"releases/{tag}/release.md").exists():
    errors.append(f"Missing releases/{tag}/release.md")

if errors:
    print("Version consistency check FAILED:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print(f"Version consistency check passed for v{expected}")
