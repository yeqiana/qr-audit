import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REQUIRED=['SKILL.md','README.md','assets/strategy-registry.initial.json',
          'scripts/run.py','scripts/inventory_images.py','scripts/scan_images.py','scripts/build_report_models.py',
          'scripts/render_reports.py','scripts/analyze_contributions.py','scripts/validate_evidence.py',
          'scripts/audit_source.py','scripts/install_tools.py','tests/test_tools.py']

def check():
    missing=[p for p in REQUIRED if not (ROOT/p).is_file()]
    registry=json.loads((ROOT/REQUIRED[2]).read_text(encoding='utf-8'))
    ids=[v['strategy_id'] for v in registry['strategies']]
    header=(ROOT/'SKILL.md').read_text(encoding='utf-8').splitlines()[:4]
    errors=[]
    if missing:errors.append('缺少文件: '+str(missing))
    if ids!=[f'V{i:02d}' for i in range(1,29)]:errors.append('28 策略编号错误')
    if 'name: qr-audit' not in header:errors.append('SKILL 名称不是 qr-audit')
    if any('qr-offline-scan-audit' in p.read_text(encoding='utf-8') for p in ROOT.rglob('*.md')):
        errors.append('残留旧 Skill 名称')
    return {'status':'PASS' if not errors else 'FAIL','errors':errors,'strategy_count':len(ids)}

if __name__=='__main__':
    result=check();print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['status']=='PASS' else 1)