"""Read-only source hints for an agent-led audit. Hints are never confirmation."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

EXT={'.py','.java','.cpp','.cc','.c','.h','.hpp','.rs','.js','.ts','.cs','.yaml','.yml','.toml','.json'}
SKIP={'.git','.idea','node_modules','.venv','venv','__pycache__','target','dist','build','report'}
KEYWORDS={
  'decoder_zxing':r'zxing|read_barcodes|ReadBarcode',
  'decoder_opencv':r'QRCodeDetector|detectAndDecode|wechatqrcode|WeChatQRCode',
  'invert':r'tryInvert|try_invert|bitwise_not|invert',
  'rotate':r'tryRotate|try_rotate|rotate',
  'downscale':r'tryDownscale|try_downscale|INTER_AREA|resize',
  'pure':r'isPure|is_pure|pureBarcode|pure_mode',
  'threshold':r'Otsu|THRESH_OTSU|adaptiveThreshold|threshold',
  'border':r'copyMakeBorder|BORDER_CONSTANT|quiet.zone|white_border',
  'module_sampling':r'module.?sampl|sample.?module|grid.?detect|perspectiveTransform',
  'early_stop':r'break|return|early.stop|stop_on_success'
}

def analyze(root,max_bytes=2_000_000,max_lines=300000):
    root=Path(root).expanduser().resolve()
    if not root.is_dir():raise ValueError('源码目录不存在')
    candidates=[];files_scanned=0;lines_scanned=0
    for path in sorted(root.rglob('*'),key=lambda p:str(p)):
        if any(part in SKIP for part in path.relative_to(root).parts):continue
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in EXT or path.stat().st_size>max_bytes:continue
        files_scanned+=1
        raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        src=raw.decode('utf-8',errors='replace')
        for line_num,line in enumerate(src.splitlines(),1):
            lines_scanned+=1
            for kind,pattern in KEYWORDS.items():
                if re.search(pattern,line,re.IGNORECASE):
                    candidates.append({'path':path.relative_to(root).as_posix(),'sha256':digest,'line':line_num,
                                       'keyword_group':kind,'snippet':line[:250],'audit_state':'HINT_ONLY'})
            if lines_scanned>=max_lines:break
        if lines_scanned>=max_lines:break
    return {'schema_version':'1.0','root':str(root),'files_scanned':files_scanned,'lines_scanned':lines_scanned,
            'truncated':lines_scanned>=max_lines,'source_hints':candidates,
            'conclusion':'NOT_VERIFIED: 仅为正则检索候选。策略实现、参数、调用条件与运行态需 Agent 实际阅读源码并核验。'}

def main():
    p=argparse.ArgumentParser(description='只读扫描二维码源码关键字，输出审计候选位置（不自动确认实现）')
    p.add_argument('--source-root',required=True);p.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        result=analyze(a.source_root)
        path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
        print(json.dumps({'status':'HINT_ONLY','files':result['files_scanned'],'hits':len(result['source_hints']),'output':str(path)},ensure_ascii=False));return 0
    except Exception as exc:
        print(json.dumps({'status':'ERROR','error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
