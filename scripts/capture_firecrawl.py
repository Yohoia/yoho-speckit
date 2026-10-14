#!/usr/bin/env python3
"""Capture planned public pages using Firecrawl API or an existing authenticated CLI."""
import argparse
import base64
import json
import hashlib
import gzip
import io
import os
import re
import shutil
import subprocess
import sys
import time
import ipaddress
from urllib.parse import urlsplit
import urllib.error
import urllib.request
from pathlib import Path
from common import plan_for, index_for, ingest, snapshot_key, write_json, now, url

API_BASE = 'https://api.firecrawl.dev/v2'


class ProviderError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def unwrap(value):
    if isinstance(value, dict) and value.get('success') is False: raise ProviderError('provider_rejected')
    return value.get('data',value) if isinstance(value,dict) else value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


class RateGate:
    """Conservative free-plan pacing; does not retry failed paid requests."""
    def __init__(self):
        self.last_request=0.;self.last_creation=0.

    def wait(self,creation=False):
        current=time.monotonic()
        delay=max(0.,6.2-(current-self.last_request),31.-(current-self.last_creation) if creation else 0.)
        if delay:time.sleep(delay)
        self.last_request=time.monotonic()
        if creation:self.last_creation=self.last_request


class ApiClient:
    def __init__(self):
        self.key = os.environ.get('FIRECRAWL_API_KEY')
        if not self.key: raise ProviderError('api_credentials_missing')
        self.opener = urllib.request.build_opener(NoRedirect())
        self.sessions={};self.gate=RateGate()

    def request(self, method, path, payload=None):
        self.gate.wait()
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(API_BASE+path,data=body,method=method,
            headers={'Content-Type':'application/json','Authorization':'Bearer '+self.key})
        try:
            with self.opener.open(req,timeout=100) as response:
                data = response.read(32*1024*1024+1)
                if len(data)>32*1024*1024: raise ProviderError('response_too_large')
                return unwrap(json.loads(data))
        except urllib.error.HTTPError as error:
            raise ProviderError('http_'+str(error.code)) from None
        except (urllib.error.URLError,TimeoutError,json.JSONDecodeError):
            raise ProviderError('network_or_response_error') from None

    def scrape(self,target,branding):
        return self.request('POST','/scrape',{'url':target,'formats':['links']+(['branding'] if branding else []),
            'onlyMainContent':False,'maxAge':0,'blockAds':False})

    def interact(self,identifier,code):
        payload={'code':code,'language':'node','timeout':90}
        if identifier in self.sessions:
            return self.request('POST','/interact/'+self.sessions[identifier]+'/execute',payload)
        self.gate.wait(creation=True)
        result=self.request('POST','/scrape/'+identifier+'/interact',payload)
        session=result.get('sessionId')
        if isinstance(session,str) and re.fullmatch(r'[a-fA-F0-9-]{36}',session):self.sessions[identifier]=session
        return result

    def stop(self,identifier):
        path='/interact/'+self.sessions.pop(identifier) if identifier in self.sessions else '/scrape/'+identifier+'/interact'
        self.request('DELETE',path)


class CliClient:
    def __init__(self):
        self.command = shutil.which('firecrawl')
        if not self.command: raise ProviderError('cli_missing')
        from design import doctor
        if not doctor(cloud_status=True)['firecrawlCli']['authenticated']: raise ProviderError('cli_credentials_missing')
        self.sessions={};self.gate=RateGate()

    def invoke(self, args):
        self.gate.wait()
        try:
            result = subprocess.run([self.command]+args,capture_output=True,text=True,timeout=150)
        except (OSError,subprocess.TimeoutExpired): raise ProviderError('cli_timeout_or_unavailable') from None
        if result.returncode:
            text = (result.stdout + result.stderr).lower()
            code = 'authentication_failed' if any(x in text for x in ['unauthorized','invalid token']) else 'quota_exhausted' if 'credit' in text else 'rate_limited' if 'rate limit' in text else 'cli_request_failed'
            raise ProviderError(code)
        try: return unwrap(json.loads(result.stdout))
        except json.JSONDecodeError: raise ProviderError('cli_response_not_json') from None

    def scrape(self,target,branding):
        return self.invoke(['scrape',target,'--format','links,branding' if branding else 'links','--json','--max-age','0'])

    def interact(self,identifier,code):
        if identifier in self.sessions:
            return self.invoke(['browser','execute','--session',self.sessions[identifier],'--node',code,'--json'])
        self.gate.wait(creation=True)
        result=self.invoke(['interact','--scrape-id',identifier,'--node','--code',code,'--timeout','90','--json'])
        session=result.get('sessionId')
        if isinstance(session,str) and re.fullmatch(r'[a-fA-F0-9-]{36}',session):self.sessions[identifier]=session
        return result

    def stop(self,identifier):
        self.gate.wait()
        args=['browser','close','--session',self.sessions.pop(identifier)] if identifier in self.sessions else ['interact','stop',identifier]
        try:
            result = subprocess.run([self.command]+args,capture_output=True,text=True,timeout=30)
        except (OSError,subprocess.TimeoutExpired): raise ProviderError('session_cleanup_failed') from None
        if result.returncode: raise ProviderError('session_cleanup_failed')


def browser_code(view,maximum,key='capture'):
    probe = (Path(__file__).resolve().parent.parent/'assets'/'probe.js').read_text(encoding='utf-8')
    return '''await page.setViewportSize(VIEWPORT);
await page.evaluate(() => Promise.race([document.fonts.ready,new Promise(r=>setTimeout(r,5000))]));
let walkComplete=false;
for(let i=0;i<24;i++){
  const geometry=await page.evaluate(()=>({y:scrollY,h:innerHeight,total:document.documentElement.scrollHeight}));
  if(geometry.y+geometry.h>=geometry.total-2){walkComplete=true;break;}
  await page.evaluate(()=>scrollBy(0,innerHeight*0.85));
  await page.waitForTimeout(120);
}
await page.evaluate(()=>scrollTo(0,0));
await page.waitForTimeout(200);
const observation=await page.evaluate(PROBE,{maxElements:MAXIMUM});
observation.walkComplete=walkComplete;
const screenshot=await page.screenshot({type:'png',fullPage:false});
const fs=require('node:fs/promises'), crypto=require('node:crypto'), zlib=require('node:zlib');
const raw=Buffer.from(JSON.stringify(observation));
const compressed=zlib.gzipSync(raw);
await fs.writeFile('/tmp/wde-KEY-observation.json',compressed);
await fs.writeFile('/tmp/wde-KEY-screenshot.png',screenshot);
console.log(JSON.stringify({captureFiles:{observation:{bytes:compressed.length,rawBytes:raw.length,compression:'gzip',sha256:crypto.createHash('sha256').update(compressed).digest('hex')},screenshot:{bytes:screenshot.length,sha256:crypto.createHash('sha256').update(screenshot).digest('hex')}}}));
'''.replace('VIEWPORT',json.dumps({k:view[k] for k in ('width','height')})).replace('PROBE',probe).replace('MAXIMUM',str(maximum)).replace('KEY',key)


def interact_result(response):
    if not isinstance(response,dict): raise ProviderError('interact_response_invalid')
    if response.get('exitCode',0) != 0 or response.get('killed'): raise ProviderError('browser_execution_failed')
    if response.get('truncated'): raise ProviderError('provider_output_truncated')
    if any(k in response for k in ('observation','captureFiles','chunk')):return response
    if isinstance(response.get('result'),dict) and any(k in response['result'] for k in ('observation','captureFiles','chunk')): return response['result']
    for key in ('stdout','result','output'):
        value = response.get(key)
        if isinstance(value,str):
            for line in reversed(value.splitlines()):
                try:
                    parsed=json.loads(line)
                    if isinstance(parsed,dict) and any(k in parsed for k in ('observation','captureFiles','chunk')): return parsed
                except json.JSONDecodeError: continue
    raise ProviderError('probe_result_missing')


def download_capture(client,identifier,key,manifest):
    output={}
    for kind,ext in [('observation','json'),('screenshot','png')]:
        record=manifest[kind]; size=record['bytes']
        if not isinstance(size,int) or size<1 or size>16*1024*1024: raise ProviderError('capture_size_invalid')
        data=bytearray()
        for offset in range(0,size,256*1024):
            code="const fs=require('node:fs/promises');const b=await fs.readFile('/tmp/wde-"+key+"-"+kind+"."+ext+"');console.log(JSON.stringify({chunk:b.subarray("+str(offset)+","+str(min(size,offset+256*1024))+ ").toString('base64')}));"
            result=interact_result(client.interact(identifier,code))
            data.extend(base64.b64decode(result['chunk'],validate=True))
        if len(data)!=size or hashlib.sha256(data).hexdigest()!=record['sha256']:
            raise ProviderError('capture_transfer_incomplete')
        output[kind]=bytes(data)
    observation=output['observation']
    if manifest['observation'].get('compression')=='gzip':
        with gzip.GzipFile(fileobj=io.BytesIO(observation)) as stream:observation=stream.read(32*1024*1024+1)
        if len(observation)>32*1024*1024 or len(observation)!=manifest['observation']['rawBytes']:
            raise ProviderError('capture_decompression_incomplete')
    return {'observation':json.loads(observation), 'screenshot':base64.b64encode(output['screenshot']).decode()}


def failure(run,target,view,stage,code,identifier=None):
    index = index_for(run)
    record = {'url':target,'viewport':view,'stage':stage,'code':code,'capturedAt':now()}
    if identifier: record['scrapeId']=identifier
    index['failures'].append(record)
    write_json(Path(run)/'evidence'/'index.json',index)


def capture(client,run,target,view,maximum=600,branding=False,refresh=False):
    host=urlsplit(target).hostname
    try: private=not ipaddress.ip_address(host).is_global
    except ValueError: private=host=='localhost' or host.endswith('.local')
    if private: raise ProviderError('local_or_private_url_requires_host_browser')
    key = snapshot_key(target,view['name'],'default')
    if not refresh and any(x['id']==key for x in index_for(run)['snapshots']):
        return {'status':'unchanged','url':target,'viewport':view['name']}
    identifier,stage = None,'scrape'
    try:
        doc = client.scrape(target,branding)
        if not isinstance(doc,dict): raise ProviderError('scrape_document_missing')
        metadata = doc.get('metadata',{})
        status = metadata.get('statusCode')
        if not isinstance(status,int) or not (200<=status<300 or status==304): raise ProviderError('target_page_failed')
        identifier = metadata.get('scrapeId')
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-fA-F0-9-]{36}',identifier): raise ProviderError('scrape_id_missing')
        if branding and doc.get('branding'):
            write_json(Path(run)/'evidence'/'branding'/(key+'.json'),{'url':target,'capturedAt':now(),'value':doc['branding'],'status':'provider-summary-unverified'})
        stage='interact'
        result = interact_result(client.interact(identifier,browser_code(view,maximum,key)))
        if 'captureFiles' in result:
            stage='transfer'
            result=download_capture(client,identifier,key,result['captureFiles'])
        obs = result['observation']
        if any(x in (obs.get('title') or '').lower() for x in ['just a moment','access denied','verify you are human']):
            raise ProviderError('target_challenge_page')
        stage='ingest'
        shot = None
        if result.get('screenshot'):
            data = base64.b64decode(result['screenshot'],validate=True)
            if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data)>10*1024*1024: raise ProviderError('screenshot_invalid')
            shot='evidence/screenshots/'+key+'.png'
            path=Path(run)/shot;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        saved = ingest(run,obs,'firecrawl',view['name'],'default',target,shot,refresh)
        return {**saved,'url':target,'viewport':view['name'],'elements':len(obs['elements'])}
    except (ProviderError,ValueError,KeyError,TypeError,OSError) as error:
        code=error.code if isinstance(error,ProviderError) else 'invalid_observation_or_local_io'
        failure(run,target,view['name'],stage,code,identifier)
        raise ProviderError(code) from None
    finally:
        if identifier:
            try: client.stop(identifier)
            except Exception:
                failure(run,target,view['name'],'cleanup','session_cleanup_failed',identifier)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True)
    parser.add_argument('--transport',choices=['cli','api'],default='api')
    parser.add_argument('--url');parser.add_argument('--viewport',choices=['desktop','mobile'])
    parser.add_argument('--branding',action='store_true');parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--max-elements',type=int,default=600)
    args=parser.parse_args(argv)
    try:
        plan=plan_for(args.run)
        if not 1<=args.max_elements<=5000: raise ValueError('max-elements 范围为 1–5000')
        pages = [url(args.url)] if args.url else plan['pages']
        if any(p not in plan['pages'] for p in pages): raise ValueError('URL 不在计划中')
        views = [v for v in plan['viewports'] if not args.viewport or v['name']==args.viewport]
        if not views: raise ValueError('视口不在计划中')
        pending = [(p,v) for p in pages for v in views if args.refresh or not any(x['id']==snapshot_key(p,v['name'],'default') for x in index_for(args.run)['snapshots'])]
        if not pending:
            print(json.dumps({'status':'unchanged','message':'计划快照已存在'}));return 0
        client = CliClient() if args.transport=='cli' else ApiClient()
        for p,v in pending:
            print(json.dumps(capture(client,args.run,p,v,args.max_elements,args.branding,args.refresh),ensure_ascii=False),flush=True)
        from common import coverage
        result=coverage(args.run);write_json(Path(args.run)/'evidence'/'coverage.json',result)
        cleanup=[x for x in result['failures'] if x['stage']=='cleanup']
        print(json.dumps({'status':'captured','pages':result['pageCount'],'snapshots':result['snapshotCount'],'cleanupWarnings':len(cleanup)},ensure_ascii=False))
        return 0
    except ProviderError as error:
        print(json.dumps({'status':'stopped','code':error.code,'message':'保留已采结果；检查配置、额度或服务合同后恢复。'}),file=sys.stderr)
        return 2
    except (ValueError,KeyError,OSError) as error:
        print(json.dumps({'status':'error','message':str(error)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(main())
