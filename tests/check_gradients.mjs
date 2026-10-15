/** Render the actual captured and exported CSS in the same owned browser. */
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {launch,sleep} from '../scripts/cdp.mjs';

const request=JSON.parse(await readFile(process.argv[2],'utf8'));
const browser=await launch(),cdp=browser.cdp;
try {
  await cdp.send('Page.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:512,height:request.pairs.length*100,deviceScaleFactor:1,mobile:false});
  await cdp.send('Page.navigate',{url:'data:text/html,'+encodeURIComponent('<!doctype html><style>body{margin:0;display:grid;grid-template-columns:256px 256px}div{width:256px;height:100px}</style>')});
  await sleep(100);
  const values=await cdp.evaluate(`(()=>{
    const pairs=${JSON.stringify(request.pairs)},result=[];
    for(const pair of pairs)for(const value of [pair.original,pair.exported]){
      const el=document.createElement('div');el.style.backgroundImage=value;document.body.append(el);
      result.push(getComputedStyle(el).backgroundImage);
    }
    return result;
  })()`);
  assert(values.every(value=>value!=='none'),'original and exported gradients must be executable');
  const screenshot=await cdp.send('Page.captureScreenshot',{format:'png'});
  await writeFile(request.screenshot,Buffer.from(screenshot.data,'base64'));
  console.log(JSON.stringify({rendered:request.pairs.length,values}));
}finally{cdp.close();await browser.stop();}
