#!/usr/bin/env node
/** Single local Chrome/CDP backend. Writes staged snapshots; Python commits validated evidence. */
import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { gzipSync } from 'node:zlib';
import { launch, chromePath, sleep } from './cdp.mjs';
import { documentGuard, DocumentChanged } from './document_guard.mjs';
import { createScrollWalk } from './scroll_walk.mjs';

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
  let health={errors:[],failures:[]}, sheets=new Map(), navigations=0, documents=[];
  const unsubscribe=cdp.on(message=>{
    const p=message.params||{};
    if(message.method==='CSS.styleSheetAdded') sheets.set(p.header.styleSheetId,p.header);
    if(message.method==='CSS.styleSheetRemoved') sheets.delete(p.styleSheetId);
    if(message.method==='Runtime.exceptionThrown') health.errors.push('page exception: '+(p.exceptionDetails?.text||'unknown'));
    if(message.method==='Log.entryAdded' && p.entry.level==='error') health.errors.push('browser log error: '+p.entry.source);
    if(message.method==='Network.responseReceived' && p.response.status>=400) health.failures.push({url:publicUrl(p.response.url),status:p.response.status,type:p.type,frameId:p.frameId,loaderId:p.loaderId});
    if(message.method==='Network.responseReceived' && p.type==='Document')documents.push({frameId:p.frameId,loaderId:p.loaderId,url:publicUrl(p.response.url),status:p.response.status});
    if(message.method==='Network.loadingFailed' && !p.canceled) health.failures.push({error:p.errorText});
    if(message.method==='Inspector.targetCrashed') health.errors.push('renderer crashed');
    if(message.method==='Page.frameNavigated' && !p.frame.parentId) navigations++;
  });
  const guard=documentGuard(cdp,request,()=>documents);
  try {
    for(const method of ['Page.enable','Runtime.enable','Network.enable','DOM.enable','CSS.enable','Log.enable','Inspector.enable']) await cdp.send(method);
    await cdp.send('Emulation.setFocusEmulationEnabled',{enabled:true});
    const version=await cdp.send('Browser.getVersion');
    for(const job of request.jobs) {
      health={errors:[],failures:[]};sheets=new Map();navigations=0;documents=[];
      let failedState=job.snapshotState||job.state;
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
        await sleep(request.settleMs);
        const positions=job.state==='default' && request.checkpoints>1 ? Array.from({length:request.checkpoints},(_,i)=>i/(request.checkpoints-1)) : [0];
        const walk=createScrollWalk(cdp,request);
        for(let point=0;point<positions.length;point++) {
          failedState=point===0?(job.snapshotState||job.state):'scroll-'+String(point).padStart(2,'0');
          for(let retry=0;retry<3;retry++) {
            let identity;
            try {
              identity=await guard.ready();
              const ready=identity.readiness;
              walk.bind(identity);
              await walk.to(positions[point],point>0,()=>guard.check(identity));
              await guard.check(identity);
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
              await guard.check(identity);
              const observation=await cdp.evaluate('('+probe+')('+JSON.stringify({maxElements:request.maxElements,targetSelector:job.state!=='default'?job.selector:undefined})+')');
              observation.capturedAt=new Date().toISOString();
              const state=point===0?(job.snapshotState||job.state):'scroll-'+String(point).padStart(2,'0');
              if(job.state!=='default') {
                const applied=await cdp.evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(job.selector)});return !!el&&${job.state==='hover'?"el.matches(':hover')":"document.activeElement===el&&el.matches(':focus')"};})()`);
                if(!applied)throw new Error('Requested interaction state did not apply');
                const target=observation.interactionTarget;
                if(!target || !observation.elements.some(e=>e.id===target.id&&e.selector===target.selector))throw new Error('Interaction target not measured');
                observation.interaction={kind:job.state,selector:job.selector,elementId:target.id,elementSelector:target.selector,applied};
              }
              delete observation.interactionTarget;
              observation.readiness={documentState:ready.state,fonts:ready.fonts,
                unloadedImages:await cdp.evaluate('[...document.images].filter(i=>!i.complete||!i.naturalWidth).length')};
              if(ready.state!=='complete' || ready.fonts!=='loaded') observation.gaps.push('readiness timeout');
              observation.scrollWalk=await walk.summary();
              observation.gaps.push(...observation.scrollWalk.gaps);
              observation.walkComplete=point===positions.length-1?observation.scrollWalk.complete:undefined;
              observation.health={errors:health.errors.slice(0,100),failures:health.failures.slice(0,100),navigations};
              observation.browser={product:version.product,protocolVersion:version.protocolVersion,metricsMode:'css-viewport'};
              observation.mainDocument=identity.mainDocument;
              observation.documentIdentity={frameId:identity.frameId,loaderId:identity.loaderId};
              observation.captureConfig=job.captureConfig;observation.captureAttempt=job.attemptId;
              observation.checkpoint={index:point,fraction:positions[point]};
              observation.capabilities={backend:'local-cdp',matchedStyles:true,renderedFonts:true};
              await sourceEvidence(cdp,observation,sheets,out,request.maxMatched);
              await guard.check(identity);
              const id=hash(job.url+'|'+job.viewport+'|'+state).slice(0,16);
              const file=id+'.json.gz', screenshot=id+'.jpg';
              const image=await cdp.send('Page.captureScreenshot',{format:'jpeg',quality:92},30000);
              await guard.check(identity);
              await writeFile(path.join(out,screenshot),Buffer.from(image.data,'base64'));
              await writeFile(path.join(out,file),gzipSync(JSON.stringify(observation)));
              result.snapshots.push({file,screenshot,url:job.url,viewport:job.viewport,state});await saveResult();
              console.log(JSON.stringify({status:'staged',url:job.url,viewport:job.viewport,state,elements:observation.elements.length}));
              break;
            } catch(error) {
              if(retry<2 && identity && (error instanceof DocumentChanged || await guard.changed(identity))) {
                await sleep(request.settleMs);continue;
              }
              throw error;
            }
          }
        }
      } catch(error) {
        result.failures.push({url:job.url,viewport:job.viewport,state:failedState,stage:'capture',message:error.message});
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
  const target=obs.interaction?.elementId;
  const eligible=obs.elements.filter(el=>el.id===target||el.textStyleRelevant||el.hasText||['button','nav','input','svg'].includes(el.tag)||Object.keys(el.pseudos).length);
  eligible.sort((a,b)=>a.id===target?-1:b.id===target?1:0);
  const chosen=eligible.slice(0,limit);
  if(target && !limit)obs.gaps.push('interaction target matched-style/font sampling disabled (maxMatched=0)');
  if(chosen.length<obs.elements.length)obs.gaps.push('matched-style/font sampling limited to '+chosen.length+' representative elements');
  const readRule=(entry,pseudo=null,inherited=false,ancestorSelector=null,ancestorDepth=null)=>{
    const rule=entry.rule, header=sheets.get(rule.style.styleSheetId);
    // Comma-separated media queries are alternatives; nested media blocks are cumulative.
    const mediaActive=(rule.media||[]).every(m=>!m.mediaList?.length || m.mediaList.some(v=>v.active!==false));
    return {selector:rule.selectorList.text,matchingSelectors:entry.matchingSelectors,active:mediaActive,
      href:publicUrl(header?.sourceURL)||'inline',styleSheetId:rule.style.styleSheetId,range:rule.style.range,
      values:Object.fromEntries(rule.style.cssProperties.filter(p=>!p.disabled && p.parsedOk!==false).map(p=>[p.name,p.value])),
      context:(rule.media||[]).map(m=>m.text).join(' / '),pseudo,inherited,ancestorSelector,ancestorDepth,
      origin:rule.origin,provenance:'matched-candidate'};
  };
  for(const el of chosen) {
    try {
      const {nodeId}=await cdp.send('DOM.querySelector',{nodeId:root.root.nodeId,selector:el.selector});
      if(!nodeId){if(el.id===target)throw new Error('Interaction target source node missing');continue;}
      const match=await cdp.send('CSS.getMatchedStylesForNode',{nodeId});
      el.matchedRules=(match.matchedCSSRules||[]).map(r=>readRule(r));
      for(const [depth,inherited] of (match.inherited||[]).entries()) {
        const ancestorSelector=el.ancestorSelectors?.[depth]||null;
        el.matchedRules.push(...(inherited.matchedCSSRules||[]).map(r=>readRule(r,null,true,ancestorSelector,depth+1)));
        if(inherited.inlineStyle?.cssProperties?.length)el.matchedRules.push({selector:ancestorSelector||'unknown',
          values:Object.fromEntries(inherited.inlineStyle.cssProperties.filter(p=>!p.disabled&&p.parsedOk!==false).map(p=>[p.name,p.value])),
          active:true,origin:'inline',inherited:true,ancestorSelector,ancestorDepth:depth+1,pseudo:null,provenance:'matched-candidate'});
      }
      for(const pseudo of match.pseudoElements||[])el.matchedRules.push(...(pseudo.matches||[]).map(r=>readRule(r,'::'+pseudo.pseudoType)));
      if(el.textStyleRelevant||el.hasText||el.id===target) {
        el.renderedFonts=(await cdp.send('CSS.getPlatformFontsForNode',{nodeId})).fonts;
        if(el.textStyleRelevant && !el.renderedFonts.some(f=>f.glyphCount>0))obs.gaps.push('rendered fonts unknown for '+el.selector);
      }
    } catch(error) {
      if(el.id===target)throw new Error('Interaction target matched-style/font unavailable: '+error.message);
      obs.gaps.push('matched-style/font unavailable for '+el.selector);
    }
  }
  const table=[],positions=new Map();
  for(const el of obs.elements) {
    if(!el.matchedRules)continue;
    el.matchedRuleRefs=el.matchedRules.map(rule=>{const key=JSON.stringify(rule);if(!positions.has(key)){positions.set(key,table.length);table.push(rule)}return positions.get(key)});
    delete el.matchedRules;
  }
  obs.matchedRuleTable=table;
  obs.gaps=[...new Set(obs.gaps)];
}
