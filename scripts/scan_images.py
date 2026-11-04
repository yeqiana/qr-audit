"""Offline baseline scan (V01-V03) with optional local cv2/zxingcpp adapters.

The other 25 user-defined variants are deliberately NOT reimplemented here:
exact existing implementation and parameters are unavailable until source audit.
"""
import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from inventory_images import build_inventory, sha256_file


def utc_now(): return datetime.now(timezone.utc).isoformat()

def get_library(name):
    try:
        return importlib.import_module(name)
    except ImportError as ex:
        raise RuntimeError(f'本地解码依赖缺失: {name}；不联网安装，请预先安装或复用项目扫描器') from ex


def git_fingerprint(root):
    try:
        rev=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,text=True,timeout=5)
        dirty=subprocess.run(['git','-C',str(root),'status','--porcelain'],capture_output=True,text=True,timeout=5)
        return {'git_commit':rev.stdout.strip() if rev.returncode==0 else 'NOT_A_GIT_REPOSITORY',
                'git_dirty':bool(dirty.stdout.strip()) if dirty.returncode==0 else None}
    except (OSError,subprocess.TimeoutExpired):
        return {'git_commit':'NOT_VERIFIED','git_dirty':None}


def load_image(path,cv2,np):
    # IMREAD_UNCHANGED and PIL fallback support unicode Windows paths and GIF first frame.
    buffer=np.fromfile(str(path),dtype=np.uint8)
    img=cv2.imdecode(buffer,cv2.IMREAD_COLOR)
    if img is None:
        from PIL import Image
        with Image.open(path) as p:
            rgb=np.asarray(p.convert('RGB'))
        img=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
    return img


def preprocessing(img,strategy_id,cv2):
    if strategy_id=='V01':return img
    if strategy_id=='V02':return cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    if strategy_id=='V03':
        gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
        # Transparent reference only. NOT claimed equal to user's existing auto contrast.
        return cv2.normalize(gray,None,alpha=0,beta=255,norm_type=cv2.NORM_MINMAX)
    raise NotImplementedError(f'{strategy_id} 需与现有源码对齐后方可实现')


def decode_cv2(img,cv2):
    detector=cv2.QRCodeDetector()
    candidates=0; texts=[]
    try:
        ok, decoded, points, _=detector.detectAndDecodeMulti(img)
        if points is not None: candidates=len(points)
        if ok and decoded: texts=[str(x) for x in decoded if x]
    except Exception:
        pass
    if not texts:
        text,points,_=detector.detectAndDecode(img)
        if points is not None:candidates=max(candidates,1)
        if text:texts=[str(text)]
    return texts,candidates


def decode_zxing(img,zxingcpp):
    results=zxingcpp.read_barcodes(img)
    texts=[]
    for result in results:
        fmt=str(getattr(result,'format','')).lower()
        if 'qr' in fmt:
            text=getattr(result,'text','')
            if text:texts.append(str(text))
    return texts,len(results)


def make_manifest(run_id,inventory,root,registry,lib_versions,decoders):
    images=[]
    for group in inventory['groups']:
        for side in group['sides']:
            for f in side['files']:
                images.append({'image_id':f['file_id'],'group_id':group['group_id'],
                               'side_id':side['side_id'],'path':f['absolute_path'],
                               'relative_path':f['relative_path'],'sha256':f.get('sha256')})
    pair_keys={}
    for group in inventory['groups']:
        for pair in group['pairs']:
            for file_id in pair.get('left_file_ids', [])+pair.get('right_file_ids', []):
                pair_keys[file_id]=pair['pair_key']
    for item in images:
        item['pair_key']=pair_keys.get(item['image_id'])
    return {'schema_version':'1.0','run_id':run_id,'mode':'scan','started_at':utc_now(),
            'input_root':inventory['input_root'],'inventory_sha256':None,
            'strategy_registry_sha256':sha256_file(registry),
            'source_fingerprint':git_fingerprint(root),
            'dependencies':[{'name':k,'version':v} for k,v in lib_versions.items()],
            'strategy_order':[f'V{i:02d}' for i in range(1,29)],
            'strategies':[{'strategy_id':f'V{i:02d}'} for i in range(1,29)],
            'decoders':[{'decoder_id':d} for d in decoders], 'images':images,
            'baseline_implementation_note':'内置扫描器仅执行 V01–V03 参考实现；V04–V28 为 NOT_RUN，不能声称完整执行28策略。',
            'wechat_scan_status':'NOT_TESTED','business_validity':'NOT_VERIFIED'}


def run_scan(input_root,report_root,workspace_root=None,decoders=None,max_pixels=50000000,left_name='WAVES_QR',right_name='WAVES_QR_RAW'):
    input_root=Path(input_root).expanduser().resolve()
    report_root=Path(report_root).expanduser().resolve()
    workspace_root=Path(workspace_root).expanduser().resolve() if workspace_root else input_root.parent
    if not input_root.is_dir():raise ValueError('input_root 不存在')
    # all dependencies imported before creating run output directory
    cv2=get_library('cv2');np=get_library('numpy')
    decoders=decoders or ['opencv']
    libs={'opencv':cv2.__version__,'numpy':np.__version__}
    zxing=None
    if 'zxingcpp' in decoders:
        zxing=get_library('zxingcpp')
        libs['zxingcpp']=str(getattr(zxing,'__version__','VERSION_NOT_EXPOSED'))
    if any(x not in ('opencv','zxingcpp') for x in decoders):raise ValueError('不支持的 decoder')
    inventory=build_inventory(input_root,left_name,right_name)
    registry=Path(__file__).resolve().parents[1]/'assets'/'strategy-registry.initial.json'
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+os.urandom(3).hex()
    run_root=report_root/run_id
    run_root.mkdir(parents=True,exist_ok=False)
    evidence=run_root/'evidence';evidence.mkdir()
    inv_path=evidence/'inventory.json'
    inv_path.write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest=make_manifest(run_id,inventory,workspace_root,registry,libs,decoders)
    manifest['inventory_sha256']=sha256_file(inv_path)
    attempt_path=evidence/'attempts.jsonl'
    total=0; decoded_images=0
    with attempt_path.open('x',encoding='utf-8') as out:
        for image_meta in manifest['images']:
            good=False
            for sid in manifest['strategy_order']:
                # record per-decoder even when early stopped or not implemented
                image_obj=None;transform_error=None
                if sid in ('V01','V02','V03') and not good:
                    try:
                        image_obj=load_image(image_meta['path'],cv2,np)
                        if image_obj.shape[0]*image_obj.shape[1]>max_pixels:
                            raise ValueError('MAX_PIXELS_EXCEEDED')
                        image_obj=preprocessing(image_obj,sid,cv2)
                    except Exception as exc:
                        transform_error=str(exc)
                stopped_before_strategy=good
                strategy_decoded=False
                for decoder in decoders:
                    begin=time.perf_counter()
                    record={'attempt_id':f"{run_id}-{image_meta['image_id']}-{sid}-{decoder}",
                            'run_id':run_id,'image_id':image_meta['image_id'],'group_id':image_meta['group_id'],
                            'side_id':image_meta['side_id'],'relative_path':image_meta['relative_path'],
                            'input_sha256':image_meta.get('sha256'), 'strategy_id':sid,
                            'strategy_order':int(sid[1:]), 'decoder_id':decoder,
                            'decoder_version':libs[decoder], 'decoder_options':{},
                            'status':'NOT_RUN','payload':None,'payload_sha256':None,
                            'candidate_count':0,'duration_ms':0,'error':None,'skip_reason':None,
                            'executed_at':utc_now()}
                    if stopped_before_strategy:
                        record['status']='SKIPPED_EARLY_STOP';record['skip_reason']='已由之前策略解码成功'
                    elif sid not in ('V01','V02','V03'):
                        record['status']='NOT_RUN';record['skip_reason']='NOT_IMPLEMENTED_EXACT_USER_STRATEGY: 待源码审计对齐'
                    elif transform_error:
                        record['status']='ERROR';record['error']=transform_error
                    else:
                        try:
                            texts,count=(decode_cv2(image_obj,cv2) if decoder=='opencv' else decode_zxing(image_obj,zxing))
                            record['candidate_count']=count
                            record['variant_width']=int(image_obj.shape[1])
                            record['variant_height']=int(image_obj.shape[0])
                            # Both pixels and metadata are used for auditing; not proof of decoder reproducibility.
                            record['variant_sha256']=hashlib.sha256(image_obj.tobytes()).hexdigest()
                            if texts:
                                record['status']='DECODED'
                                record['payload']=texts[0]
                                record['all_payloads']=texts
                                record['payload_sha256']=hashlib.sha256(texts[0].encode('utf-8')).hexdigest()
                                strategy_decoded=True
                            else:
                                record['status']='DETECTED_ONLY' if count else 'NO_DECODE'
                        except Exception as exc:
                            record['status']='ERROR';record['error']=str(exc)
                        record['duration_ms']=round((time.perf_counter()-begin)*1000,3)
                    out.write(json.dumps(record,ensure_ascii=False)+'\n')
                    total+=1
                good=good or strategy_decoded
            if good:decoded_images+=1
    manifest_path=evidence/'run-manifest.json'
    manifest['finished_at']=utc_now();manifest['attempt_count']=total
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'run_root':str(run_root),'evidence':str(evidence),'image_count':len(manifest['images']),
            'decoded_images':decoded_images,'attempts':total,'run_id':run_id}


def main():
    p=argparse.ArgumentParser(description='纯本地 V01–V03 基线扫描，未审计的 V04–V28 不会伪装成已经执行。')
    p.add_argument('--input-root',required=True)
    p.add_argument('--report-root',required=True)
    p.add_argument('--workspace-root')
    p.add_argument('--decoder',action='append',choices=['opencv','zxingcpp'])
    p.add_argument('--max-pixels',type=int,default=50000000)
    p.add_argument('--left-name',default='WAVES_QR');p.add_argument('--right-name',default='WAVES_QR_RAW')
    a=p.parse_args()
    try:
        result=run_scan(a.input_root,a.report_root,a.workspace_root,a.decoder,a.max_pixels,a.left_name,a.right_name)
        print(json.dumps({'status':'PASS_BASELINE_ONLY',**result},ensure_ascii=False));return 0
    except Exception as exc:
        print(json.dumps({'status':'BLOCKED','error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
