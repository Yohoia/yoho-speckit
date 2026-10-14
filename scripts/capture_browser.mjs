#!/usr/bin/env node
/** Single local Chrome/CDP backend. Writes staged snapshots; Python commits validated evidence. */
import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { launch, chromePath, sleep } from './cdp.mjs';

if (Number(process.versions.node.split('.')[0]) < 22) throw new Error('Node.js 22+ required');
const hash = value => createHash('sha256').update(value).digest('hex');
const args=process.argv.slice(2), options={};
for (let i=0;i<args.length;i++) {
  const name=args[i];
  if (name==='--doctor') { options.doctor=true; continue; }
  if (!['--request','--out','--chrome'].includes(name) || !args[i+1] || args[i+1].startsWith('--')) throw new Error('Unknown/incomplete option: '+name);
  options[name.slice(2)]=args[++i];
}
if (options.doctor) {
  let chrome=null; try { chrome=await chromePath(options.chrome); } catch {}
  console.log(JSON.stringify({node:process.versions.node,nodeSupported:true,chrome,backend:'local-cdp'}));
} else {
  await main().catch(error => { console.error(JSON.stringify({status:'error',message:error.message})); process.exitCode=2; });
}

function publicUrl(value,base) {
  if (!value) return '';
  try {
    const u=new URL(value,base);
    if (!['http:','https:'].includes(u.protocol) || u.username || u.password || [...u.searchParams.keys()].some(k=>/token|secret|password|signature|session|authorization|api.?key|^code$|jwt/i.test(k))) return '';
    u.hash='';return u.href;
  } catch { return ''; }
}

async function main() {
  if (!options.request || !options.out) throw new Error('--request and --out required');
  const request=JSON.parse(await readFile(options.request,'utf8')), out=path.resolve(options.out);
  const probe=await readFile(fileURLToPath(new URL('../assets/probe.js',import.meta.url)),'utf8');
  await mkdir(path.join(out,'styles'),{recursive:true});
  const result={snapshots:[],failures:[]};
  const saveResult=async()=>{await writeFile(path.join(out,'result.json.tmp'),JSON.stringify(result));await rename(path.join(out,'result.json.tmp'),path.join(out,'result.json'));};
  const browser=await launch(options.chrome), cdp=browser.cdp;
  const shutdown=async()=>{cdp.close();await browser.stop();};
  const interrupt=()=>{shutdown().finally(()=>process.exit(130));};
  process.once('SIGINT',interrupt);process.once('SIGTERM',interrupt);
  let health={errors:[],failures:[]}, sheets=new Map(), navigations=0;
  const unsubscribe=cdp.on(message=>{
    const p=message.params||{};
    if(message.method==='CSS.styleSheetAdded') sheets.set(p.header.styleSheetId,p.header);
    if(message.method==='Runtime.exceptionThrown') health.errors.push('page exception: '+(p.exceptionDetails?.text||'unknown'));
    if(message.method==='Log.entryAdded' && p.entry.level==='error') health.errors.push('browser log error: '+p.entry.source);
    if(message.method==='Network.responseReceived' && p.response.status>=400) health.failures.push({url:publicUrl(p.response.url),status:p.response.status});
    if(message.method==='Network.loadingFailed' && !p.canceled) health.failures.push({error:p.errorText});
    if(message.method==='Inspector.targetCrashed') health.errors.push('renderer crashed');
    if(message.method==='Page.frameNavigated' && !p.frame.parentId) navigations++;
  });
  try {
    for(const method of ['Page.enable','Runtime.enable','Network.enable','DOM.enable','CSS.enable','Log.enable','Inspector.enable']) await cdp.send(method);
    const version=await cdp.send('Browser.getVersion');
    for(const job of request.jobs) {
      health={errors:[],failures:[]};sheets=new Map();navigations=0;
      try {
        if (!publicUrl(job.url) || !request.allowedOrigins.includes(new URL(job.url).origin)) throw new Error('URL outside authorized scope');
        await cdp.send('Emulation.setDeviceMetricsOverride',{width:job.width,height:job.height,deviceScaleFactor:1,mobile:false});
        await cdp.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:-1,y:-1});
        // Blank navigation resets the document and keeps no user profile/cookies.
        await cdp.send('Page.navigate',{url:'about:blank'});
        for(let attempt=0;attempt<40;attempt++) {
          if(await cdp.evaluate('location.href')==='about:blank')break;
          if(attempt===39)throw new Error('Document reset timeout');
          await sleep(50);
        }
        const navigation=await cdp.send('Page.navigate',{url:job.url},30000);
        if(navigation.errorText) throw new Error('Navigation failed: '+navigation.errorText);
        const deadline=Date.now()+request.readyTimeout;
        let ready;
        while(Date.now()<deadline) {
          ready=await cdp.evaluate(`({state:document.readyState,fonts:document.fonts?.status||'unknown',images:[...document.images].filter(i=>!i.complete||!i.naturalWidth).length,url:location.href})`);
          if(ready?.state==='complete' && ready.fonts==='loaded' && ready.url!=='about:blank') break;
          await sleep(200);
        }
        if(!ready || !request.allowedOrigins.includes(new URL(ready.url).origin)) throw new Error('Final URL outside authorized scope');
        await sleep(request.settleMs);
        if (/just a moment|access denied|verify you are human/i.test(await cdp.evaluate('document.title'))) throw new Error('Challenge page; target not observed');
        const positions=job.state==='default' && request.checkpoints>1 ? Array.from({length:request.checkpoints},(_,i)=>i/(request.checkpoints-1)) : [0];
        let walkComplete=false, steps=0;
        for(let point=0;point<positions.length;point++) {
          if(point>0) {
            while(steps<request.maxSteps) {
              const g=await cdp.evaluate('({y:scrollY,h:innerHeight,total:document.documentElement.scrollHeight})');
              const target=(g.total-g.h)*positions[point];
              if(g.y>=target-2 || g.y+g.h>=g.total-2) break;
              await cdp.evaluate(`scrollTo({top:Math.min(${target},scrollY+innerHeight*.85),behavior:'instant'})`);
              steps++;await sleep(request.dwellMs);
            }
          }
          if(job.state!=='default') {
            const rect=await cdp.evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(job.selector)});if(!el)return null;el.scrollIntoView({block:'center'});const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
            if(!rect) throw new Error('State selector not found');
            if(job.state==='hover') await cdp.send('Input.dispatchMouseEvent',{type:'mouseMoved',...rect});
            else {
              const root=await cdp.send('DOM.getDocument');
              const selected=await cdp.send('DOM.querySelector',{nodeId:root.root.nodeId,selector:job.selector});
              await cdp.send('DOM.focus',{nodeId:selected.nodeId});
            }
            await sleep(request.settleMs);
          }
          const observation=await cdp.evaluate('('+probe+')('+JSON.stringify({maxElements:request.maxElements})+')');
          const state=point===0?(job.snapshotState||job.state):'scroll-'+String(point).padStart(2,'0');
          if(job.state!=='default') {
            const applied=await cdp.evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(job.selector)});return !!el&&${job.state==='hover'?"el.matches(':hover')":"document.activeElement===el"};})()`);
            if(!applied)throw new Error('Requested interaction state did not apply');
            observation.interaction={kind:job.state,selector:job.selector,applied};
          }
          observation.readiness={documentState:ready.state,fonts:ready.fonts,
            unloadedImages:await cdp.evaluate('[...document.images].filter(i=>!i.complete||!i.naturalWidth).length')};
          if(ready.state!=='complete' || ready.fonts!=='loaded') observation.gaps.push('readiness timeout');
          const geometry=await cdp.evaluate('({y:scrollY,h:innerHeight,total:document.documentElement.scrollHeight})');
          walkComplete=geometry.y+geometry.h>=geometry.total-2;
          observation.walkComplete=positions.length===1 ? geometry.total<=geometry.h : point===positions.length-1 ? walkComplete : undefined;
          observation.health={errors:health.errors.slice(0,100),failures:health.failures.slice(0,100),navigations};
          observation.browser={product:version.product,protocolVersion:version.protocolVersion,metricsMode:'css-viewport'};
          observation.capabilities={backend:'local-cdp',matchedStyles:true,renderedFonts:true};
          await sourceEvidence(cdp,observation,sheets,out,request.maxMatched);
          const id=hash(job.url+'|'+job.viewport+'|'+state).slice(0,16);
          const file=id+'.json', screenshot=id+'.jpg';
          const image=await cdp.send('Page.captureScreenshot',{format:'jpeg',quality:92},30000);
          await writeFile(path.join(out,screenshot),Buffer.from(image.data,'base64'));
          await writeFile(path.join(out,file),JSON.stringify(observation));
          result.snapshots.push({file,screenshot,url:job.url,viewport:job.viewport,state});await saveResult();
          console.log(JSON.stringify({status:'staged',url:job.url,viewport:job.viewport,state,elements:observation.elements.length}));
        }
      } catch(error) {
        result.failures.push({url:job.url,viewport:job.viewport,state:job.snapshotState||job.state,stage:'capture',message:error.message});
        await saveResult();
      }
    }
    await saveResult();if(result.failures.length) process.exitCode=2;
  } finally { unsubscribe();process.removeListener('SIGINT',interrupt);process.removeListener('SIGTERM',interrupt);await shutdown(); }
}

async function sourceEvidence(cdp,obs,sheets,out,limit) {
  obs.stylesheets=[];
  for(const [styleSheetId,header] of sheets) {
    try {
      const {text}=await cdp.send('CSS.getStyleSheetText',{styleSheetId});
      const sha256=hash(text), file='styles/'+sha256+'.css';
      await writeFile(path.join(out,file),text);
      obs.stylesheets.push({styleSheetId,href:publicUrl(header.sourceURL)||'inline',file,sha256,bytes:Buffer.byteLength(text)});
    } catch { obs.gaps.push('stylesheet text unavailable'); }
  }
  const root=await cdp.send('DOM.getDocument',{depth:0});
  const chosen=obs.elements.filter(el=>el.hasText||['button','nav','input','svg'].includes(el.tag)||Object.keys(el.pseudos).length).slice(0,limit);
  if(chosen.length<obs.elements.length)obs.gaps.push('matched-style/font sampling limited to '+chosen.length+' representative elements');
  const readRule=(entry,pseudo=null,inherited=false)=>{
    const rule=entry.rule, header=sheets.get(rule.style.styleSheetId);
    // Comma-separated media queries are alternatives; nested media blocks are cumulative.
    const mediaActive=(rule.media||[]).every(m=>!m.mediaList?.length || m.mediaList.some(v=>v.active!==false));
    return {selector:rule.selectorList.text,matchingSelectors:entry.matchingSelectors,active:mediaActive,
      href:publicUrl(header?.sourceURL)||'inline',styleSheetId:rule.style.styleSheetId,range:rule.style.range,
      values:Object.fromEntries(rule.style.cssProperties.filter(p=>!p.disabled && p.parsedOk!==false).map(p=>[p.name,p.value])),
      context:(rule.media||[]).map(m=>m.text).join(' / '),pseudo,inherited,provenance:'matched-candidate'};
  };
  for(const el of chosen) {
    try {
      const {nodeId}=await cdp.send('DOM.querySelector',{nodeId:root.root.nodeId,selector:el.selector});
      if(!nodeId)continue;
      const match=await cdp.send('CSS.getMatchedStylesForNode',{nodeId});
      el.matchedRules=(match.matchedCSSRules||[]).map(r=>readRule(r));
      for(const inherited of match.inherited||[])el.matchedRules.push(...(inherited.matchedCSSRules||[]).map(r=>readRule(r,null,true)));
      for(const pseudo of match.pseudoElements||[])el.matchedRules.push(...(pseudo.matches||[]).map(r=>readRule(r,'::'+pseudo.pseudoType)));
      if(el.hasText)el.renderedFonts=(await cdp.send('CSS.getPlatformFontsForNode',{nodeId})).fonts;
    } catch { obs.gaps.push('matched-style/font unavailable for '+el.selector); }
  }
  obs.gaps=[...new Set(obs.gaps)];
}
