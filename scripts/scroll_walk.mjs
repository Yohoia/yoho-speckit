/** Bounded vertical walking of the document and measurable scroll containers. */
import {sleep} from './cdp.mjs';

function discover(limit) {
  const root=document.scrollingElement||document.documentElement;
  const selector=el=>{
    if(el.id&&document.querySelectorAll('#'+CSS.escape(el.id)).length===1)return '#'+CSS.escape(el.id);
    const parts=[];
    for(let n=el;n&&n.nodeType===1;n=n.parentElement){
      parts.unshift(n.tagName.toLowerCase()+':nth-child('+(n.parentElement?[...n.parentElement.children].indexOf(n)+1:1)+')');
    }
    return parts.join(' > ');
  };
  const geometry=(el,kind)=>{
    const r=el.getBoundingClientRect();
    return {kind,selector:kind==='document'?null:selector(el),x:el.scrollLeft,y:el.scrollTop,
      width:kind==='document'?innerWidth:el.clientWidth,height:kind==='document'?innerHeight:el.clientHeight,
      total:el.scrollHeight,visible:kind==='document'||(r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth)};
  };
  const nodes=document.querySelectorAll('body, body *'),containers=[];
  let horizontal=root.scrollWidth>innerWidth+2?1:0;
  for(let i=0;i<Math.min(nodes.length,limit);i++){
    const el=nodes[i];
    if(el===root||el.matches('input,textarea,select,option')||el.clientHeight<=0||el.clientWidth<=0)continue;
    if(el.scrollHeight<=el.clientHeight+2&&el.scrollWidth<=el.clientWidth+2)continue;
    const s=getComputedStyle(el),r=el.getBoundingClientRect();
    if(s.display==='none'||s.visibility==='hidden'||!r.width||!r.height)continue;
    if(/^(auto|scroll|overlay)$/.test(s.overflowX)&&el.scrollWidth>el.clientWidth+2)horizontal++;
    if(/^(auto|scroll|overlay)$/.test(s.overflowY)&&el.scrollHeight>el.clientHeight+2)containers.push(geometry(el,'element'));
  }
  containers.sort((a,b)=>Number(b.visible)-Number(a.visible)||b.width*b.height-a.width*a.height);
  return {document:geometry(root,'document'),containers,horizontal,truncated:nodes.length>limit};
}

export function createScrollWalk(cdp,{maxSteps,dwellMs,maxContainers=4,maxNodes=10000}) {
  let documentKey,steps=0,selected=new Map(),omitted=0,horizontal=0,truncated=false,stalled=new Set(),unavailable=new Set();
  const bind=identity=>{
    const key=identity.frameId+':'+identity.loaderId;
    if(key!==documentKey){documentKey=key;selected.clear();omitted=horizontal=0;truncated=false;stalled.clear();unavailable.clear();}
  };
  const read=async()=>{
    const data=await cdp.evaluate('('+discover+')('+maxNodes+')');
    truncated||=data.truncated;horizontal=Math.max(horizontal,data.horizontal);
    for(const item of data.containers){
      if(!selected.has(item.selector)&&selected.size<maxContainers)selected.set(item.selector,false);
      if(selected.has(item.selector)&&item.visible)selected.set(item.selector,true);
    }
    omitted=Math.max(omitted,data.containers.filter(x=>!selected.has(x.selector)).length);
    const containers=data.containers.filter(x=>selected.has(x.selector));
    for(const selector of selected.keys())if(!containers.some(x=>x.selector===selector))unavailable.add(selector);
    return [data.document,...containers];
  };
  const to=async(fraction,move,check)=>{
    let targets=await read();
    while(move&&steps<maxSteps){
      await check();
      const item=targets.find(t=>t.visible&&!stalled.has(t.selector)&&t.y<(t.total-t.height)*fraction-2);
      if(!item)break;
      const y=Math.min((item.total-item.height)*fraction,item.y+item.height*.85);
      await cdp.evaluate(`(()=>{const el=${item.kind==='document'?'document.scrollingElement||document.documentElement':'document.querySelector('+JSON.stringify(item.selector)+')'};if(el)el.scrollTo({top:${y},behavior:'instant'});})()`);
      steps++;await sleep(dwellMs);await check();targets=await read();
      const after=targets.find(t=>t.selector===item.selector);
      if(after&&Math.abs(after.y-item.y)<1&&after.total===item.total)stalled.add(item.selector);
    }
  };
  const summary=async()=>{
    const targets=await read(),gaps=[];
    if(omitted)gaps.push('scroll container budget exceeded: '+omitted+' omitted');
    if(truncated)gaps.push('scroll container discovery truncated at '+maxNodes+' nodes');
    if(horizontal)gaps.push('horizontal scroll regions not walked: '+horizontal);
    if(stalled.size)gaps.push('scroll targets stalled: '+stalled.size);
    if(unavailable.size)gaps.push('scroll containers changed or became unavailable: '+unavailable.size);
    for(const target of targets){
      target.atEnd=target.y+target.height>=target.total-2;
      if(target.kind==='element'&&!target.atEnd&&!target.visible)gaps.push('scroll container outside viewport: '+target.selector);
    }
    const complete=!omitted&&!truncated&&!horizontal&&!stalled.size&&!unavailable.size&&
      targets.every(t=>t.atEnd&&(t.kind==='document'||selected.get(t.selector)));
    return {targets,stepsUsed:steps,maxSteps,maxContainers,maxNodes,omittedContainers:omitted,
      discoveryTruncated:truncated,horizontalRegions:horizontal,complete,gaps};
  };
  return {bind,to,summary};
}
