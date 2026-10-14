"""Generate all handoff files from one reviewed model."""
import base64
import json
import re
from pathlib import Path
from model import TYPE_PROPS, safe_css, validate_model
from common import digest, local_file, read_json, write_json
from colors import to_hex, normalize_css, conversion_info
from reference import metric_css, presentation
from documents import document

COMPACT_FILES = {'DESIGN.md':'DESIGN.compact.md','tokens.css':'tokens.compact.css',
    'tailwind.css':'tailwind.compact.css','design-tokens.json':'design-tokens.compact.json'}


def selected_tokens(model, compact=False):
    return [t for t in model['tokens'] if not compact or t['category'] in {'color','gradient','font'}]

CSS_GROUP = dict(color='color', gradient='gradient', font='font', typography='text',
                 spacing='spacing', radius='radius', shadow='shadow', surface='surface')
SUFFIX = dict(fontFamily='font-family', fontSize='font-size', fontWeight='font-weight',
    lineHeight='line-height', letterSpacing='letter-spacing', fontFeatureSettings='font-feature-settings',
    fontVariationSettings='font-variation-settings', textTransform='text-transform')



PROPERTY_ALIASES = {
    'color': ('color',), 'backgroundColor': ('background-color', 'background'),
    'backgroundImage': ('background-image', 'background'),
    'borderTopColor': ('border-top-color', 'border-top'), 'borderRightColor': ('border-right-color', 'border-right'),
    'borderBottomColor': ('border-bottom-color', 'border-bottom'), 'borderLeftColor': ('border-left-color', 'border-left'),
    'borderTopLeftRadius': ('border-top-left-radius',), 'borderTopRightRadius': ('border-top-right-radius',),
    'borderBottomRightRadius': ('border-bottom-right-radius',), 'borderBottomLeftRadius': ('border-bottom-left-radius',),
    'boxShadow': ('box-shadow',), 'fontFamily': ('font-family', 'font'),
    'fontSize': ('font-size', 'font'), 'fontWeight': ('font-weight', 'font'),
    'lineHeight': ('line-height',), 'letterSpacing': ('letter-spacing',),
    'fontFeatureSettings': ('font-feature-settings',), 'fontVariationSettings': ('font-variation-settings',),
    'textTransform': ('text-transform',)
}
INHERITED_PROPERTIES={'color','font-family','font-size','font-weight','font','line-height','letter-spacing',
    'font-feature-settings','font-variation-settings','text-transform','fill','stroke'}


def color_display(value):
    """Use one serializer for legacy/modern RGB and Oklab color values."""
    return to_hex(value)


def export_value(token):
    if token.get('category') in {'color','surface','gradient','shadow'}:
        return normalize_css(token.get('value'))
    return token.get('value')


def display_value(token):
    if token.get('category')=='gradient':return 'Gradient'
    return export_value(token)


def css_values_equal(a, b, category):
    if a == b: return True
    if category in {'color', 'surface'}: return color_display(a) == color_display(b)
    return False


def _source_candidates(evidence, element, token, observation):
    properties = PROPERTY_ALIASES.get(evidence.get('property'), (evidence.get('property'),))
    expected = token.get('value')
    matches = []
    if element and element.get('styleDeclarations'):
        for source_property, declared in element['styleDeclarations'].items():
            if source_property in properties:
                matches.append({'method':'inline-style','selector':evidence['selector'],'property':source_property,
                    'value':declared,'computedValue':expected,'matchStatus':'inline-candidate',
                    'snapshotId':evidence.get('snapshotId'),'observedSelector':evidence['selector'],'inherited':False,'origin':'inline'})
    if evidence.get('method')=='css-declaration':
        rule=observation['sourceRules'][evidence['sourceRuleIndex']]
        return [{'method':'css-declaration','sourceRuleIndex':evidence['sourceRuleIndex'],
            'selector':rule.get('selector',''),'property':evidence['property'],'value':evidence['value'],
            'computedValue':expected,'href':rule.get('href',''),'context':rule.get('context',''),
            'matchStatus':'explicit-declaration-evidence'}]
    rules=element.get('matchedRules',[]) if element else []
    if evidence.get('property','').startswith('::'):
        pseudo,prop=evidence['property'].split('.',1)
        properties=PROPERTY_ALIASES.get(prop,(prop,))
        rules=[rule for rule in rules if rule.get('pseudo')==pseudo]
    else:rules=[rule for rule in rules if not rule.get('pseudo')]
    explicit_inherit=any(not r.get('inherited') and any(r.get('values',{}).get(p)=='inherit' for p in properties) for r in rules)
    if not rules:
        rules=[dict(rule,sourceRuleIndex=index) for index,rule in enumerate(observation.get('sourceRules',[]))
            if not rule.get('context') and evidence['selector'] in [x.strip() for x in rule.get('selector','').split(',')]]
    for rule in rules:
        if rule.get('active') is False:continue
        values = rule.get('values', {})
        for source_property, declared in values.items():
            if rule.get('inherited') and source_property not in INHERITED_PROPERTIES and not explicit_inherit:continue
            if source_property not in properties or ('active' not in rule and not css_values_equal(expected, declared, token.get('category'))):
                continue
            exact_selector = any(part.strip() == evidence.get('selector') for part in rule.get('selector', '').split(','))
            matches.append({'method':'css-declaration','sourceRuleIndex':rule.get('sourceRuleIndex'),'selector':rule.get('selector',''),
                'property':source_property,'value':declared,'computedValue':expected,'href':rule.get('href',''),
                'context':rule.get('context',''),'range':rule.get('range'),
                'inherited':rule.get('inherited',False),'ancestorSelector':rule.get('ancestorSelector'),
                'ancestorDepth':rule.get('ancestorDepth'),'pseudo':rule.get('pseudo'),
                'origin':rule.get('origin'),'styleSheetId':rule.get('styleSheetId'),
                'matchingSelectors':rule.get('matchingSelectors'),'snapshotId':evidence.get('snapshotId'),
                'observedSelector':evidence['selector'],
                'stylesheetFile':next((s['file'] for s in observation.get('stylesheets',[]) if s.get('styleSheetId')==rule.get('styleSheetId') and rule.get('styleSheetId')),None),
                'matchStatus':'matched-candidate' if 'active' in rule else 'selector-exact-candidate',
                '_exact_selector': exact_selector})
            variables=set(re.findall(r'var\(\s*(--[\w-]+)',declared))
            if variables:
                matches[-1]['variableDeclarations']=[{'name':name,'value':r['values'][name],
                    'selector':r.get('selector'),'inherited':r.get('inherited',False),'ancestorSelector':r.get('ancestorSelector'),
                    'href':r.get('href'),'range':r.get('range'),'origin':r.get('origin')}
                    for r in (element or {}).get('matchedRules',[]) for name in sorted(variables) if name in r.get('values',{}) and r.get('active') is not False]
    matches.sort(key=lambda item: not item.get('_exact_selector', False))
    for item in matches: item.pop('_exact_selector', None)
    unique, seen = [], set()
    for item in matches:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen: continue
        seen.add(key); unique.append(item)
        if len(unique) >= 3: break
    return unique


def attach_source_declarations(model, run):
    """Add best-effort original CSS/inline declarations without rewriting computed evidence."""
    from common import coverage
    rows = {row['id']: row for row in coverage(run)['snapshots']}
    observations = {}
    for snapshot_id, row in rows.items():
        observations[snapshot_id] = read_json(local_file(run, row['file']))
    evidence_by_id = {item.get('id'): item for item in model.get('evidence', [])}
    for token in model.get('tokens', []):
        candidates = []
        rendered=[]
        for evidence_id in token.get('evidenceIds', []):
            evidence = evidence_by_id.get(evidence_id)
            if not evidence: continue
            observation = observations.get(evidence.get('snapshotId'))
            if not observation: continue
            parts=evidence_id.split(':')
            element = next((el for el in observation.get('elements', []) if len(parts)>1 and el.get('id')==parts[1]), None)
            if token['category']=='font' and element:
                for font in element.get('renderedFonts',[]):
                    item={**font,'snapshotId':evidence['snapshotId'],'selector':element['selector']}
                    if item not in rendered:rendered.append(item)
            candidates.extend(_source_candidates(evidence, element, token, observation))
        unique, seen = [], set()
        for item in candidates:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if key in seen: continue
            seen.add(key); unique.append(item)
            if len(unique) >= 3: break
        if unique: token['sourceDeclarations'] = unique
        if rendered:token['renderedFonts']=rendered
    return model

def variable(token):
    return '--' + CSS_GROUP[token['category']] + '-' + token['name']


def css_values(model, compact=False):
    values = {}
    for token in selected_tokens(model,compact):
        base = variable(token)
        if token['category'] == 'typography':
            for prop in TYPE_PROPS: values[base + '-' + SUFFIX[prop]] = safe_css(token['value'][prop])
        else: values[base] = safe_css(export_value(token))
    if not compact:
        for key,value in metric_css(model).items():
            if key in values and values[key]!=value:raise ValueError('布局变量与 Token 冲突：'+key)
            values[key]=value
    return values


def css(model, compact=False):
    return ':root {\n' + '\n'.join('  ' + k + ': ' + v + ';' for k,v in css_values(model,compact).items()) + '\n}\n'


def tailwind(model, compact=False):
    theme, extra = {}, {}
    for t in selected_tokens(model,compact):
        if t['category'] == 'typography':
            base = variable(t)
            theme[base] = t['value']['fontSize']
            for prop in ('lineHeight','fontWeight','letterSpacing'):
                theme[base + '--' + SUFFIX[prop]] = t['value'][prop]
            for prop in ('fontFamily','fontFeatureSettings','fontVariationSettings','textTransform'):
                extra[base + '-' + SUFFIX[prop]] = t['value'][prop]
        elif t['category'] in {'gradient','surface'}:
            extra[variable(t)] = export_value(t)
        else:
            theme[variable(t)] = export_value(t)
    if not compact:extra.update(metric_css(model))
    result = '/* Import with Tailwind v4; fonts are declared stacks, not bundled font files. */\n@theme {\n'
    result += '\n'.join('  ' + k + ': ' + v + ';' for k,v in theme.items()) + '\n}\n'
    if extra:
        result += '\n/* Complete gradients, surfaces and additional typography properties. */\n:root {\n'
        result += '\n'.join('  ' + k + ': ' + v + ';' for k,v in extra.items()) + '\n}\n'
    return result


def tokens_json(model, compact=False):
    result = {}
    reserved={t['name'] for t in model['tokens'] if t['category']=='color'}
    for t in selected_tokens(model,compact):
        group='color' if t['category']=='gradient' else t['category']
        name=t['name']
        if t['category']=='gradient':
            while name in reserved:name='gradient-'+name
            reserved.add(name)
        result.setdefault(group, {})[name] = {
            '$value': export_value(t), '$type': t['type'], '$description': t.get('role') or t['label'],
            '$extensions': {'org.yoho-design-extractor': {'status':t['status'],
                'nameStatus':t.get('nameStatus','inferred'), 'evidenceIds':t['evidenceIds'], 'cssVariable':variable(t),
                'sourceCategory':t['category'],
                'computedValue':t['value'], 'displayValue':display_value(t),
                'renderedFonts':t.get('renderedFonts',[]),
                'normalization':conversion_info(t['value']) if t['category'] in {'color','surface','gradient','shadow'} else {},
                'sourceDeclarations':t.get('sourceDeclarations', [])}}}
    result['$extensions'] = {'org.yoho-design-extractor': {
        'url':model['sourceUrl'],'siteName':model['siteName'],'extractedAt':model['generatedAt'],
        'format':'CSS-oriented token exchange; importer conformance is not asserted',
        'pageCount':model['coverage']['pageCount'],'variant':'compact' if compact else 'extended'}}
    if not compact:result['$extensions']['org.yoho-design-extractor']['layoutMetrics']=model.get('layoutMetrics',{})
    return json.dumps(result, ensure_ascii=False, indent=2) + '\n'


def markdown(model, compact=False):
    return document(model,compact,variable)


def generate(model, run):
    validate_model(model, run)
    if model.get('review',{}).get('status') != 'reviewed' or not model['overview'].get('description'):
        raise ValueError('先完成 Agent 解释，填写摘要并将 review.status 设为 reviewed')
    css_map = css_values(model)
    export_model = attach_source_declarations(json.loads(json.dumps(model)), run)
    for t in export_model['tokens']:
        if t['category'] in {'color','surface','gradient','shadow'} and conversion_info(t['value'])['status']=='unsupported':
            export_model['coverage']['gaps'].append(t['id']+': color encoding unsupported; original retained')
    for t in export_model['tokens']:
        t['cssVariable'] = variable(t)
        t['displayValue'] = display_value(t)
        t['exportValue'] = export_value(t)
        if t['label']==t['value']:t['label']=str(t['displayValue'])
    files = {'DESIGN.md':markdown(export_model),'DESIGN.compact.md':markdown(export_model,True),
        'tokens.css':css(model),'tokens.compact.css':css(model,True),
        'tailwind.css':tailwind(model),'tailwind.compact.css':tailwind(model,True),
        'design-tokens.json':tokens_json(export_model),'design-tokens.compact.json':tokens_json(export_model,True)}
    view_model={key:export_model[key] for key in ('siteName','sourceUrl','overview','tokens','guidelines')}
    payload = {'model':view_model,'files':files,'css':css_map,'compactFiles':COMPACT_FILES,
        'reference':presentation(export_model)}
    assets = Path(__file__).resolve().parent.parent/'assets'
    template = (assets/'preview.html').read_text(encoding='utf-8')
    preview_css = (assets/'preview.css').read_text(encoding='utf-8').replace(
        '__PREVIEW_FONT_DATA_URL__', 'data:font/woff2;base64,' +
        base64.b64encode((assets/'jetbrains-mono-latin.woff2').read_bytes()).decode('ascii'))
    template = template.replace('__PREVIEW_CSS__', preview_css).replace(
        '__PREVIEW_JS__', (assets/'preview.js').read_text(encoding='utf-8')).replace(
        '__PREVIEW_AVATAR_DATA_URL__', 'data:image/png;base64,' +
        base64.b64encode((assets/'yohoia-avatar.png').read_bytes()).decode('ascii'))
    encoded = json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    files['preview.html'] = template.replace('__PAYLOAD__',encoded)
    return files


def export(run):
    run = Path(run)
    model = read_json(run/'design.json')
    files = generate(model, run)
    from common import coverage
    cov=coverage(run)
    for key in ('omittedTokenCandidates','rejectedTokenCandidates','omittedComponentCandidates'):cov[key]=model['coverage'].get(key,{})
    for t in model['tokens']:
        if t['category'] in {'color','surface','gradient','shadow'} and conversion_info(t['value'])['status']=='unsupported':
            cov['gaps'].append(t['id']+': color encoding unsupported; original retained')
    write_json(run/'evidence'/'coverage.json',cov)
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
