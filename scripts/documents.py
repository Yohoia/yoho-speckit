"""Refero-shaped Markdown, clipped before Imagery for this Skill's delivery contract."""
from colors import normalize_css
from reference import family_name, font_summary, line_ratio, metric_rows


def cell(value):
    return str(value).replace('|','\\|').replace('\n',' ').replace('`','\\`')


def table(headers, rows):
    lines=['| '+' | '.join(headers)+' |','|'+'|'.join('---' for h in headers)+'|']
    lines.extend('| '+' | '.join(cell(v) for v in row)+' |' for row in rows)
    return lines+[''] if rows else ['未在已采范围确认。','']


def paint(token):
    return 'Gradient' if token['category']=='gradient' else normalize_css(token['value'])


def role(item):
    return item.get('role') or item.get('description') or '用途未确认'


def summary_styles(styles):
    parts=[]
    if styles.get('backgroundColor'):parts.append('Background '+normalize_css(styles['backgroundColor']))
    if 'gradient(' in styles.get('backgroundImage',''):parts.append('Background image Gradient')
    if styles.get('color'):parts.append('Text '+normalize_css(styles['color']))
    if styles.get('fontFamily'):
        parts.append('Font '+family_name(styles['fontFamily'])+' '+styles.get('fontSize','未确认')
            +' / '+styles.get('fontWeight','未确认'))
    for key,label in [('lineHeight','Line height'),('letterSpacing','Letter spacing')]:
        if styles.get(key):parts.append(label+' '+styles[key])
    for prefix,labels in [('padding','Padding'),('border','Radius')]:
        properties = ['padding'+p for p in ('Top','Right','Bottom','Left')] if prefix=='padding' else [
            'border'+p+'Radius' for p in ('TopLeft','TopRight','BottomRight','BottomLeft')]
        values=[styles.get(p) for p in properties]
        if all(values):
            if len(set(values))==1:values=values[:1]
            parts.append(labels+' '+' '.join(values))
    borders=[]
    for side in ('Top','Right','Bottom','Left'):
        if styles.get('border'+side+'Width') not in {None,'0','0px'}:
            borders.append((side,' '.join(styles.get('border'+side+p,'未确认') for p in ('Width','Style'))
                +' '+normalize_css(styles.get('border'+side+'Color','未确认'))))
    if len(borders)==4 and len({value for side,value in borders})==1:parts.append('Border '+borders[0][1])
    else:parts.extend(side+' border '+value for side,value in borders)
    if styles.get('boxShadow') not in {None,'none'}:parts.append('Shadow '+normalize_css(styles['boxShadow']))
    return '; '.join(parts)+'.' if parts else '样式组合未确认。'


def document(model, compact, variable):
    overview=model['overview']
    lines=['# '+model['siteName']+' — Style Reference',
        '> '+(overview.get('tagline') or '基于已采页面的样式参考'),'','**Theme:** '+str(model.get('theme') or 'unknown'),'',
        '测量值已归一化；名称、用途和建议属于解释。字体摘要独立列示，不按位置配对；字体文件未随产物分发。','',
        overview['description'],'','Source: '+model['sourceUrl'],'']
    tokens=lambda category:[t for t in model['tokens'] if t['category']==category]
    lines+=['## '+('Colors' if compact else 'Tokens — Colors'),'']
    colors=tokens('color')+tokens('gradient')
    rows=[(t['label'],paint(t),role(t)) if compact else (t['label'],paint(t),variable(t),role(t)) for t in colors]
    lines+=table(['Name','Value','Role'] if compact else ['Name','Value','Token','Role'],rows)

    lines+=['## '+('Typography' if compact else 'Tokens — Typography'),'']
    for t in tokens('font'):
        s=font_summary(t,model)
        title=s['name']+' — '+role(t)
        if not compact:title+=' · '+variable(t)
        lines+=['### '+title,'','- **Substitute:** '+s['fallback']]
        if s['renderedFonts']:lines.append('- **Rendered fonts observed:** '+', '.join(s['renderedFonts']))
        for key,label in [('weights','Weights'),('sizes','Sizes'),('lineHeights','Line height'),('letterSpacings','Letter spacing')]:
            lines.append('- **'+label+':** '+(', '.join(s[key]) or '未确认'))
        if not compact and s['features']:lines.append('- **OpenType features:** '+', '.join(s['features']))
        lines+=['- **Role:** '+role(t),'']
    if not tokens('font'):lines+=['未在已采范围确认字体。','']
    lines+=['### Type Scale','']
    headers=['Role','Family','Weight','Size','Line Height','Letter Spacing']+([] if compact else ['Token'])
    rows=[]
    for t in tokens('typography'):
        v=t['value'];row=[t['label'],family_name(v['fontFamily']),v['fontWeight'],v['fontSize'],
            line_ratio(v['fontSize'],v['lineHeight']),v['letterSpacing']]
        if not compact:row.append(variable(t)+'-font-size')
        rows.append(row)
    lines+=table(headers,rows)

    lines+=['## '+('Spacing & Layout' if compact else 'Tokens — Spacing & Shapes'),'']
    metrics={row['key']:row for row in metric_rows(model)}
    for key in ('baseUnit','density'):
        if key in metrics:lines+=['**'+metrics[key]['label']+':** '+metrics[key]['value'],'']
    if not compact:
        lines+=['### Spacing Scale','']
        lines+=table(['Name','Value','Token'],[(t['label'],t['value'],variable(t)) for t in tokens('spacing')])
    else:
        lines.extend('- **'+label+':** '+metrics[key]['value'] for key,label in
            [('pageMaxWidth','Page max-width'),('sectionGap','Section gap'),('cardPadding','Card padding'),('elementGap','Element gap')])
        lines.append('')
    lines+=['### Border Radius','']
    radii=[(t['label'],t['value']) for t in tokens('radius')]
    if compact:lines+=['- **'+cell(name)+':** '+value for name,value in radii] or ['未在已采范围确认。']
    else:lines+=table(['Element','Value'],radii)
    lines.append('')
    if not compact:
        if tokens('shadow'):
            lines+=['### Shadows','']+table(['Name','Value','Token'],[
                (t['label'],normalize_css(t['value']),variable(t)) for t in tokens('shadow')])
        lines+=['### Layout','']
        lines.extend('- **'+label+':** '+metrics[key]['value'] for key,label in
            [('pageMaxWidth','Page max-width'),('sectionGap','Section gap'),('cardPadding','Card padding'),('elementGap','Element gap')])
        lines.append('')

    lines+=['## Components','']
    for component in model['components']:
        lines+=['### '+component['name'],'','**Role:** '+role(component),'']
        if component.get('description') and component['description']!=role(component):lines+=[component['description'],'']
        lines+=[summary_styles(component.get('styles',{})),'']
    if not model['components']:lines+=['未在已采范围确认代表组件。','']
    lines+=["## Do's and Don'ts",'']
    for key,title in [('do','Do'),('dont',"Don't")]:
        lines+=['### '+title,'']
        lines+=['- '+(item.get('text') or item.get('description') or '建议未确认') for item in model['guidelines'][key]] or ['尚未形成有依据的建议。']
        lines.append('')

    def surfaces():
        rows=[(t.get('level','—'),t['label'],paint(t),role(t)) for t in tokens('surface')]
        if compact:return ['## Surfaces','']+['- **'+cell(t['label'])+':** '+paint(t)+' — '+role(t) for t in tokens('surface')]+[''] if rows else ['## Surfaces','','未在已采范围确认。','']
        return ['## Surfaces','']+table(['Level','Name','Value','Purpose'],rows)
    def elevation():
        return ['## Elevation','']+(['- **'+cell(t['label'])+':** '+normalize_css(t['value']) for t in tokens('shadow')] or ['未在已采范围确认。'])+['']
    lines+=(elevation()+surfaces()) if compact else (surfaces()+elevation())
    return '\n'.join(lines).rstrip()+'\n'
