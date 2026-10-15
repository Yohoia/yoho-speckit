/** Bind a sample to the current main-frame loader, including client-side navigation. */
import { sleep } from './cdp.mjs';

export class DocumentChanged extends Error {}

export function documentGuard(cdp, request, responses) {
  const frame = async () => (await cdp.send('Page.getFrameTree')).frameTree.frame;
  const allowed = value => {
    if (!request.allowedOrigins.includes(new URL(value).origin)) throw new Error('Final URL outside authorized scope');
  };
  const same = (a,b) => a.frameId===b.id && a.loaderId===b.loaderId;
  const changed = async identity => !same(identity,await frame());
  const check = async identity => {
    const current=await frame();
    if (!same(identity,current)) throw new DocumentChanged('Main document changed during sampling');
    allowed(current.url);
  };
  const ready = async () => {
    const deadline=Date.now()+request.readyTimeout;
    let last;
    while(Date.now()<deadline) {
      let before,after,state;
      try {
        before=await frame();
        state=await cdp.evaluate(`({state:document.readyState,fonts:document.fonts?.status||'unknown',url:location.href,title:document.title,images:[...document.images].filter(i=>!i.complete||!i.naturalWidth).length})`);
        after=await frame();
      } catch(error) {
        if(/CDP (?:session closed|disconnected|transport)/.test(error.message))throw error;
        await sleep(100);continue;
      }
      if(before.id!==after.id || before.loaderId!==after.loaderId || !state || state.url==='about:blank') {
        await sleep(100);continue;
      }
      allowed(state.url);
      const document=responses().findLast(d=>d.frameId===after.id && d.loaderId===after.loaderId);
      if(!document){await sleep(100);continue;}
      if(document.status>=400)throw new Error('Main document HTTP '+document.status+': '+document.url);
      if(/just a moment|access denied|verify you are human/i.test(state.title))throw new Error('Challenge page; target not observed');
      last={frameId:after.id,loaderId:after.loaderId,mainDocument:document,readiness:state};
      if(state.state==='complete' && state.fonts==='loaded')return last;
      await sleep(200);
    }
    if(last && !await changed(last))return last;
    throw new Error('Current main document identity/readiness unavailable');
  };
  return {ready,check,changed};
}
