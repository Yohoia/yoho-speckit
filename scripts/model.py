"""Deterministic candidate extraction; semantic interpretation remains editable."""
import re
from collections import defaultdict
from pathlib import Path
from common import coverage, digest, index_for, local_file, read_json, write_json, now, STATUS

TYPE_PROPS = ('fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing',
              'fontFeatureSettings', 'fontVariationSettings', 'textTransform')
LIMITS = dict(color=80, gradient=16, font=16, typography=64, spacing=64, radius=32, shadow=32, surface=48)
TYPES = dict(color='color', gradient='gradient', font='fontFamily', typography='typography',
             spacing='dimension', radius='dimension', shadow='shadow', surface='color')
NARRATIVE_SECTIONS = (('imagery','Imagery'),('layout','Layout'),
    ('agentPromptGuide','Agent Prompt Guide'),('signatureRules','Signature Rules'),
    ('similarBrands','Similar Brands'))
LENGTH = re.compile(r'-?(?:\d+(?:\.\d+)?|\.\d+)(?:px|rem|em|%|vh|vw|dvh|dvw|svh|svw|lvh|lvw|ch|ex|vmin|vmax|cqw|cqh|pt|pc|cm|mm|in)$')


def safe_css(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 3000:
        raise ValueError('CSS 值为空、过长或类型错误')
    if re.search(r'[;{}<>@\n\r]|/\*|\*/|url\s*\(|expression\s*\(', value, re.I):
        raise ValueError('Token 必须为单个无外部资源的 CSS 值')
    return value


def nonzero(value):
    return value and value not in {'0', '0px', 'normal', 'none', 'auto', 'transparent', 'rgba(0, 0, 0, 0)'}


def validate_value(category, value):
    if category == 'typography':
        if not isinstance(value, dict) or set(value) != set(TYPE_PROPS):
            raise ValueError('排版组合字段缺失')
        for item in value.values(): safe_css(item)
        validate_value('spacing', value['fontSize'])
    else:
        safe_css(value)
        if value.count('(') != value.count(')'): raise ValueError('CSS 括号未配对')
        if category in {'spacing','radius'}:
            functional = re.match(r'^(?:calc|clamp|min|max)\(.+\)$',value)
            parts = value.split()
            if not functional and (not 1 <= len(parts) <= (2 if category == 'radius' else 1) or any(not LENGTH.fullmatch(x) and x != '0' for x in parts)):
                raise ValueError('尺寸必须是可执行长度；范围留在说明中')
        if category == 'gradient' and 'gradient(' not in value: raise ValueError('渐变需要完整 CSS 函数')


def build(run):
    run = Path(run)
    cov = coverage(run)
    index = index_for(run)
    if not index['snapshots']:
        raise ValueError('没有 DOM 实测证据；先采集再 build')
    groups = defaultdict(dict)
    evidence = {}
    components = []
    component_seen = set()

    def add(category, value, row, el, prop):
        try:
            validate_value(category,value)
        except ValueError:
            return
        key = digest(value)[:12]
        evid = row['id'] + ':' + el['id'] + ':' + prop
        evidence[evid] = {'id': evid, 'snapshotId': row['id'], 'selector': el['selector'],
                          'property': prop, 'value': value}
        item = groups[category].setdefault(key, {'id': category + '-' + key,
            'category': category, 'name': 'sample-' + key, 'label': str(value) if isinstance(value, str) else value['fontSize'] + ' / ' + value['fontWeight'],
            'value': value, 'type': TYPES[category], 'status': 'observed',
            'nameStatus': 'inferred', 'role': '', 'evidenceIds': [], 'count': 0})
        item['count'] += 1
        if len(item['evidenceIds']) < 16: item['evidenceIds'].append(evid)

    observations = []
    for row in index['snapshots']:
        obs = read_json(local_file(run, row['file']))
        observations.append(obs)
        for el in obs['elements']:
            s = el['styles']
            if el.get('hasText') and s.get('color'): add('color', s['color'], row, el, 'color')
            if nonzero(s.get('backgroundColor')):
                add('color', s['backgroundColor'], row, el, 'backgroundColor')
                add('surface', s['backgroundColor'], row, el, 'backgroundColor')
            for edge in ('Top', 'Right', 'Bottom', 'Left'):
                if nonzero(s.get('border' + edge + 'Width')) and s.get('border' + edge + 'Color'):
                    add('color', s['border' + edge + 'Color'], row, el, 'border' + edge + 'Color')
            if 'gradient(' in s.get('backgroundImage', ''): add('gradient', s['backgroundImage'], row, el, 'backgroundImage')
            if el.get('hasText') and all(s.get(p) for p in TYPE_PROPS):
                add('font', s['fontFamily'], row, el, 'fontFamily')
                add('typography', {p:s[p] for p in TYPE_PROPS}, row, el, 'typography')
            for p in ('paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'gap', 'rowGap', 'columnGap'):
                if nonzero(s.get(p)): add('spacing', s[p], row, el, p)
            for p in ('borderTopLeftRadius', 'borderTopRightRadius', 'borderBottomRightRadius', 'borderBottomLeftRadius'):
                if nonzero(s.get(p)): add('radius', s[p], row, el, p)
            if nonzero(s.get('boxShadow')): add('shadow', s['boxShadow'], row, el, 'boxShadow')
            for pseudo, ps in el.get('pseudos',{}).items():
                for prop in ('color','backgroundColor'):
                    if nonzero(ps.get(prop)):add('color',ps[prop],row,el,pseudo+'.'+prop)
                if 'gradient(' in ps.get('backgroundImage',''):add('gradient',ps['backgroundImage'],row,el,pseudo+'.backgroundImage')
                if nonzero(ps.get('boxShadow')):add('shadow',ps['boxShadow'],row,el,pseudo+'.boxShadow')
            kind = 'button' if el.get('role') == 'button' else 'input' if el['tag'] in {'input','textarea','select'} else 'navigation' if el['tag'] == 'nav' else None
            if kind:
                fingerprint = digest([kind, s.get('backgroundColor'), s.get('borderTopColor'), s.get('borderTopLeftRadius'), s.get('fontSize')])
                if fingerprint not in component_seen and len(components) < 16:
                    component_seen.add(fingerprint)
                    evid = row['id'] + ':' + el['id'] + ':element'
                    evidence[evid] = {'id':evid,'snapshotId':row['id'],'selector':el['selector'],'property':'element','value':el['selector']}
                    components.append({'name':kind + ' ' + str(len(components)+1), 'kind':kind,
                        'description':'', 'status':'observed', 'nameStatus':'inferred',
                        'evidenceIds':[evid], 'styles':s, 'text':el.get('text') or kind,
                        'state':row['state'], 'viewport':row['viewport']})
    tokens, omitted = [], {}
    for category, items in groups.items():
        values = sorted(items.values(), key=lambda x:(-x['count'],x['id']))
        tokens.extend(values[:LIMITS[category]])
        if len(values) > LIMITS[category]: omitted[category] = len(values) - LIMITS[category]
    used = {ref for item in tokens + components for ref in item['evidenceIds']}
    cov['omittedTokenCandidates'] = omitted
    if omitted: cov['gaps'].append('Candidate token limits reached; raw observations retain omitted values')
    model = {'schemaVersion':1, 'siteName': observations[0].get('title') or observations[0]['url'],
        'sourceUrl':read_json(run/'plan.json')['originalUrl'], 'generatedAt':now(),
        'theme':observations[0].get('theme',{}).get('colorScheme') or 'unknown','layoutMetrics':{},
        'overview':{'tagline':'', 'description':'', 'status':'unknown', 'evidenceIds':[]},
        'tokens':tokens, 'components':components,
        'guidelines':{'do':[], 'dont':[]},
        'sections':{key:[] for key,title in NARRATIVE_SECTIONS},
        'coverage':cov, 'evidence':[evidence[k] for k in sorted(used)],
        'notes':['Candidate names and semantic roles require Agent review.',
                 'Computed font stacks do not prove the exact font used for every glyph.',
                 'Counts describe sampled elements, not site-wide token prevalence.'],
        'review':{'status':'candidate','notes':[]}}
    target = run / ('design.candidate.json' if (run/'design.json').exists() else 'design.json')
    write_json(target, model)
    return target, model


def validate_model(model, run):
    if model.get('schemaVersion') != 1 or not model.get('siteName'):
        raise ValueError('design.json 版本或站名无效')
    from common import url, plan_for
    if url(model['sourceUrl']) != url(plan_for(run)['originalUrl']):
        raise ValueError('模型来源与运行计划不一致')
    cov = coverage(run)
    actual = {s['id']:s for s in cov['snapshots']}
    stored = {s['id']:s for s in model['coverage']['snapshots']}
    if actual != stored:
        raise ValueError('模型证据快照过期；重新 build 并合并解释')
    refs = {}
    for e in model.get('evidence', []):
        if e['id'] in refs or e['snapshotId'] not in actual:
            raise ValueError('证据重复或指向不存在的快照')
        refs[e['id']] = e
        obs = read_json(local_file(run, actual[e['snapshotId']]['file']))
        if e.get('method')=='css-declaration':
            rule_index=e.get('sourceRuleIndex')
            if not isinstance(rule_index,int) or not 0<=rule_index<len(obs.get('sourceRules',[])):
                raise ValueError('CSS 声明坐标无效')
            rule=obs['sourceRules'][rule_index]
            if rule.get('selector')!=e['selector'] or rule.get('values',{}).get(e['property'])!=e['value']:
                raise ValueError('CSS 声明与原始观察不一致')
            continue
        element_id = e['id'].split(':')[1] if ':' in e['id'] else ''
        el = next((x for x in obs['elements'] if x['id'] == element_id), None)
        if not el or el['selector'] != e['selector']:
            raise ValueError('证据坐标与原始观察不一致')
        prop = e['property']
        if prop.startswith('::'):
            pseudo,attribute=prop.split('.',1)
            raw=el.get('pseudos',{}).get(pseudo,{}).get(attribute)
        else:
            raw = {p:el['styles'].get(p) for p in TYPE_PROPS} if prop == 'typography' else el['selector'] if prop == 'element' else el['styles'].get(prop)
        if raw != e['value']:
            raise ValueError('证据值与原始观察不一致')
    ids, names = set(), set()
    for token in model.get('tokens', []):
        if token['category'] not in TYPES or token['type'] != TYPES[token['category']]:
            raise ValueError('Token 分类与类型不一致')
        if token['id'] in ids or (token['category'], token['name']) in names:
            raise ValueError('Token ID 或分类内名称重复')
        ids.add(token['id']); names.add((token['category'],token['name']))
        if not re.fullmatch(r'[a-z][a-z0-9-]*', token['name']):
            raise ValueError('Token 名称必须为小写 kebab-case')
        if token['status'] not in STATUS:
            raise ValueError('Token 证据状态无效')
        if 'paletteGroup' in token and token['paletteGroup'] not in {'brand','accent','neutrals'}:
            raise ValueError('颜色分组无效；不能隐藏未匹配分组的 Token')
        if 'level' in token and (type(token['level']) is not int or token['level']<0):
            raise ValueError('表面层级必须是非负整数；未知时省略')
        value = token['value']
        validate_value(token['category'],value)
        cited = token.get('evidenceIds', [])
        if any(x not in refs for x in cited): raise ValueError('Token 证据引用无效')
        if token['status'] == 'observed' and (not cited or any(refs[x]['value'] != value for x in cited)):
            raise ValueError('实测 Token 没有等值原始证据')
    narrative = [model['overview']] + model.get('components', [])
    metrics=model.get('layoutMetrics',{})
    if not isinstance(metrics,dict) or set(metrics)-{'density','baseUnit','pageMaxWidth','sectionGap','cardPadding','elementGap'}:
        raise ValueError('布局字段无效')
    for key,item in metrics.items():
        if not isinstance(item,dict):raise ValueError('布局字段需要带状态与证据的对象')
        safe_css(item.get('value'))
        if item.get('status')=='observed':
            cited=item.get('evidenceIds',[])
            if not cited or any(x not in refs or refs[x]['value']!=item['value'] for x in cited):
                raise ValueError('实测布局字段没有等值原始证据')
    narrative+=list(metrics.values())
    narrative += [x for items in model['guidelines'].values() for x in items]
    narrative += [x for items in model['sections'].values() for x in items]
    for item in narrative:
        if item.get('status') not in STATUS: raise ValueError('说明缺少证据状态')
        cited = item.get('evidenceIds', [])
        if any(x not in refs for x in cited): raise ValueError('说明的证据引用不存在')
        if item['status'] in {'observed','inferred'} and not cited:
            raise ValueError('实测或推断说明需附证据')
        if 'styles' in item:
            if item.get('kind') not in {'button','input','navigation','card','text'}:
                raise ValueError('未知组件类型')
            if item['status'] == 'observed':
                ref = refs[cited[0]]
                obs = read_json(local_file(run,actual[ref['snapshotId']]['file']))
                el = next(x for x in obs['elements'] if x['selector']==ref['selector'])
                if item['styles'] != el['styles']: raise ValueError('实测组件与原始样式不一致')
    if not model.get('tokens'): raise ValueError('没有可导出的 Token')
    return cov
