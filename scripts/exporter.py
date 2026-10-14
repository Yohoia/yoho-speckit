"""Generate all handoff files from one reviewed model."""
import json
from pathlib import Path
from model import TYPE_PROPS, safe_css, validate_model
from common import digest, read_json, write_json

LABELS = dict(observed='实测', inferred='推断', proposed='补全提案', unknown='未知')
CSS_GROUP = dict(color='color', gradient='gradient', font='font', typography='text',
                 spacing='spacing', radius='radius', shadow='shadow', surface='surface')
SUFFIX = dict(fontFamily='font-family', fontSize='font-size', fontWeight='font-weight',
    lineHeight='line-height', letterSpacing='letter-spacing', fontFeatureSettings='font-feature-settings',
    fontVariationSettings='font-variation-settings', textTransform='text-transform')


def variable(token):
    return '--' + CSS_GROUP[token['category']] + '-' + token['name']


def css_values(model):
    values = {}
    for token in model['tokens']:
        base = variable(token)
        if token['category'] == 'typography':
            for prop in TYPE_PROPS: values[base + '-' + SUFFIX[prop]] = safe_css(token['value'][prop])
        else: values[base] = safe_css(token['value'])
    return values


def css(model):
    return ':root {\n' + '\n'.join('  ' + k + ': ' + v + ';' for k,v in css_values(model).items()) + '\n}\n'


def tailwind(model):
    theme, extra = {}, {}
    for t in model['tokens']:
        if t['category'] == 'typography':
            base = variable(t)
            theme[base] = t['value']['fontSize']
            for prop in ('lineHeight','fontWeight','letterSpacing'):
                theme[base + '--' + SUFFIX[prop]] = t['value'][prop]
            for prop in ('fontFamily','fontFeatureSettings','fontVariationSettings','textTransform'):
                extra[base + '-' + SUFFIX[prop]] = t['value'][prop]
        elif t['category'] in {'gradient','surface'}:
            extra[variable(t)] = t['value']
        else:
            theme[variable(t)] = t['value']
    result = '/* Import with Tailwind v4; fonts are declared stacks, not bundled font files. */\n@theme {\n'
    result += '\n'.join('  ' + k + ': ' + v + ';' for k,v in theme.items()) + '\n}\n'
    if extra:
        result += '\n/* Complete gradients, surfaces and additional typography properties. */\n:root {\n'
        result += '\n'.join('  ' + k + ': ' + v + ';' for k,v in extra.items()) + '\n}\n'
    return result


def tokens_json(model):
    result = {}
    for t in model['tokens']:
        result.setdefault(t['category'], {})[t['name']] = {
            '$value': t['value'], '$type': t['type'], '$description': t.get('role') or t['label'],
            '$extensions': {'org.yoho-design-extractor': {'status':t['status'],
                'nameStatus':t.get('nameStatus','inferred'), 'evidenceIds':t['evidenceIds'], 'cssVariable':variable(t)}}}
    result['$extensions'] = {'org.yoho-design-extractor': {
        'url':model['sourceUrl'],'siteName':model['siteName'],'extractedAt':model['generatedAt'],
        'format':'CSS-oriented token exchange; importer conformance is not asserted',
        'pageCount':model['coverage']['pageCount']}}
    return json.dumps(result, ensure_ascii=False, indent=2) + '\n'


def cell(value):
    return str(value).replace('|','\\|').replace('\n',' ').replace('`','\\`')


def text_item(item):
    return item.get('text') or item.get('description') or item.get('name') or '尚未解释'


def markdown(model, compact=False):
    overview = model['overview']
    lines = ['# ' + model['siteName'] + ' — Style Reference',
        '> ' + (overview.get('tagline') or '基于已采页面的样式参考'), '',
        '来源：' + model['sourceUrl'], '',
        '测量值来自 DOM；名称和用途可能为推断；HTML 样本是重建示例。',
        '字体栈为声明/计算结果，不保证字体文件已随产物分发。', '',
        '**摘要状态：** ' + LABELS[overview['status']], '', overview.get('description') or '摘要待依据证据解释。', '']
    titles = [('color','Colors'),('gradient','Gradients'),('font','Typography — Fonts'),
              ('typography','Typography — Type Scale'),('spacing','Spacing & Shapes — Spacing'),
              ('radius','Spacing & Shapes — Border Radius'),('shadow','Elevation'),('surface','Surfaces')]
    for category, title in titles:
        rows = [t for t in model['tokens'] if t['category'] == category]
        if compact: rows = rows[:12]
        lines += ['## ' + ('' if compact else 'Tokens — ') + title, '']
        if not rows: lines += ['未在已采范围确认。','']; continue
        lines += ['| Name | Value | Token | Role | Evidence |','|---|---|---|---|---|']
        for t in rows:
            value = json.dumps(t['value'],ensure_ascii=False) if isinstance(t['value'],dict) else t['value']
            refs = ', '.join(t['evidenceIds'][:2])
            lines.append('| ' + ' | '.join(cell(v) for v in (t['label'],value,variable(t),t.get('role') or '用途待解释',LABELS[t['status']] + ': ' + refs)) + ' |')
        lines.append('')
    lines += ['## Components','']
    for c in model['components']:
        lines += ['### ' + c['name'], '', '**状态：** ' + LABELS[c['status']] + ' · ' + c.get('state','未指定') + ' · ' + c.get('viewport','未指定'),
            '', c.get('description') or '用途待依据源证据解释。', '', 'Evidence: ' + ', '.join(c['evidenceIds']), '']
        if not compact:
            lines += ['```json',json.dumps(c.get('styles',{}),ensure_ascii=False,indent=2),'```','']
    if not model['components']: lines += ['未在已采范围确认代表组件。','']
    lines += ["## Do's and Don'ts",'']
    for key,title in (('do','Do'),('dont',"Don't")):
        lines += ['### ' + title,'']
        lines += ['- [' + LABELS[x['status']] + '] ' + text_item(x) for x in model['guidelines'][key]] or ['尚未形成有依据的建议。']
        lines.append('')
    for key,title in (('imagery','Imagery'),('layout','Layout'),('agentPromptGuide','Agent Prompt Guide'),('signatureRules','Signature Rules'),('similarBrands','Similar Brands')):
        lines += ['## ' + title,'']
        lines += ['- [' + LABELS[x['status']] + '] ' + text_item(x) for x in model['sections'][key]] or ['未确认；不根据缺失信息补造规则。']
        lines.append('')
    cov = model['coverage']
    lines += ['## Coverage & Evidence','',f"已采 {cov['pageCount']} 个页面、{cov['snapshotCount']} 个快照。",'']
    for row in cov['snapshots']:
        lines.append('- ' + row['url'] + ' · ' + row['viewport'] + ' · ' + row['state'] + ' · ' + row['capturedAt'])
    lines += ['', '### Gaps','']
    lines += ['- ' + x for x in cov['gaps']]
    lines += ['- 缺少计划快照：' + json.dumps(x,ensure_ascii=False) for x in cov['missing']]
    lines += ['- 采集失败：' + str(x.get('stage')) + ' / ' + str(x.get('code')) for x in cov['failures']]
    if not compact:
        lines += ['', '## Quick Start','','### CSS Custom Properties','','```css',css(model).rstrip(),'```','',
                  '### Tailwind v4','','```css',tailwind(model).rstrip(),'```','']
    return '\n'.join(lines).rstrip() + '\n'


def generate(model, run):
    validate_model(model, run)
    if model.get('review',{}).get('status') != 'reviewed' or not model['overview'].get('description'):
        raise ValueError('先完成 Agent 解释，填写摘要并将 review.status 设为 reviewed')
    files = {'DESIGN.md':markdown(model),'DESIGN.compact.md':markdown(model,True),
        'tokens.css':css(model),'tailwind.css':tailwind(model),'design-tokens.json':tokens_json(model)}
    css_map = css_values(model)
    export_model = json.loads(json.dumps(model))
    for t in export_model['tokens']: t['cssVariable'] = variable(t)
    payload = {'model':export_model,'files':files,'css':css_map}
    template = (Path(__file__).resolve().parent.parent/'assets'/'preview.html').read_text(encoding='utf-8')
    encoded = json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    files['preview.html'] = template.replace('__PAYLOAD__',encoded)
    return files


def export(run):
    run = Path(run)
    model = read_json(run/'design.json')
    files = generate(model, run)
    write_json(run/'evidence'/'coverage.json',model['coverage'])
    for name, content in files.items():
        target = run/name
        temporary = run/(name+'.tmp')
        temporary.write_text(content,encoding='utf-8')
        temporary.replace(target)
    manifest = {'modelSha256':digest(model),'files':{name:digest(content) for name,content in files.items()}}
    write_json(run/'export-manifest.json',manifest)
    return list(files)


def verify(run):
    run = Path(run)
    model = read_json(run/'design.json')
    expected = generate(model,run)
    manifest = read_json(run/'export-manifest.json')
    if manifest.get('modelSha256') != digest(model): raise ValueError('导出模型已过期')
    for name, content in expected.items():
        path = run/name
        if not path.exists() or path.read_text(encoding='utf-8') != content or manifest['files'].get(name) != digest(content):
            raise ValueError('导出缺失或不一致：' + name)
    return {'status':'passed','files':len(expected),'tokens':len(model['tokens']),
            'pages':model['coverage']['pageCount'],'gaps':len(model['coverage']['gaps'])}
