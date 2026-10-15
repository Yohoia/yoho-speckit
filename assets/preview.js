'use strict';
const payload=JSON.parse(document.getElementById('payload').textContent), model=payload.model;
const byId=id=>document.getElementById(id), make=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
const value=t=>typeof t.value==='object'?JSON.stringify(t.value):(t.exportValue??t.value);const shownValue=t=>t.displayValue||value(t);
const resourceFunctions=new Set(payload.cssPolicy.resourceFunctions);
function safeValue(v){
  if(typeof v!=='string'||!v.trim()||v.length>3000||/[;{}<>@\n\r]|\/\*|\*\//.test(v))return false;
  const text=v.replace(/"(?:[^"\\]|\\[\s\S])*"|'(?:[^'\\]|\\[\s\S])*'/g,'""').replace(/\\([0-9a-fA-F]{1,6})(?:\r\n|[\t\n\f\r ])?|\\([^\r\n\f])/g,(_,hex,char)=>{
    if(char!==undefined)return char;
    const code=parseInt(hex,16);return code>0&&code<=0x10ffff&&!(code>=0xd800&&code<=0xdfff)?String.fromCodePoint(code):'\ufffd';
  });
  return ![...text.matchAll(/([\w-]+)\s*\(/g)].some(m=>resourceFunctions.has(m[1].toLowerCase()));
}
for(const [key,v]of Object.entries(payload.css)){if(key.startsWith('--')&&safeValue(v))document.documentElement.style.setProperty(key,v);}
let current='DESIGN.md',variant='extended',mobileView='preview';
function selectedFile(){return variant==='compact'?payload.compactFiles[current]:current;}
function shiki(parent,text,theme){
  const el=make('span',text);for(const [key,value]of Object.entries(theme)){el.style.setProperty(key,value);}
  parent.append(el);return el;
}
const plainTheme=theme('#24292E','#E1E4E8');
function theme(light,dark,extra={}){return {'--shiki-light':light,'--shiki-dark':dark,...extra};}
function appendInlineMarkdown(parent,text){
  const pattern=/(`[^`]+`)|(\*\*[^*]+\*\*)/g;let last=0,match;
  while((match=pattern.exec(text))){
    if(match.index>last)shiki(parent,text.slice(last,match.index),plainTheme);
    if(match[1])shiki(parent,match[1],theme('#005CC5','#79B8FF'));
    else shiki(parent,match[1]??match[2],theme('#24292E','#E1E4E8',{'--shiki-light-font-weight':'bold','--shiki-dark-font-weight':'bold'}));
    last=pattern.lastIndex;
  }
  if(last<text.length)shiki(parent,text.slice(last),plainTheme);
}
function appendMarkdownLine(parent,line){
  if(/^#{1,6}\s/.test(line)){shiki(parent,line,theme('#005CC5','#79B8FF',{'--shiki-light-font-weight':'bold','--shiki-dark-font-weight':'bold'}));return;}
  if(/^>\s?/.test(line)){shiki(parent,line,theme('#22863A','#85E89D'));return;}
  const bullet=/^(\s*(?:[-*+]|\d+\.)\s+)(.*)$/.exec(line);
  if(bullet){shiki(parent,bullet[1],theme('#E36209','#FFAB70'));appendInlineMarkdown(parent,bullet[2]);return;}
  appendInlineMarkdown(parent,line);
}
function appendCssLine(parent,line){
  let i=0;
  while(i<line.length){
    const rest=line.slice(i);
    let match;
    if((match=/^\/\*[\s\S]*?\*\//.exec(rest))){shiki(parent,match[0],theme('#6A737D','#6A737D'));i+=match[0].length;continue;}
    if((match=/^--[A-Za-z0-9-]+/.exec(rest))){shiki(parent,match[0],theme('#E36209','#FFAB70'));i+=match[0].length;continue;}
    if((match=/^@[A-Za-z-]+/.exec(rest))){shiki(parent,match[0],theme('#D73A49','#F97583'));i+=match[0].length;continue;}
    if((match=/^#[0-9a-fA-F]{3,8}\b/.exec(rest))){shiki(parent,match[0],theme('#B31D28','#FDAEB7',{'--shiki-light-font-style':'italic','--shiki-dark-font-style':'italic'}));i+=match[0].length;continue;}
    if((match=/^(?:rgba?|hsla?|lab|oklab|linear-gradient|radial-gradient|color-mix)\(/.exec(rest))){shiki(parent,match[0].slice(0,-1),theme('#005CC5','#79B8FF'));shiki(parent,'(',plainTheme);i+=match[0].length;continue;}
    if((match=/^(-?\d+(?:\.\d+)?)(px|rem|em|%|vh|vw|s|ms|fr|ch|deg)?/.exec(rest))&&match[1]){shiki(parent,match[1],theme('#005CC5','#79B8FF'));if(match[2])shiki(parent,match[2],theme('#D73A49','#F97583'));i+=match[0].length;continue;}
    if((match=/^[A-Za-z-]+(?=\s*:)/.exec(rest))){shiki(parent,match[0],plainTheme);i+=match[0].length;continue;}
    if((match=/^\s+/.exec(rest))){shiki(parent,match[0],plainTheme);i+=match[0].length;continue;}
    shiki(parent,rest[0],plainTheme);i++;
  }
}
function appendJsonLine(parent,line){
  const pattern=/("(?:\\.|[^"\\])*"\s*:)|("(?:\\.|[^"\\])*")|(-?\d+(?:\.\d+)?)|(\b(?:true|false|null)\b)/g;let last=0,match;
  while((match=pattern.exec(line))){
    if(match.index>last)shiki(parent,line.slice(last,match.index),plainTheme);
    if(match[1])shiki(parent,match[1],theme('#005CC5','#79B8FF'));
    else if(match[2])shiki(parent,match[2],theme('#032F62','#9ECBFF'));
    else if(match[3])shiki(parent,match[3],theme('#005CC5','#79B8FF'));
    else if(match[4])shiki(parent,match[4],theme('#D73A49','#F97583'));
    last=pattern.lastIndex;
  }
  if(last<line.length)shiki(parent,line.slice(last),plainTheme);
}
function renderCode(text,fileName){
  const pre=byId('code');pre.className='code shiki shiki-themes github-light github-dark';pre.replaceChildren();
  const lines=String(text).split('\n');let fence=null;
  lines.forEach((line,index)=>{
    const row=make('span',undefined,'line');
    if(fileName.endsWith('.md')){
      if(/^```/.test(line)){shiki(row,line,plainTheme);fence=/^```(?:css|scss)?\s*$/.exec(line)&&!fence?'css':null;}
      else if(fence==='css')appendCssLine(row,line);
      else appendMarkdownLine(row,line);
    }else if(fileName.endsWith('.css'))appendCssLine(row,line);
    else if(fileName.endsWith('.json'))appendJsonLine(row,line);
    else shiki(row,line,plainTheme);
    pre.append(row);if(index<lines.length-1)pre.append(document.createTextNode('\n'));
  });
}
function updateCode(){
  renderCode(payload.files[selectedFile()],selectedFile());
  const mobile=matchMedia('(max-width:1023px)').matches;
  document.querySelectorAll('[data-format],[data-mobile-format]').forEach(el=>{
    const isMobile=el.hasAttribute('data-mobile-format');const active=(el.dataset.format||el.dataset.mobileFormat)===current&&(!isMobile||mobileView==='exports');
    el.setAttribute('aria-selected',String(active));el.tabIndex=active?0:-1;
    if(active&&mobile===isMobile)byId('code').setAttribute('aria-labelledby',el.id);
  });
  byId('show-preview').setAttribute('aria-selected',String(mobileView==='preview'));
  byId('show-preview').tabIndex=mobileView==='preview'?0:-1;
  byId('download').setAttribute('aria-label','Download '+selectedFile());
}
function toast(text){byId('toast').textContent=text;byId('toast').classList.remove('hidden');setTimeout(()=>byId('toast').classList.add('hidden'),2300);}
async function copy(text){try{if(navigator.clipboard&&window.isSecureContext)await navigator.clipboard.writeText(text);else{const box=make('textarea',text);box.style.position='fixed';box.style.opacity='0';document.body.append(box);box.select();const ok=document.execCommand('copy');box.remove();if(!ok)throw Error('copy');}toast('已复制');}catch{toast('复制不可用，请在右侧选择文本复制');}}
document.querySelectorAll('[data-format],[data-mobile-format]').forEach(el=>{el.onclick=()=>{current=el.dataset.format||el.dataset.mobileFormat;mobileView='exports';document.body.classList.add('mobile-code');updateCode();};});
for(const selector of ['.tabs','.mobile-tabs']){
  const tabs=[...document.querySelectorAll(selector+' [role="tab"]')];
  tabs.forEach((el,i)=>{el.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].focus();tabs[next].click();}};});
}
byId('compact').onclick=()=>{variant='compact';byId('compact').classList.add('active');byId('extended').classList.remove('active');updateCode();};
byId('extended').onclick=()=>{variant='extended';byId('extended').classList.add('active');byId('compact').classList.remove('active');updateCode();};
byId('copy').onclick=()=>copy(payload.files[selectedFile()]);
byId('download').onclick=()=>{
  const file=selectedFile(),text=payload.files[file],a=make('a');let blobUrl;
  try{blobUrl=URL.createObjectURL(new Blob([text],{type:'application/octet-stream'}));a.href=blobUrl;}
  catch{a.href='data:application/octet-stream;charset=utf-8,'+encodeURIComponent(text);}
  a.download=file;document.body.append(a);a.click();a.remove();
  if(blobUrl)setTimeout(()=>URL.revokeObjectURL(blobUrl),1000);
  toast('已生成下载文件');
};
byId('show-preview').onclick=()=>{mobileView='preview';document.body.classList.remove('mobile-code');updateCode();};
function luminance(value){
  const text=String(value);let rgb=null;
  if(rgb=/^#([0-9a-f]{6})(?:[0-9a-f]{2})?$/i.exec(text))rgb=[parseInt(rgb[1].slice(0,2),16),parseInt(rgb[1].slice(2,4),16),parseInt(rgb[1].slice(4,6),16)];
  else if(rgb=/^rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)/.exec(text))rgb=[+rgb[1],+rgb[2],+rgb[3]];
  else if(rgb=/^oklab\(([\d.]+)%/.exec(text))return +rgb[1]/100;
  if(!rgb)return .5;return (rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722)/255;
}
const tokens=category=>model.tokens.filter(t=>t.category===category);
function showMore(container,items,limit,render,label){
  container.replaceChildren();
  items.forEach((item,index)=>{const row=render(item);if(index>=limit)row.classList.add('hidden','overflow-item');container.append(row);});
  if(items.length>limit){const button=make('button','Show all '+items.length+' '+label,'show-all');button.setAttribute('aria-expanded','false');button.onclick=()=>{const expanded=button.getAttribute('aria-expanded')==='true';container.querySelectorAll('.overflow-item').forEach(x=>x.classList.toggle('hidden',expanded));button.setAttribute('aria-expanded',String(!expanded));button.textContent=expanded?'Show all '+items.length+' '+label:'Show fewer';};if(container.tagName==='TBODY'){const tr=make('tr');const td=make('td');td.colSpan=3;td.append(button);tr.append(td);container.append(tr)}else container.append(button);}
}
function swatch(t){
  const button=make('button',undefined,'swatch');button.setAttribute('aria-label','Copy '+t.label);
  const paint=make('div',undefined,'paint');paint.style.background='var('+t.cssVariable+')';
  const dark=luminance(value(t))>.55;
  paint.append(make('span','Copy','copy-chip'+(dark?' dark':'')));
  const info=make('div',undefined,'swatch-info');info.append(make('span',t.label,'swatch-name'),make('span',shownValue(t),'swatch-value'),make('p',t.role||'用途待解释','swatch-role'));
  button.append(paint,info);button.onclick=()=>copy(value(t));return button;
}
function colorGroup(name,items){
  const group=make('div',undefined,'color-group');const grid=make('div',undefined,'color-grid');
  group.append(make('p',name,'eyebrow'),grid);items.forEach(t=>grid.append(swatch(t)));return group;
}
function renderFonts(){
  const container=byId('fonts');container.replaceChildren();
  tokens('font').forEach((t,index)=>{
    const row=make('div',undefined,'font-row');const family=String(t.value);
    const summary=payload.reference.fonts[t.id];
    const weights=summary.weights.join(', ')||'未确认';
    const sizes=summary.sizes.join(', ')||'未确认';
    const lines=summary.lineHeights.join(', ')||'未确认';
    const tracking=summary.letterSpacings.join(', ')||'未确认';
    const eyebrow=index===0?'Primary':/mono/i.test(family)?'Code':'Secondary';
    const name=make('button',undefined,'font-name');name.style.fontFamily='var('+t.cssVariable+')';name.append(make('span',summary.name));name.title='Click to copy';name.onclick=()=>copy(family);
    row.append(make('span',eyebrow,'font-eyebrow'),name);
    const stats=make('div',undefined,'font-stats');[['Weight',weights],['Sizes',sizes],['Line height',lines],['Letter spacing',tracking],['Fallback',summary.fallback]].forEach(([k,v])=>{const item=make('div',undefined,'font-stat');item.append(make('span',k),make('span',v));stats.append(item)});
    if(summary.renderedFonts?.length){const item=make('div',undefined,'font-stat');item.append(make('span','Rendered'),make('span',summary.renderedFonts.join(', ')));stats.append(item)}
    row.append(stats,make('p',t.role||'用途待解释','font-role'));container.append(row);
  });
  if(!container.children.length)container.append(make('p','未在已采范围确认。','empty'));
}
function renderTypeScale(){
  const items=tokens('typography');byId('type-scale-note').textContent=items.length+' sampled combinations';
  showMore(byId('type-scale'),items,8,t=>{const row=make('div',undefined,'type-row');const meta=make('div',undefined,'type-meta');meta.append(make('span',t.label),make('span',t.value.fontSize+' · '+t.value.fontWeight+' · '+t.value.lineHeight));const sample=make('button','The quick brown fox jumps · 设计语言','type-sample');sample.title='Click to copy font family';sample.onclick=()=>copy(t.value.fontFamily);for(const prop of ['fontFamily','fontSize','fontWeight','lineHeight','letterSpacing','fontFeatureSettings','fontVariationSettings','textTransform'])sample.style[prop==='fontFamily'?'fontFamily':prop]='var('+t.cssVariable+'-'+({fontFamily:'font-family',fontSize:'font-size',fontWeight:'font-weight',lineHeight:'line-height',letterSpacing:'letter-spacing',fontFeatureSettings:'font-feature-settings',fontVariationSettings:'font-variation-settings',textTransform:'text-transform'})[prop]+')';row.append(meta,sample);return row;},'steps');
}
function metricRow(t,kind){
  const tr=make('tr');const label=make('td',t.label);const valueCell=make('td');const button=make('button',value(t),'mono-value');button.onclick=()=>copy(value(t));valueCell.append(button);const preview=make('td');const visual=make('div',undefined,kind==='spacing'?'bar-preview':'radius-window');
  if(kind==='spacing')visual.style.width='var('+t.cssVariable+')';else{const shape=make('div',undefined,'radius-shape');shape.style.borderRadius='var('+t.cssVariable+')';visual.append(shape)}
  preview.append(visual);tr.append(label,valueCell,preview);return tr;
}
function renderMetrics(){
  byId('spacing').replaceChildren();
  for(const metric of payload.reference.metrics){
    const tr=make('tr');if(metric.reason)tr.title=metric.reason;tr.append(make('td',metric.label));const valueCell=make('td');
    if(metric.status==='unknown')valueCell.append(make('span',metric.value,'mono-value'));
    else{const button=make('button',metric.value,'mono-value');button.onclick=()=>copy(metric.value);valueCell.append(button)}
    const preview=make('td');if(metric.status!=='unknown'&&metric.key!=='density'&&/^[\d.]+(?:px|rem|em|%)$/.test(metric.value)){const bar=make('div',undefined,'bar-preview');bar.style.width=metric.value;bar.style.maxWidth='100%';preview.append(bar)}
    tr.append(valueCell,preview);byId('spacing').append(tr);
  }
  showMore(byId('radius'),tokens('radius'),10,t=>metricRow(t,'radius'),'steps');
  const shadows=byId('shadow');shadows.replaceChildren();tokens('shadow').forEach(t=>{const card=make('button',t.label,'elevation-card');card.type='button';card.setAttribute('aria-label','Copy shadow '+t.label);card.style.boxShadow='var('+t.cssVariable+')';card.title=value(t);card.onclick=()=>copy(value(t));shadows.append(card)});if(!shadows.children.length)shadows.append(make('div','未在已采范围确认。','empty'));
}
function renderGuidelines(){
  for(const [key,icon]of [['do','do'],['dont','dont']]){const list=byId(key);list.replaceChildren();for(const item of model.guidelines[key]){const li=make('li');const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('class','guideline-icon '+icon);svg.setAttribute('aria-hidden','true');const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',icon==='do'?'M20 6 9 17l-5-5':'M18 6 6 18M6 6l12 12');path.setAttribute('fill','none');path.setAttribute('stroke','currentColor');path.setAttribute('stroke-width','2');path.setAttribute('stroke-linecap','round');svg.append(path);li.append(svg,make('span',item.text||item.description));list.append(li)}if(!list.children.length)list.append(make('li','尚未形成有依据的建议。','empty'))}
}
document.title=model.siteName+' — Style Reference';const siteLabel=model.siteName.split(/\s+-\s+/).pop()||model.sourceUrl;byId('breadcrumb').textContent=siteLabel;byId('site-title').title=siteLabel;byId('site-name').textContent=siteLabel;byId('tagline').textContent=model.overview.tagline||'基于已采页面的样式参考';byId('overview').textContent=model.overview.description||'摘要尚未解释；请查看下方实测数值，采集依据保存在 evidence 中。';byId('source').href=model.sourceUrl;byId('source-label').textContent=model.sourceUrl.replace(/\/$/,'');

function groupFor(t){
  if(t.paletteGroup)return t.paletteGroup;
  if(t.category==='gradient')return 'accent';
  const match=/^#([0-9a-f]{6})/i.exec(value(t));
  if(match){const channels=[0,2,4].map(i=>parseInt(match[1].slice(i,i+2),16));return Math.max(...channels)-Math.min(...channels)>12?'accent':'neutrals';}
  return 'neutrals';
}
const palette=byId('palette');palette.replaceChildren();
const allColors=model.tokens.filter(t=>['color','gradient'].includes(t.category));
for(const [key,title]of [['brand','Brand'],['accent','Accent'],['neutrals','Neutrals']]){
  const items=allColors.filter(t=>groupFor(t)===key);if(key==='neutrals')items.sort((a,b)=>luminance(value(b))-luminance(value(a)));
  if(items.length)palette.append(colorGroup(title,items));
}
renderTypeScale();renderFonts();renderMetrics();renderGuidelines();

updateCode();
matchMedia('(max-width:1023px)').addEventListener('change',updateCode);
