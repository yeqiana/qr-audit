"""qr-audit unified CLI: baseline scan, read-only source hints, evidence analysis."""
import argparse
import json
import sys
from pathlib import Path

import audit_source
import analyze_contributions
import build_report_models
import scan_images
import validate_evidence


def json_print(payload):print(json.dumps(payload,ensure_ascii=False,indent=2))

def main():
    p=argparse.ArgumentParser(description='qr-audit 统一入口：scan / audit / contribution / all')
    sub=p.add_subparsers(dest='mode',required=True)
    for name in ('scan','all'):
        s=sub.add_parser(name,help='实际离线 V01–V03 基线扫码并生成 MD/HTML；all 另做源码候选审计')
        s.add_argument('--input-root',required=True)
        s.add_argument('--report-root',required=True)
        s.add_argument('--workspace-root')
        s.add_argument('--decoder',action='append',choices=['opencv','zxingcpp'])
        s.add_argument('--left-name',default='WAVES_QR')
        s.add_argument('--right-name',default='WAVES_QR_RAW')
        s.add_argument('--max-pixels',type=int,default=50000000)
        s.add_argument('--source-root',help='all 模式只读检索源码候选位置')
    a=sub.add_parser('audit',help='源码候选审计（不是自动确认）')
    a.add_argument('--source-root',required=True)
    a.add_argument('--output',required=True)
    c=sub.add_parser('contribution',help='分析已有完整 28 策略实验 attempts，不会自动执行未对接策略')
    c.add_argument('--manifest',required=True)
    c.add_argument('--attempts',required=True)
    c.add_argument('--out-dir',required=True)
    c.add_argument('--registry',default=str(Path(__file__).resolve().parents[1]/'assets'/'strategy-registry.initial.json'))
    args=p.parse_args()
    try:
        if args.mode=='audit':
            outcome=audit_source.analyze(args.source_root)
            path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('x',encoding='utf-8') as f:json.dump(outcome,f,ensure_ascii=False,indent=2)
            json_print({'status':'HINT_ONLY','source_files':outcome['files_scanned'],'hits':len(outcome['source_hints']),'file':str(path)});return 0
        if args.mode=='contribution':
            manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
            attempts=validate_evidence.load_jsonl(args.attempts)
            registry=json.loads(Path(args.registry).read_text(encoding='utf-8'))
            check=validate_evidence.validate(manifest,attempts,registry)
            if check['status']!='PASS':
                json_print({'status':'BLOCKED_INCOMPLETE_EXPERIMENT','check':check});return 3
            result=analyze_contributions.analyze(manifest,attempts,registry)
            if not result['contribution_metrics_valid']:
                json_print({'status':'BLOCKED_INCOMPLETE_EXPERIMENT','reasons':result['incomplete_reasons']});return 3
            out=Path(args.out_dir)
            out.mkdir(parents=True,exist_ok=True)
            targets=[out/'contribution-summary.json',out/'strategy-contribution.csv',out/'strategy-group-removal-loss.csv',out/'strategy-contribution-by-scope.csv']
            if any(x.exists() for x in targets):raise FileExistsError('贡献度文件已存在，拒绝覆盖')
            targets[0].write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            analyze_contributions.write_csv(targets[1],result['strategy_metrics'])
            analyze_contributions.write_csv(targets[2],result['group_removal_loss'])
            analyze_contributions.write_csv(targets[3],result['strategy_metrics_by_scope'])
            json_print({'status':'PASS','images':result['image_count'],'success_images':result['all_success_images'],'out_dir':str(out)});return 0
        run=scan_images.run_scan(args.input_root,args.report_root,args.workspace_root,args.decoder,args.max_pixels,args.left_name,args.right_name)
        evidence=Path(run['evidence'])
        manifest=json.loads((evidence/'run-manifest.json').read_text(encoding='utf-8'))
        attempts=validate_evidence.load_jsonl(evidence/'attempts.jsonl')
        check=validate_evidence.validate(manifest,attempts)
        if check['status']!='PASS':
            json_print({'status':'BLOCKED_EVIDENCE_INVALID','run_root':run['run_root'],'errors':check['errors']});return 3
        models=build_report_models.build(run['run_root'])
        info={'status':'PASS_BASELINE_ONLY','run_root':run['run_root'],
              'groups':len(models),'reports_per_group':3,'image_count':run['image_count'],
              'decoded_images':run['decoded_images'],
              'note':'仅 V01–V03 内置参考实现。V04–V28 未执行，完整策略贡献度仍需要对接用户现有扫码源码。'}
        if args.mode=='all':
            if args.source_root:
                audit=audit_source.analyze(args.source_root)
                (evidence/'audit-hints.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
                info['source_audit']='HINT_ONLY';info['audit_hits']=len(audit['source_hints'])
            info['full_contribution']='BLOCKED_NOT_CONNECTED_TO_28_IMPLEMENTATIONS'
        json_print(info);return 0
    except Exception as exc:
        json_print({'status':'BLOCKED','error':str(exc)});return 2

if __name__=='__main__':raise SystemExit(main())