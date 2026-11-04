"""Transform real evidence into 3 reports/group, then use the same model for MD+HTML."""
import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
from render_reports import render


def read_json(p):return json.loads(Path(p).read_text(encoding='utf-8'))

def attempts_jsonl(p):return [json.loads(x) for x in Path(p).read_text(encoding='utf-8').splitlines() if x.strip()]

def safe_dir(name):
    import re
    value=re.sub(r'[\\/:*?"<>|\x00-\x1f]', '-',name).strip(' .')
    return value[:100] or 'group'

def summary_status(records):
    decoded=[r for r in records if r.get('status')=='DECODED']
    vals={str(r.get('payload_sha256') or r.get('payload')) for r in decoded}
    if len(vals)>1: return 'PAYLOAD_CONFLICT'
    if decoded:return 'DECODED'
    if any(r.get('status')=='DETECTED_ONLY' for r in records):return 'DETECTED_ONLY'
    if any(r.get('status')=='ERROR' for r in records):return 'ERROR'
    if any(r.get('status')=='NO_DECODE' for r in records):return 'NO_DECODE'
    return 'NOT_RUN'

def result_for_file(file_id,attempts):
    records=attempts.get(file_id,[])
    status=summary_status(records)
    successes=[r for r in records if r.get('status')=='DECODED']
    value=successes[0].get('payload','') if successes else ''
    attempted=[r for r in records if r.get('status') in ('DECODED','DETECTED_ONLY','NO_DECODE','ERROR')]
    return {'file_id':file_id,'status':status,'payload':value,
            'strategy':', '.join(sorted({x['strategy_id'] for x in successes})),
            'decoder':', '.join(sorted({x['decoder_id'] for x in successes})),
            'attempts':len(attempted),'skipped':len(records)-len(attempted),
            'duration_ms':round(sum(float(x.get('duration_ms',0)) for x in attempted),2),
            'review':status not in ('DECODED',)}

def report_model(inventory,manifest,attempts):
    by_img=defaultdict(list)
    for a in attempts:by_img[a['image_id']].append(a)
    output=[];now=datetime.now(timezone.utc).isoformat()
    all_count=len(manifest.get('strategy_order',[]))
    for group in inventory['groups']:
        name=group['group_name'];sid=group['group_id'];sides=group['sides']
        # A missing side is represented in inventory, not silently omitted.
        if len(sides)==1 and sides[0]['side_id']=='SINGLE':
            side_names=['SINGLE',inventory['right_directory']]
            sides += [{'side_id':inventory['right_directory'],'directory_present':False,'files':[],'image_count':0}]
        else: side_names=[inventory['left_directory'],inventory['right_directory']]
        by_side={s['side_id']:s for s in sides}
        files={f['file_id']:f for s in sides for f in s['files']}
        result={fid:result_for_file(fid,by_img) for fid in files}
        reports=[]
        for i,side_name in enumerate(side_names,1):
            side=by_side.get(side_name,{'side_id':side_name,'directory_present':False,'files':[],'image_count':0})
            rows=[];counts=defaultdict(int)
            for f in side['files']:
                r=result[f['file_id']];counts[r['status']]+=1
                rows.append([f['relative_path'],r['status'],r['strategy'],r['decoder'],
                             {'text':r['payload'],'code':True},str(r['duration_ms'])])
            reports.append({
                'file_stem':f'{i}. {name}-{side_name}-扫描结果',
                'title':f'{name} / {side_name} 扫描结果',
                'generated_at':now,'status':'PARTIAL' if counts['NOT_RUN'] or not side['directory_present'] else 'COMPLETE',
                'metrics':[
                    {'label':'目录存在','value':str(bool(side['directory_present']))},
                    {'label':'图片文件数','value':len(side['files'])},
                    {'label':'策略定义数','value':all_count},
                    {'label':'实际执行次数','value':sum(result[f['file_id']]['attempts'] for f in side['files'])},
                    {'label':'离线解码成功','value':counts['DECODED']},
                    {'label':'候选检测','value':counts['DETECTED_ONLY']},
                    {'label':'待人工复核','value':sum(result[f['file_id']]['review'] for f in side['files'])}
                ],
                'sections':[
                    {'type':'paragraph','text':f"run_id={manifest['run_id']}；目录侧={side_name}；微信 App 实扫：NOT_TESTED；业务可用性：NOT_VERIFIED。"},
                    {'type':'table','title':'扫描明细','headers':['目录/图片名称','离线状态','成功策略','解码器','载荷','实际执行耗时(ms)'],'rows':rows},
                    {'type':'paragraph','text':'目录未发现。' if not side['directory_present'] else '表中的 DECODED 仅表示离线解码成功。原图和历史结果均未修改。'},
                ]})
        left_name,right_name=side_names
        paired=[];stats=defaultdict(int)
        for pair in group['pairs']:
            left_ids=pair.get('left_file_ids',[])
            right_ids=pair.get('right_file_ids',[])
            lf=[files[fid]['relative_path'] for fid in left_ids if fid in files]
            rf=[files[fid]['relative_path'] for fid in right_ids if fid in files]
            left_results=[result[fid] for fid in left_ids if fid in result]
            right_results=[result[fid] for fid in right_ids if fid in result]
            ls=' / '.join(x['status'] for x in left_results) or 'MISSING'
            rs=' / '.join(x['status'] for x in right_results) or 'MISSING'
            successes=[x for x in left_results+right_results if x['status'] in ('DECODED','PAYLOAD_CONFLICT')]
            ok=bool(successes)
            payloads={str(x['payload']) for x in successes}
            conflict=len(payloads)>1 or any(x['status']=='PAYLOAD_CONFLICT' for x in left_results+right_results)
            review=conflict or not ok or pair['pair_status']!='PAIRED'
            if ok:stats['any_success']+=1
            if conflict:stats['payload_conflicts']+=1
            if review:stats['review']+=1
            if pair['pair_status']!='PAIRED':stats['unpaired']+=1
            paired.append([pair['pair_key'],pair['pair_status'],
                           ', '.join(lf) or 'MISSING',ls,
                           ', '.join(rf) or 'MISSING',rs,
                           '✓' if ok else '✗','PAYLOAD_CONFLICT' if conflict else ('SAME' if len(successes)>1 else 'NOT_COMPARABLE'),
                           '是' if review else '否'])
        reports.append({
            'file_stem':f'3. {name}-二维码-总扫描结果',
            'title':f'{name} / 二维码配对总扫描结果',
            'generated_at':now,'status':'PARTIAL' if stats['review'] else 'COMPLETE',
            'metrics':[
                {'label':'图片文件总数','value':group['stats']['image_file_count']},
                {'label':'配对数','value':group['stats']['pair_count']},
                {'label':'任一目录解码通过','value':stats['any_success']},
                {'label':'未配对条目','value':stats['unpaired']},
                {'label':'载荷冲突数','value':stats['payload_conflicts']},
                {'label':'待人工复核','value':stats['review']}],
            'sections':[
                {'type':'paragraph','text':f"run_id={manifest['run_id']}；任一侧离线 DECODED 则打 ✓；两侧载荷不同另标冲突。微信实扫 NOT_TESTED，业务有效性 NOT_VERIFIED。"},
                {'type':'table','title':'配对明细','headers':['配对键','配对情况',f'{left_name} 图片',f'{left_name} 状态',f'{right_name} 图片',f'{right_name} 状态','任一目录离线解码','载荷一致性','人工复核'],'rows':paired},
            ]})
        output.append({'group_id':sid,'group_name':name,'reports':reports,'metrics':dict(stats)})
    return output


def build(run_root):
    run_root=Path(run_root).resolve();evidence=run_root/'evidence'
    inv=read_json(evidence/'inventory.json');manifest=read_json(evidence/'run-manifest.json')
    attempts=attempts_jsonl(evidence/'attempts.jsonl')
    all_models=report_model(inv,manifest,attempts)
    summary=[]
    for number,group in enumerate(all_models,1):
        group_dir=run_root/(f'{number:02d}-'+safe_dir(group['group_name']))
        group_dir.mkdir(exist_ok=False)
        model_file=group_dir/'report-model.json'
        model_file.write_text(json.dumps({'schema_version':'1.0','reports':group['reports']},ensure_ascii=False,indent=2),encoding='utf-8')
        rendered=render(model_file,group_dir)
        summary.append({'group':group['group_name'],'path':str(group_dir),'documents':len(rendered),'metrics':group['metrics']})
    # Same structured renderer is used for overview, also a paired MD/HTML.
    overview={'schema_version':'1.0','reports':[
        {'file_stem':'0. 扫描总览','title':'二维码离线扫描总览',
         'status':'PARTIAL','generated_at':datetime.now(timezone.utc).isoformat(),
         'metrics':[{'label':'图片组数','value':len(summary)},
                    {'label':'输入文件数','value':len(manifest['images'])},
                    {'label':'策略注册数','value':len(manifest['strategy_order'])},
                    {'label':'本次尝试记录数','value':len(attempts)}],
         'sections':[{'type':'paragraph','text':'本次扫描严格离线；微信实扫 NOT_TESTED；业务有效性 NOT_VERIFIED。内置参考扫描器只执行 V01–V03，余下策略待源码对齐。'},
                     {'type':'table','title':'各组报告','headers':['图片组','报告目录','报告数量'],
                      'rows':[[s['group'],s['path'],s['documents']] for s in summary]}]}]}
    overview_file=run_root/'overview-model.json'
    overview_file.write_text(json.dumps(overview,ensure_ascii=False,indent=2),encoding='utf-8')
    render(overview_file,run_root)
    return summary


def main():
    p=argparse.ArgumentParser(description='根据 inventory、manifest、attempts 生成每组3份 MD + 3份 HTML')
    p.add_argument('--run-root',required=True)
    a=p.parse_args()
    try:
        summary=build(a.run_root)
        print(json.dumps({'status':'PASS','groups':len(summary),'reports_per_group':3},ensure_ascii=False));return 0
    except Exception as exc:
        print(json.dumps({'status':'ERROR','error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
