"""Shared, evidence-preserving presentation summaries for documents and preview."""
import re
from model import validate_value

METRICS = (('density','Density',None),('baseUnit','Base unit','--base-unit'),
    ('pageMaxWidth','Max width','--page-max-width'),('sectionGap','Section gap','--section-gap'),
    ('cardPadding','Card padding','--card-padding'),('elementGap','Element gap','--element-gap'))


def family_name(value):
    return value.split(',')[0].strip().strip('\"\'')


def ordered(values):
    unique = list(dict.fromkeys(values))
    def key(value):
        match = re.match(r'^(-?[\d.]+)', value)
        return (0,float(match[1])) if match else (1,value)
    return sorted(unique,key=key)


def line_ratio(size, height):
    if re.fullmatch(r'[\d.]+px',size) and re.fullmatch(r'[\d.]+px',height) and float(size[:-2]):
        return format(float(height[:-2])/float(size[:-2]),'.4g')
    return height


def font_summary(token, model):
    rows = [t['value'] for t in model['tokens'] if t['category']=='typography'
        and t['value']['fontFamily']==token['value']]
    fallback = ', '.join(token['value'].split(',')[1:]).strip()
    return {'name':token['label'] if token['label']!=token['value'] else family_name(token['value']),
        'renderedFonts':list(dict.fromkeys(f['familyName'] for f in token.get('renderedFonts',[]) if f.get('familyName'))),
        'fallback':fallback or '未确认',
        'weights':ordered([r['fontWeight'] for r in rows]),
        'sizes':ordered([r['fontSize'] for r in rows]),
        'lineHeights':ordered([line_ratio(r['fontSize'],r['lineHeight']) for r in rows]),
        'letterSpacings':ordered([r['letterSpacing'] for r in rows]),
        'features':list(dict.fromkeys(r['fontFeatureSettings'] for r in rows
            if r['fontFeatureSettings']!='normal'))}


def metric_rows(model):
    result=[]
    for key,label,variable in METRICS:
        item=model.get('layoutMetrics',{}).get(key)
        if key=='baseUnit' and not item:continue
        result.append({'key':key,'label':label,'value':item['value'] if item else '未确认',
            'status':item['status'] if item else 'unknown','cssVariable':variable,
            'evidenceIds':item.get('evidenceIds',[]) if item else [],'reason':item.get('reason','') if item else ''})
    return result


def metric_css(model):
    result={}
    for row in metric_rows(model):
        if row['status']=='unknown' or not row['cssVariable']:continue
        try:validate_value('spacing',row['value'])
        except ValueError:continue  # A descriptive range is not an executable CSS length.
        result[row['cssVariable']]=row['value']
    return result


def presentation(model):
    return {'theme':model.get('theme') or 'unknown',
        'metrics':metric_rows(model),
        'fonts':{t['id']:font_summary(t,model) for t in model['tokens'] if t['category']=='font'}}
