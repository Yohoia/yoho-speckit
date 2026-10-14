(options = {}) => {
  const properties = [
    'color', 'backgroundColor', 'backgroundImage', 'opacity', 'fontFamily',
    'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing', 'fontFeatureSettings',
    'fontVariationSettings', 'textTransform', 'textDecorationLine', 'textAlign',
    'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'marginTop',
    'marginRight', 'marginBottom', 'marginLeft', 'gap', 'rowGap', 'columnGap',
    'borderTopWidth', 'borderTopStyle', 'borderTopColor', 'borderRightWidth',
    'borderRightColor', 'borderBottomWidth', 'borderBottomColor', 'borderLeftWidth',
    'borderLeftColor', 'borderTopLeftRadius', 'borderTopRightRadius',
    'borderBottomRightRadius', 'borderBottomLeftRadius', 'boxShadow', 'display',
    'position', 'width', 'height', 'minWidth', 'maxWidth', 'gridTemplateColumns',
    'gridTemplateRows', 'alignItems', 'justifyContent', 'transitionProperty',
    'transitionDuration', 'transitionTimingFunction', 'animationName',
    'animationDuration', 'animationTimingFunction', 'backdropFilter', 'outlineColor',
    'outlineWidth', 'outlineStyle', 'outlineOffset', 'fill', 'stroke'
  ];
  const gaps = [];
  const maxElements = Math.max(1, Math.min(5000, Number(options.maxElements) || 600));
  const sensitive = /token|secret|password|signature|session|authorization|api.?key|^code$|jwt/i;
  const safeUrl = value => {
    try {
      if (!value) return null;
      const u = new URL(value, location.href);
      if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password) return null;
      if ([...u.searchParams.keys()].some(k => sensitive.test(k))) return null;
      u.hash = ''; return u.href;
    } catch { return null; }
  };
  const selectorCache=new WeakMap();
  const selector = el => {
    if(selectorCache.has(el))return selectorCache.get(el);
    if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1) {const value='#'+CSS.escape(el.id);selectorCache.set(el,value);return value;}
    const parts = [];
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const name = n.tagName.toLowerCase();
      const index = n.parentElement ? [...n.parentElement.children].indexOf(n) + 1 : 1;
      parts.unshift(name + ':nth-child(' + index + ')');
      if (n === document.documentElement) break;
    }
    const value=parts.join(' > ');selectorCache.set(el,value);return value;
  };
  const css = (el, pseudo) => {
    const computed = getComputedStyle(el, pseudo);
    const result = Object.fromEntries(properties.map(p => [p, computed[p] || '']));
    if (pseudo) result.content = computed.content;
    return result;
  };
  const candidates = [document.documentElement, document.body, ...document.body.querySelectorAll('*')].filter(el => {
    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'META', 'LINK'].includes(el.tagName)) return false;
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  });
  const priority = el => el === document.documentElement || el === document.body ? 0 :
    el.matches('h1,h2,h3,nav,button,input,textarea,select,a,[role=button]') ? 1 : el.matches('svg,path,circle,rect,polygon') ? 3 : 2;
  candidates.sort((a,b) => priority(a)-priority(b));
  const elements = candidates.slice(0, maxElements).map((el, index) => {
    const rect = el.getBoundingClientRect(), tag = el.tagName.toLowerCase();
    // Leaf text avoids duplicate container copy; form values are never collected.
    const text = ['input', 'textarea', 'select', 'option'].includes(tag) ? '' :
      [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').trim().slice(0, 120);
    const pseudos = {};
    for (const name of ['::before', '::after']) {
      const style = css(el, name);
      if (style.content && !['none', 'normal'].includes(style.content)) pseudos[name] = style;
    }
    const styleDeclarations = {};
    for (const name of el.style) {
      const value = el.style.getPropertyValue(name).trim();
      if (value) styleDeclarations[name] = value;
    }
    const ancestors=[];for(let parent=el.parentElement;parent;parent=parent.parentElement)ancestors.push(selector(parent));
    const buttonLike=tag==='a' && (el.getAttribute('role')==='button' || el.matches('[class*=button],[class*=btn]') ||
      (getComputedStyle(el).backgroundColor!=='rgba(0, 0, 0, 0)' && parseFloat(getComputedStyle(el).paddingLeft)>0));
    return { id: 'e' + (index + 1), selector: selector(el), tag, ancestorSelectors:ancestors,
      componentHint:buttonLike?'button':undefined,
      role: el.getAttribute('role') || (tag === 'button' ? 'button' : tag === 'a' ? 'link' : ''),
      text, styles: css(el), pseudos,
      styleDeclarations: Object.keys(styleDeclarations).length ? styleDeclarations : undefined,
      rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
      inViewport: rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth,
      hasText: !!text, childCount: el.children.length };
  });
  const sourceVariables = [], sourceRules = [], inaccessibleStylesheets = [];
  let declarationCount = 0, declarationsTruncated = false;
  const visit = (rules, href, context = '') => {
    for (const rule of rules) {
      if (declarationCount >= 12000) { declarationsTruncated = true; return; }
      if (rule.style) {
        const values = {};
        for (const name of rule.style) {
          const value = rule.style.getPropertyValue(name).trim();
          if (name.startsWith('--')) sourceVariables.push({name, value, selector: rule.selectorText || '', href, context});
          if (name.startsWith('--') || /^(color|fill|stroke|font|line-height|letter-spacing|background|border|box-shadow|gap|padding|margin|max-width|transition|animation)/.test(name)) values[name] = value;
        }
        if (Object.keys(values).length) {
          sourceRules.push({selector: rule.selectorText || '', href, context, values}); declarationCount++;
        }
      }
      if (rule.cssRules) visit(rule.cssRules, href, [context, rule.conditionText || ''].filter(Boolean).join(' / '));
    }
  };
  for (const sheet of document.styleSheets) {
    try { visit(sheet.cssRules, safeUrl(sheet.href) || 'inline'); }
    catch { inaccessibleStylesheets.push(safeUrl(sheet.href) || 'unreadable'); }
  }
  const links = [...new Map([...document.querySelectorAll('a[href]')].map(el => {
    const url = safeUrl(el.href);
    return [url, {url, label: (el.innerText || '').trim().slice(0, 100), inNavigation: !!el.closest('nav,header,[role="navigation"]')}];
  }).filter(([url]) => url)).values()].slice(0, 300);
  const rootStyle = getComputedStyle(document.documentElement);
  const rootVariables = {};
  for (const variable of sourceVariables) {
    const value = rootStyle.getPropertyValue(variable.name).trim();
    if (value) rootVariables[variable.name] = value;
  }
  let declaredFonts=[];
  try { declaredFonts=Array.from(document.fonts).map(f=>({family:f.family,weight:f.weight,style:f.style,status:f.status})).slice(0,100); }
  catch { gaps.push('font declaration enumeration unavailable'); }
  const shadowRoots=candidates.filter(el=>el.shadowRoot).length;
  if(shadowRoots)gaps.push('Shadow DOM contents require separate inspection');
  if(document.querySelectorAll('iframe').length)gaps.push('iframe contents not included in this document probe');
  return {
    schemaVersion: 1, url: safeUrl(location.href), title: document.title,
    capturedAt: new Date().toISOString(), method: 'dom-computed-style',
    viewport: {width: innerWidth, height: innerHeight, dpr: devicePixelRatio},
    scroll: {x: scrollX, y: scrollY, height: document.documentElement.scrollHeight},
    theme: {colorScheme: rootStyle.colorScheme, rootBackground: rootStyle.backgroundColor},
    fontStatus: document.fonts?.status || 'unknown',
    declaredFonts, gaps, shadowRoots,
    sampling: {total: candidates.length, captured: elements.length, truncated: candidates.length > maxElements, declarationsTruncated},
    elements, links, sourceVariables, rootVariables, sourceRules, inaccessibleStylesheets,
    canvasCount: document.querySelectorAll('canvas').length
  };
}
