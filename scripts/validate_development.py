"""Validate v2 development identity separately from preserved v1.6 release records."""
from pathlib import Path
import ast,json,re
ROOT=Path(__file__).resolve().parents[1]
meta=json.loads((ROOT/'DEVELOPMENT.json').read_text(encoding='utf-8'))
manifest=json.loads((ROOT/'custom_components/hpvc/manifest.json').read_text(encoding='utf-8'))
const=(ROOT/'custom_components/hpvc/const.py').read_text(encoding='utf-8')
assert meta['version']==manifest['version'] and meta['version'] in const
assert meta['production_transport_authorized'] is False and meta['release'] is False
assert meta['legacy_reference']=='1.6.0'
assert '# Home PV Control v1.6.0' in (ROOT/'RELEASE_NOTES.md').read_text(encoding='utf-8')
assert (ROOT/'releases/v1.6.0/release.md').is_file()
src=(ROOT/'custom_components/hpvc/execution/ha_executor.py').read_text(encoding='utf-8')
f=next(n for n in ast.parse(src).body if isinstance(n,ast.FunctionDef) and n.name=='production_transport_admitted')
assert isinstance(f.body[-1],ast.Return) and isinstance(f.body[-1].value,ast.Constant) and f.body[-1].value.value is False
assert (ROOT/'migration/legacy-bridge-v1.6.cjs').is_file()
assert (ROOT/'home assistant/hpvc_native_dashboard.json').is_file()
print('Development metadata validated:',meta['version'],'; historical v1.6.0 reference retained; production admission closed')
