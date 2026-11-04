"""Strict run-manifest/attempt-matrix integrity checks (not a cryptographic attestation)."""
import argparse
import json
import sys
from pathlib import Path

VALID={'DECODED','DETECTED_ONLY','NO_DECODE','ERROR','SKIPPED_EARLY_STOP','SKIPPED_INELIGIBLE','NOT_RUN'}


def validate(manifest,attempts,registry=None):
    errors=[]; warnings=[]
    images={x['image_id'] for x in manifest.get('images',[])}
    strategies=manifest.get('strategy_order') or [x['strategy_id'] if isinstance(x,dict) else x for x in manifest.get('strategies',[])]
    decoders=[x['decoder_id'] if isinstance(x,dict) else x for x in manifest.get('decoders',[])]
    seen=set();ids=set()
    for n,a in enumerate(attempts,1):
        for k in ('image_id','strategy_id','decoder_id','status'):
            if not a.get(k):errors.append(f'#{n} 缺少 {k}')
        if a.get('status') not in VALID:errors.append(f'#{n} 状态不合法')
        if a.get('status') in {'SKIPPED_EARLY_STOP','SKIPPED_INELIGIBLE','NOT_RUN'} and not a.get('skip_reason'):
            errors.append(f'#{n} 跳过必须填写 skip_reason')
        if a.get('status')=='DECODED' and not (a.get('payload') not in (None,'') or a.get('payload_sha256')):
            errors.append(f'#{n} DECODED 缺少 payload / payload_sha256')
        if a.get('image_id') not in images: errors.append(f'#{n} image_id 未登记')
        if a.get('strategy_id') not in strategies: errors.append(f'#{n} strategy_id 未登记')
        if a.get('decoder_id') not in decoders: errors.append(f'#{n} decoder_id 未登记')
        aid=a.get('attempt_id')
        if aid:
            if aid in ids: errors.append(f'#{n} attempt_id 重复')
            ids.add(aid)
        seen.add((a.get('image_id'),a.get('strategy_id'),a.get('decoder_id')))
    if manifest.get('mode')=='contribution':
        expected={(img,sid,dec) for img in images for sid in strategies for dec in decoders}
        if not expected: errors.append('贡献度实验预期组合为空')
        missing=expected-seen
        if missing: errors.append('缺失组合 '+str(len(missing)))
        if any(x.get('status')=='SKIPPED_EARLY_STOP' for x in attempts): errors.append('贡献度实验禁止提前停止')
        if any(x.get('status') in {'ERROR','NOT_RUN'} or (x.get('status')=='SKIPPED_INELIGIBLE' and str(x.get('skip_reason','')).startswith(('NOT_IMPLEMENTED','DECODER_UNAVAILABLE'))) for x in attempts):
            errors.append('存在失败或未实现策略，完整贡献度不可用')
    for field in ('inventory_sha256','strategy_registry_sha256','source_fingerprint','dependencies'):
        if not manifest.get(field):warnings.append('缺少 '+field)
    return {'status':'PASS' if not errors else 'FAIL','errors':errors,'warnings':warnings,'attempt_count':len(attempts)}


def load_jsonl(p):
    return [json.loads(line) for line in Path(p).read_text(encoding='utf-8').splitlines() if line.strip()]


def main():
    p=argparse.ArgumentParser(description='二维码扫描证据校验')
    p.add_argument('--manifest',required=True);p.add_argument('--attempts',required=True)
    a=p.parse_args()
    try:
        result=validate(json.loads(Path(a.manifest).read_text(encoding='utf-8')),load_jsonl(a.attempts))
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['status']=='PASS' else 1
    except Exception as exc:
        print(json.dumps({'status':'ERROR','error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
