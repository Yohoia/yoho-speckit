/** Local, isolated Chrome session. Independent implementation; Node 22+ built-ins only. */
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm, access } from 'node:fs/promises';
import { tmpdir, platform, homedir } from 'node:os';
import path from 'node:path';

export const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

export async function chromePath(explicit = process.env.SPECKIT_CHROME_PATH) {
  if (explicit) { await access(explicit); return path.resolve(explicit); }
  const candidates = platform() === 'darwin' ? [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    path.join(homedir(), 'Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
  ] : platform() === 'win32' ? [process.env.PROGRAMFILES, process.env['PROGRAMFILES(X86)'], process.env.LOCALAPPDATA]
    .filter(Boolean).flatMap(root => [path.join(root, 'Google/Chrome/Application/chrome.exe'), path.join(root, 'Chromium/Application/chrome.exe')])
    : ['/usr/bin/google-chrome','/usr/bin/google-chrome-stable','/usr/bin/chromium','/usr/bin/chromium-browser'];
  for (const candidate of candidates) { try { await access(candidate); return candidate; } catch {} }
  throw new Error('Chrome/Chromium not found; set SPECKIT_CHROME_PATH to its executable');
}

export async function connect(url) {
  const ws = new WebSocket(url);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { ws.close(); reject(new Error('CDP connection timeout')); }, 10000);
    ws.onopen = () => { clearTimeout(timer); resolve(); };
    ws.onerror = () => { clearTimeout(timer); reject(new Error('CDP connection failed')); };
  });
  let sequence = 0, closed = false;
  const pending = new Map(), listeners = new Set();
  const rejectAll = reason => { closed = true; for (const item of pending.values()) { clearTimeout(item.timer); item.reject(new Error(reason)); } pending.clear(); };
  ws.onclose = () => rejectAll('CDP disconnected');
  ws.onerror = () => rejectAll('CDP transport error');
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const item = pending.get(message.id); if (!item) return;
      pending.delete(message.id); clearTimeout(item.timer);
      if (message.error) item.reject(new Error(message.error.message)); else item.resolve(message.result || {});
    } else for (const listener of listeners) listener(message);
  };
  const send = (method, params = {}, timeout = 15000) => new Promise((resolve, reject) => {
    if (closed) { reject(new Error('CDP session closed')); return; }
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('CDP timeout: '+method)); }, timeout);
    pending.set(id, {resolve,reject,timer}); ws.send(JSON.stringify({id,method,params}));
  });
  return {send, on: listener => { listeners.add(listener); return () => listeners.delete(listener); },
    evaluate: async expression => {
      const result = await send('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true}, 30000);
      if (result.exceptionDetails) throw new Error('Page evaluation failed: '+result.exceptionDetails.text);
      return result.result?.value;
    }, close: () => { rejectAll('CDP session closed'); ws.close(); }};
}

export async function launch(explicit) {
  const bin = await chromePath(explicit), profile = await mkdtemp(path.join(tmpdir(), 'speckit-chrome-'));
  const child = spawn(bin, ['--headless=new','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',
    '--user-data-dir='+profile,'--no-first-run','--no-default-browser-check','--disable-background-networking',
    '--disable-background-timer-throttling','--disable-renderer-backgrounding','about:blank'], {stdio:'ignore',windowsHide:true,detached:platform()!=='win32'});
  let spawnError;
  child.once('error', error => { spawnError = error; });
  let stopped = false;
  const stop = async () => {
    if (stopped) return; stopped = true;
    if (child.exitCode === null && child.pid) {
      const signalTree=signal=>{try { if(platform()==='win32')child.kill(signal);else process.kill(-child.pid,signal); } catch {} };
      if(platform()==='win32') {
        const killer=spawn('taskkill',['/PID',String(child.pid),'/T','/F'],{stdio:'ignore',windowsHide:true});
        await new Promise(resolve=>{killer.once('error',resolve);killer.once('close',resolve);setTimeout(resolve,2000).unref();});
      }
      signalTree('SIGTERM');
      for (let i=0;i<40 && child.exitCode===null;i++) await sleep(50);
      if (child.exitCode===null) { signalTree('SIGKILL'); await sleep(200); }
    }
    await rm(profile,{recursive:true,force:true,maxRetries:3,retryDelay:100});
  };
  const interrupted=()=>{stop().finally(()=>process.exit(130));};
  process.once('SIGINT',interrupted);process.once('SIGTERM',interrupted);
  try {
    for (let i=0;i<120;i++) {
      if (spawnError || child.exitCode!==null) throw new Error('Chrome failed to start');
      try {
        const [port] = (await readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n');
        const response = await fetch('http://127.0.0.1:'+port+'/json/list', {signal:AbortSignal.timeout(2000)});
        const pages = await response.json(), page = pages.find(item => item.type==='page' && item.url==='about:blank');
        if (page) return {cdp:await connect(page.webSocketDebuggerUrl),stop,bin};
      } catch (error) { if (i===119) throw error; }
      await sleep(100);
    }
    throw new Error('Chrome startup timeout');
  } catch (error) { await stop(); throw error; }
  finally {process.removeListener('SIGINT',interrupted);process.removeListener('SIGTERM',interrupted);}
}
