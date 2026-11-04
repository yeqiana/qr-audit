"""Render paired Markdown and standalone offline HTML from one structured JSON model."""
import argparse
import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path

CSS = '''
:root{color-scheme:light;--ink:#17263a;--muted:#56677e;--line:#dde5f0;--surface:#f6f9fc;--accent:#2563eb}
*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);font:15px/1.68 system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:1200px;margin:0 auto;padding:32px 22px 75px}h1{font-size:clamp(1.5rem,3vw,2.3rem)}h2{font-size:1.2rem;margin-top:2rem;border-top:1px solid var(--line);padding-top:1rem}
pre{background:#18283c;color:#fff;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;padding:15px;border-radius:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:1.2rem 0}.metric{border:1px solid var(--line);background:var(--surface);border-radius:9px;padding:12px}
.metric-label{color:var(--muted);font-size:.84rem}.metric-value{font-size:1.4rem;font-weight:700;overflow-wrap:anywhere}.table-wrap{overflow-x:auto;margin:1rem 0;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;min-width:550px;font-size:.9rem}td,th{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:var(--surface)}caption{text-align:left;padding:7px;font-weight:700}
code{background:#edf1f7;border-radius:3px;padding:0 3px}pre code{background:transparent}a:focus-visible{outline:3px solid orange}blockquote{border-left:3px solid var(--accent);margin:1rem 0;padding:.7rem;background:var(--surface)}
footer{font-size:.82rem;color:var(--muted);border-top:1px solid var(--line);margin-top:30px;padding-top:15px}
@media(max-width:550px){main{padding:20px 12px}table{font-size:.82rem}}@media print{main{max-width:none;padding:0}table,pre{break-inside:avoid}}
'''


def safe_stem(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', str(s or '')).strip(' .-')
    if s in ('', '.', '..'):
        raise ValueError('无效报告文件名')
    return s[:125]


def txt(v):
    return str(v.get('text', '')) if isinstance(v, dict) else str(v)


def md_cell(v):
    use_code = isinstance(v, dict) and v.get("code", False)
    v = txt(v).replace('\\', '\\\\').replace('|', '\\|').replace('\n', '<br>')
    if use_code:
        ticks = "`" * (max((len(m) for m in re.findall(r"`+", v)), default=0) + 1)
        return ticks + " " + v + " " + ticks
    return v


def build_md(report, digest):
    out = ['# ' + str(report['title']), '', '- 报告状态：' + str(report.get('status', 'NOT_VERIFIED')),
           '- 生成时间：' + str(report.get('generated_at', 'NOT_VERIFIED')),
           '- report-model SHA-256：`' + digest + '`', '']
    if report.get('metrics'):
        out += ['## 核心指标', '', '| 指标 | 数值 |', '| --- | --- |']
        out += ['| '+md_cell(m['label'])+' | '+md_cell(m['value'])+' |' for m in report['metrics']]
        out += ['']
    for s in report.get('sections', []):
        if s.get('title'):
            out += ['## '+str(s['title']), '']
        k = s['type']
        if k in ('paragraph', 'callout'):
            prefix = '> ' if k == 'callout' else ''
            out += [prefix+str(line) for line in str(s.get('text','')).splitlines() or ['']]
            out += ['']
        elif k == 'table':
            heads = s.get('headers', [])
            if not heads:
                raise ValueError('表格无 headers')
            out += ['| '+' | '.join(md_cell(h) for h in heads)+' |',
                    '| '+' | '.join('---' for _ in heads)+' |']
            for row in s.get('rows', []):
                if len(row) != len(heads):
                    raise ValueError('表格列数不一致')
                out += ['| '+' | '.join(md_cell(v) for v in row)+' |']
            out += ['']
        elif k == 'list':
            out += ['- '+str(x) for x in s.get('items', [])]+['']
        elif k in ('code', 'diagram'):
            if s.get('caption'):
                out += ['> '+str(s['caption']), '']
            code = str(s.get('content', ''))
            fence = '`'*max(3, max((len(x) for x in re.findall(r'`+', code)), default=0)+1)
            lang = str(s.get('language', 'text')) if k == 'code' else 'text'
            out += [fence+lang, code, fence, '']
        else:
            raise ValueError('未知 section: '+str(k))
    out += ['---', '', '本报告仅代表离线解码结果，不证明微信 App 支持或业务可用；载荷中的 URL 未被访问。', '']
    return '\n'.join(out)


def build_html(report, digest):
    e = html.escape
    out = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
           f'<meta name="report-model-sha256" content="{digest}">',
           '<title>'+e(str(report['title']))+'</title><style>'+CSS+'</style></head><body><main>',
           '<div style="color:var(--muted)">qr-audit · 静态离线报告</div>',
           '<h1>'+e(str(report['title']))+'</h1>',
           '<p>报告状态：'+e(str(report.get('status', 'NOT_VERIFIED')))+' · '+e(str(report.get('generated_at','')) )+'</p>']
    if report.get('metrics'):
        out += ['<section class="grid" aria-label="核心指标">']
        for m in report['metrics']:
            out += ['<div class="metric"><div class="metric-label">'+e(str(m['label']))+'</div>',
                    '<div class="metric-value">'+e(str(m['value']))+'</div></div>']
        out += ['</section>']
    for s in report.get('sections', []):
        if s.get('title'):
            out += ['<h2>'+e(str(s['title']))+'</h2>']
        k = s['type']
        if k == 'paragraph':
            out += ['<p>'+e(str(s.get('text',''))).replace('\n','<br>')+'</p>']
        elif k == 'callout':
            out += ['<blockquote>'+e(str(s.get('text',''))).replace('\n','<br>')+'</blockquote>']
        elif k == 'table':
            heads=s.get('headers', [])
            if not heads:
                raise ValueError('表格无 headers')
            out += ['<div class="table-wrap"><table><caption>'+e(str(s.get('title','数据表')))+'</caption><thead><tr>']
            out += ['<th scope="col">'+e(str(h))+'</th>' for h in heads]
            out += ['</tr></thead><tbody>']
            for row in s.get('rows', []):
                if len(row)!=len(heads):
                    raise ValueError('表格列数不一致')
                out += ['<tr>' + ''.join('<td>'+e(txt(v))+'</td>' for v in row)+'</tr>']
            out += ['</tbody></table></div>']
        elif k == 'list':
            out += ['<ul>']+['<li>'+e(str(x))+'</li>' for x in s.get('items', [])]+['</ul>']
        elif k in ('code','diagram'):
            if s.get('caption'):
                out += ['<p>'+e(str(s['caption']))+'</p>']
            out += ['<pre><code>'+e(str(s.get('content','')))+'</code></pre>']
        else:
            raise ValueError('未知 section: '+str(k))
    out += ['<footer>仅供离线审阅，不访问载荷链接，不运行远程脚本。数据 SHA-256：'+digest+'</footer>',
            '</main></body></html>']
    return ''.join(out)


def render(model_path, output_dir):
    raw=Path(model_path).read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    model=json.loads(raw)
    if model.get('schema_version')!='1.0' or not isinstance(model.get('reports'), list):
        raise ValueError('schema_version/reports 无效')
    out=Path(output_dir)
    stems=[safe_stem(x.get('file_stem')) for x in model['reports']]
    if len(set(stems))!=len(stems):
        raise ValueError('重复 file_stem')
    targets=[out/(name+ext) for name in stems for ext in ('.md','.html')]
    targets.append(out/'render-manifest.json')
    if any(x.exists() for x in targets):
        raise FileExistsError('文件已存在，拒绝覆盖: '+', '.join(str(x) for x in targets if x.exists()))
    # First render all in memory, so unknown block or bad table cannot produce partial output.
    payloads=[]
    for stem, rep in zip(stems,model['reports']):
        payloads.append((out/(stem+'.md'), build_md(rep,digest)))
        payloads.append((out/(stem+'.html'), build_html(rep,digest)))
    entries=[{'markdown':str(out/(stem+'.md')),'html':str(out/(stem+'.html'))} for stem in stems]
    payloads.append((out/'render-manifest.json',json.dumps({'report_model_sha256':digest,'files':entries},ensure_ascii=False,indent=2)))
    out.mkdir(parents=True,exist_ok=True)
    for path,data in payloads:
        with path.open('x',encoding='utf-8') as f: f.write(data)
    return entries


def main():
    p=argparse.ArgumentParser(description='同一结构化 JSON → Markdown + 同名离线 HTML')
    p.add_argument('--input',required=True)
    p.add_argument('--out-dir',required=True)
    a=p.parse_args()
    try:
        result=render(a.input,a.out_dir)
        print(json.dumps({'status':'PASS','reports':len(result),'files':result},ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'status':'ERROR','error':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2

if __name__=='__main__': raise SystemExit(main())
