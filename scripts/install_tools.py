"""Copy self-contained helper scripts into a new, versioned workspace directory."""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

VERSION='1.1.0'
SCRIPTS=['run.py','inventory_images.py','scan_images.py','executor_registry.py','evidence_contract.py',
         'build_report_models.py','render_reports.py','analyze_contributions.py','validate_evidence.py','audit_source.py']
ASSETS=['strategy-registry.initial.json']

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def install(workspace):
    root=Path(__file__).resolve().parents[1]
    space=Path(workspace).expanduser().resolve()
    if not space.is_dir():raise ValueError('workspace 不存在')
    target=space/'qr-tools'/f'qr-audit-v{VERSION}'
    if target.exists():raise FileExistsError('拒绝覆盖已有工具目录: '+str(target))
    stage=target.with_name(target.name+'.stage')
    if stage.exists():raise FileExistsError('发现之前的未完成 stage，请人工检查: '+str(stage))
    stage.mkdir(parents=True)
    (stage/'scripts').mkdir();(stage/'assets').mkdir()
    hashes=[]
    for name in SCRIPTS:
        src=root/'scripts'/name;dst=stage/'scripts'/name;shutil.copy2(src,dst)
        hashes.append({'path':'scripts/'+name,'sha256':sha(dst)})
    for name in ASSETS:
        src=root/'assets'/name;dst=stage/'assets'/name;shutil.copy2(src,dst)
        hashes.append({'path':'assets/'+name,'sha256':sha(dst)})
    (stage/'bundle-manifest.json').write_text(json.dumps({'version':VERSION,'files':hashes},ensure_ascii=False,indent=2),encoding='utf-8')
    target.parent.mkdir(parents=True,exist_ok=True)
    stage.rename(target)
    return {'status':'INSTALLED','path':str(target),'files':len(hashes)}

def main():
    p=argparse.ArgumentParser(description='将 qr-audit 辅助工具安装到业务工作区的 qr-tools/qr-audit-v1.1.0/')
    p.add_argument('--workspace',required=True);a=p.parse_args()
    try:print(json.dumps(install(a.workspace),ensure_ascii=False));return 0
    except Exception as exc:print(json.dumps({'status':'ERROR','error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
