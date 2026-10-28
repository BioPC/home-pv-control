"""Generate a reviewable native dashboard; never installs or edits a live dashboard."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from custom_components.hpvc.migration.dashboard import native_dashboard
from custom_components.hpvc.dashboard.builder import parity_dashboard
from custom_components.hpvc.control.models import PlantConfiguration
from custom_components.hpvc.storage import HistoryState

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mapping',type=Path)
    p.add_argument('--configuration',type=Path)
    p.add_argument('--history',type=Path)
    p.add_argument('--compatibility-layout',action='store_true',help='Retain the historical dev.7 export layout; default is v1.6-style native parity')
    p.add_argument('--output',type=Path,default=ROOT/'home assistant/hpvc_native_dashboard.json')
    a=p.parse_args()
    if not a.compatibility_layout and (a.configuration or a.history):
        p.error('Configuration/history exports require --compatibility-layout; parity binds live native configuration')
    def read(path):return json.loads(path.read_text(encoding='utf-8')) if path else None
    mapping=read(a.mapping) or {}
    cfg=PlantConfiguration.from_dict(read(a.configuration)) if a.configuration else None
    history=HistoryState.from_dict(read(a.history)) if a.history else None
    result=native_dashboard(mapping,cfg,history) if a.compatibility_layout else parity_dashboard(mapping)
    a.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('Native dashboard artifact:',a.output)
if __name__=='__main__':main()
