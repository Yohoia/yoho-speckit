"""Executable CSS value boundary; raw declarations remain untouched in evidence."""
import re

# Export this policy to the offline preview so both runtimes reject the same functions.
RESOURCE_FUNCTIONS = frozenset({
    'url', 'src', 'image', 'image-set', '-webkit-image-set', 'cross-fade',
    '-webkit-cross-fade', 'element', '-moz-element', 'paint', 'expression',
})
STRINGS = re.compile(r'''"(?:[^"\\]|\\[\s\S])*"|'(?:[^'\\]|\\[\s\S])*' '''.strip())
ESCAPE = re.compile(r'\\([0-9a-fA-F]{1,6})(?:\r\n|[\t\n\f\r ])?|\\([^\r\n\f])')


def safe_css(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 3000:
        raise ValueError('CSS 值为空、过长或类型错误')
    if re.search(r'[;{}<>@\n\r]|/\*|\*/', value):
        raise ValueError('Token 必须为单个无外部资源的 CSS 值')
    # Quoted font names are literals; CSS escapes in identifiers are significant.
    text = STRINGS.sub('""', value)
    def decode(match):
        if match[2] is not None:return match[2]
        code=int(match[1],16)
        return chr(code) if 0<code<=0x10ffff and not 0xd800<=code<=0xdfff else '\ufffd'
    text=ESCAPE.sub(decode,text)
    functions={name.lower() for name in re.findall(r'([\w-]+)\s*\(',text)}
    if functions & RESOURCE_FUNCTIONS:
        raise ValueError('Token 必须为单个无外部资源的 CSS 值')
    return value
