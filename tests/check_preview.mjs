/** Actual offline interactions, using a clipboard sink to preserve the user's clipboard. */
import assert from 'node:assert/strict';
import {readFile,mkdir} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {launch,sleep} from '../scripts/cdp.mjs';

const request=JSON.parse(await readFile(process.argv[2],'utf8'));
const browser=await launch(),cdp=browser.cdp,errors=[];
const unsubscribe=cdp.on(m=>{if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails);});
try {
  await cdp.send('Page.enable');await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await cdp.send('Page.navigate',{url:pathToFileURL(request.preview).href});await sleep(250);
  await cdp.evaluate("window.clipboardWrites=[];Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{clipboardWrites.push(text)}}});");
  const unsafe=await cdp.evaluate(JSON.stringify(request.unsafe)+'.map(s=>safeValue(s))');
  assert(unsafe.every(value=>value===false),'preview must reject resource functions');
  assert.equal(await cdp.evaluate('safeValue(\'"URL(font)", sans-serif\')'),true);
  await mkdir(request.downloads,{recursive:true});
  await cdp.send('Page.setDownloadBehavior',{behavior:'allow',downloadPath:request.downloads});
  let variants=0,downloads=0;
  for(const format of ['DESIGN.md','tailwind.css','tokens.css','design-tokens.json'])for(const variant of ['compact','extended']){
    const select='document.querySelector('+JSON.stringify('[data-format="'+format+'"]')+').click();document.getElementById('+JSON.stringify(variant)+').click();';
    const result=await cdp.evaluate('(()=>{'+select+"document.getElementById('copy').click();document.getElementById('download').click();return {file:selectedFile(),text:payload.files[selectedFile()],code:document.getElementById('code').textContent};})()");
    assert.equal(result.text,result.code);assert.equal(await cdp.evaluate('clipboardWrites.at(-1)'),result.text);variants++;
    let text;
    for(let i=0;i<30;i++){try{text=await readFile(request.downloads+'/'+result.file,'utf8');if(text===result.text)break;}catch{}await sleep(50);}
    assert.equal(text,result.text);downloads++;
  }
  const themes=[];
  for(const scheme of ['light','dark']){
    await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:scheme}]});
    themes.push(await cdp.evaluate("({background:getComputedStyle(document.querySelector('.exports')).backgroundColor,colors:[...new Set([...document.querySelectorAll('#code span')].filter(e=>!e.children.length&&e.textContent.trim()).map(e=>getComputedStyle(e).color))]})"));
  }
  assert.deepEqual(themes[0],themes[1],'fixed light code panel needs matching highlighting');
  for(const width of [320,390,768,1024,1440]){
    await cdp.send('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:false});
    const result=await cdp.evaluate("(()=>{document.getElementById('mobile-tokens').click();return {pageWidth:document.body.scrollWidth,buttons:[...document.querySelectorAll('.toolbar button')].map(e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width,height:r.height}})};})()");
    assert(result.pageWidth<=width);
    assert(result.buttons.every(r=>r.left>=0&&r.right<=width&&r.width>0&&r.height>0),JSON.stringify({width,result}));
  }
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  const expected=await cdp.evaluate("(()=>{clipboardWrites=[];const target=document.querySelector('.elevation-card');const controls=[...document.querySelectorAll('button,a[href],[tabindex]')].filter(e=>e.tabIndex>=0&&e.getClientRects().length);const previous=controls[controls.indexOf(target)-1];previous.focus();return target.title;})()");
  for(const [key,code,id] of [['Tab','Tab',9],['Enter','Enter',13],[' ','Space',32]]){
    const text=key===' '?' ':key==='Enter'?'\r':undefined;
    await cdp.send('Input.dispatchKeyEvent',{type:text?'keyDown':'rawKeyDown',key,code,windowsVirtualKeyCode:id,...(text?{text,unmodifiedText:text}:{})});
    await cdp.send('Input.dispatchKeyEvent',{type:'keyUp',key,code,windowsVirtualKeyCode:id});
    await sleep(30);
    if(key==='Tab')assert.equal(await cdp.evaluate("document.activeElement.classList.contains('elevation-card')"),true);
  }
  assert.deepEqual(await cdp.evaluate('clipboardWrites.slice(-2)'),[expected,expected]);
  // Bypass the value guard deliberately to check the independent offline CSP boundary.
  await cdp.evaluate("window.violations=[];addEventListener('securitypolicyviolation',e=>violations.push(e.effectiveDirective));const image=document.createElement('img');image.src="+JSON.stringify(request.pixel)+";document.body.append(image);");
  await sleep(200);assert((await cdp.evaluate('violations')).includes('img-src'));
  assert.equal(errors.length,0,JSON.stringify(errors));
  console.log(JSON.stringify({variants,downloads,keyboardCopies:2,themes}));
} finally {unsubscribe();cdp.close();await browser.stop();}
