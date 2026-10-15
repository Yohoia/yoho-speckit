"""CSS color serialization to sRGB hex; raw evidence is deliberately unchanged."""
import colorsys
import math
import re

FUNCTION = re.compile(r'\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\([^()]*\)',re.I)
HEX = re.compile(r'^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$',re.I)
NAMED = {'transparent':'#00000000','black':'#000000','white':'#ffffff','red':'#ff0000',
         'green':'#008000','blue':'#0000ff','yellow':'#ffff00','gray':'#808080','grey':'#808080',
         'silver':'#c0c0c0','maroon':'#800000','purple':'#800080','fuchsia':'#ff00ff',
         'lime':'#00ff00','olive':'#808000','navy':'#000080','teal':'#008080','aqua':'#00ffff',
         'orange':'#ffa500','rebeccapurple':'#663399'}
GRADIENT = re.compile(r'\b((?:repeating-)?(?:linear|radial|conic)-gradient)\(',re.I)
MODERN = re.compile(r'\b(?:lab|lch|oklab|oklch|color)\(',re.I)


def gradients(value):
    """Locate balanced gradient functions, including multi-layer backgrounds."""
    for match in GRADIENT.finditer(value):
        depth=1;end=match.end();comma=None
        while end<len(value) and depth:
            char=value[end]
            if char==',' and depth==1 and comma is None:comma=end
            depth+=(char=='(')-(char==')');end+=1
        if depth or comma is None:continue
        yield match.start(),end,match[1].lower(),match.end(),comma


def gradient_limitations(value):
    # Missing components borrow channels during interpolation; hex cannot encode them.
    return [value[start:end] for start,end,_,_,_ in gradients(value)
        if re.search(r'\bnone\b',value[start:end],re.I)]


def explicit_gradient_spaces(value):
    """Modern color stops default to Oklab; hex stops would default to sRGB."""
    for start,end,name,body,comma in reversed(list(gradients(value))):
        header=value[body:comma].strip()
        if not MODERN.search(value[body:end]) or re.search(r'\bin\s+[\w-]+',header,re.I):continue
        # A first argument with geometry is a header; otherwise it is the first stop.
        geometry = (r'^(?:to\b|[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:deg|grad|rad|turn)\b|0\s*$)' if 'linear' in name else
            r'^(?:circle\b|ellipse\b|(?:closest|farthest)-(?:side|corner)\b|at\b|[\d.]+(?:px|%|em|rem)(?=\s|$))' if 'radial' in name else r'^(?:from\b|at\b)')
        if re.match(geometry,header,re.I):
            value=value[:comma]+' in oklab'+value[comma:]
        elif re.match(r'^(?:#[\da-f]+\b|(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(|[a-z][\w-]*(?=\s|$))',header,re.I):
            value=value[:body]+'in oklab, '+value[body:]
        else:
            # Unrecognized geometry is retained by normalize_css instead of guessed.
            return None
    return value


def clamp(v):
    return min(1.,max(0.,v))


def number(value, percent_scale=1.):
    if value.lower()=='none':return 0.
    return float(value[:-1])*percent_scale/100 if value.endswith('%') else float(value)


def hue(value):
    for suffix,scale in [('turn',360),('grad',.9),('rad',180/math.pi),('deg',1)]:
        if value.endswith(suffix):return float(value[:-len(suffix)])*scale
    return number(value)


def gamma(v):
    sign=-1 if v<0 else 1
    v=abs(v)
    return sign*(12.92*v if v<=.0031308 else 1.055*v**(1/2.4)-.055)


def linear(v):
    sign=-1 if v<0 else 1
    v=abs(v)
    return sign*(v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4)


def xyz_rgb(xyz):
    x,y,z=xyz
    return list(map(gamma,[3.2409699419*x-1.5373831776*y-.4986107603*z,
        -.9692436363*x+1.8759675015*y+.0415550574*z,
        .0556300797*x-.2039769589*y+1.0569715142*z]))


def d50_d65(xyz):
    x,y,z=xyz
    return [.9554734215*x-.0230984549*y+.0632592432*z,
        -.0283697093*x+1.0099953981*y+.0210414412*z,
        .0123140149*x-.0205076493*y+1.3303659262*z]


def rgba(value):
    """Return normalized channels and whether conversion leaves the sRGB gamut."""
    text=value.strip().lower()
    if text in NAMED:text=NAMED[text]
    match=HEX.fullmatch(text)
    if match:
        digits=match[1]
        if len(digits)<5:digits=''.join(x*2 for x in digits)
        if len(digits)==6:digits+='ff'
        return tuple(int(digits[i:i+2],16)/255 for i in range(0,8,2)),False
    match=re.fullmatch(r'([a-z-]+)\(([^()]*)\)',text)
    if not match:return None,False
    name,body=match.groups()
    try:
        if '/' in body:
            body,alpha_text=body.rsplit('/',1);alpha=number(alpha_text.strip())
        else:alpha=1.
        parts=body.replace(',',' ').split()
        if len(parts)==4 and name in {'rgb','rgba','hsl','hsla'}:alpha=number(parts.pop())
        if name in {'rgb','rgba'} and len(parts)==3:
            rgb=[number(p,255)/255 for p in parts]
        elif name in {'hsl','hsla','hwb'} and len(parts)==3:
            h=hue(parts[0])%360/360
            if name=='hwb':
                white,black=number(parts[1]),number(parts[2])
                rgb=[white/(white+black)]*3 if white+black>=1 else [x*(1-white-black)+white for x in colorsys.hsv_to_rgb(h,1,1)]
            else:rgb=list(colorsys.hls_to_rgb(h,number(parts[2]),number(parts[1])))
        elif name in {'lab','lch'} and len(parts)==3:
            light=number(parts[0],100);a=number(parts[1],125 if name=='lab' else 150)
            b=number(parts[2],125) if name=='lab' else hue(parts[2])
            if name=='lch':a,b=a*math.cos(math.radians(b)),a*math.sin(math.radians(b))
            fy=(light+16)/116; f=[fy+a/500,fy,fy-b/200]
            epsilon,kappa=216/24389,24389/27
            white=[.3457/.3585,1.,(1-.3457-.3585)/.3585]
            xyz=[(v**3 if v**3>epsilon else (116*v-16)/kappa)*w for v,w in zip(f,white)]
            rgb=xyz_rgb(d50_d65(xyz))
        elif name in {'oklab','oklch'} and len(parts)==3:
            light=number(parts[0]);a=number(parts[1],.4)
            b=number(parts[2],.4) if name=='oklab' else hue(parts[2])
            if name=='oklch':a,b=a*math.cos(math.radians(b)),a*math.sin(math.radians(b))
            l=(light+.3963377774*a+.2158037573*b)**3
            m=(light-.1055613458*a-.0638541728*b)**3
            s=(light-.0894841775*a-1.2914855480*b)**3
            rgb=list(map(gamma,[4.0767416621*l-3.3077115913*m+.2309699292*s,
                -1.2684380046*l+2.6097574011*m-.3413193965*s,
                -.0041960863*l-.7034186147*m+1.707614701*s]))
        elif name=='color' and len(parts)==4:
            space=parts.pop(0);rgb=[number(p) for p in parts]
            if space=='srgb-linear':rgb=list(map(gamma,rgb))
            elif space in {'display-p3','display-p3-linear'}:
                r,g,b=rgb if space.endswith('-linear') else list(map(linear,rgb))
                rgb=list(map(gamma,[1.2249401763*r-.2249401763*g,
                    -.0420569547*r+1.0420569547*g,
                    -.0196375546*r-.0786360456*g+1.0982736001*b]))
            elif space in {'xyz','xyz-d65','xyz-d50'}:rgb=xyz_rgb(d50_d65(rgb) if space=='xyz-d50' else rgb)
            elif space!='srgb':return None,False
        else:return None,False
        if not all(math.isfinite(v) for v in [*rgb,alpha]):return None,False
        clipped=any(v < -.00001 or v > 1.00001 for v in rgb)
        return (*map(clamp,rgb),clamp(alpha)),clipped
    except (ValueError,OverflowError,ZeroDivisionError):return None,False


def to_hex(value):
    if not isinstance(value,str):return value
    channels,_=rgba(value)
    if channels is None:return value
    encoded=[int(math.floor(v*255+.5)) for v in channels]
    return '#'+''.join(f'{v:02x}' for v in encoded[:3])+ (f'{encoded[3]:02x}' if encoded[3]!=255 else '')


def normalize_css(value):
    """Convert colors within gradients/shadows without changing the CSS operation."""
    if not isinstance(value,str):return value
    if gradient_limitations(value):return value
    prepared=explicit_gradient_spaces(value)
    if prepared is None:return value
    value=prepared
    whole=to_hex(value)
    if whole!=value:return whole
    result=FUNCTION.sub(lambda match:to_hex(match[0]),value)
    for name,hex_value in NAMED.items():
        result=re.sub(r'(?<![\w-])'+name+r'(?![\w-])',hex_value,result,flags=re.I)
    return result


def conversion_info(value):
    if not isinstance(value,str):return {}
    value=value.strip()
    # A hex operand does not resolve an enclosing color operation. Inspect balanced
    # functions so relative/nested colors cannot disappear behind a simple regex.
    wrappers={'linear-gradient','radial-gradient','conic-gradient','repeating-linear-gradient',
        'repeating-radial-gradient','repeating-conic-gradient'}
    color_functions={'rgb','rgba','hsl','hsla','hwb','lab','lch','oklab','oklch','color'}
    operations=[]
    for match in re.finditer(r'\b([a-z][\w-]*)\(',value,re.I):
        depth=1;end=match.end()
        while end<len(value) and depth:
            depth+=(value[end]=='(')-(value[end]==')');end+=1
        operations.append((match[1].lower(),value[match.start():end],match.start(),end))
    samples=[value] if rgba(value)[0] is not None else [text for name,text,_,_ in operations if name in color_functions]
    unsupported=[sample for sample in samples if rgba(sample)[0] is None]
    unsupported.extend(gradient_limitations(value))
    if explicit_gradient_spaces(value) is None:unsupported.append(value)
    for name,text,start,end in operations:
        if name not in wrappers|color_functions|{'calc','min','max','clamp'} or (
                start==0 and end==len(value.strip()) and name not in wrappers|color_functions):
            unsupported.append(text)
    if not samples and not re.search(r'#[0-9a-f]{3,8}\b',normalize_css(value),re.I):unsupported=[value]
    clipped=[sample for sample in samples if rgba(sample)[1]]
    return {'status':'unsupported' if unsupported else 'converted',
            'encoding':None if unsupported else 'sRGB hex (8-bit channels)',
            'gamutClipped':None if unsupported else bool(clipped),
            'unsupportedSourceColors':list(dict.fromkeys(unsupported)),'clippedSourceColors':clipped}
