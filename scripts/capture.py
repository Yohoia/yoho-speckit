"""Validate a plan and commit staged local CDP captures; no API credentials or cloud backend."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from ledger import register_requests, resolve_failures
from common import coverage, digest, evidence_lock, index_for, _ingest, local_file, now, origin, plan_for, read_json, snapshot_key, url, write_json


def doctor():
    node=shutil.which('node')
    result={'backend':'local-cdp','node':node,'nodeSupported':False,'chrome':None,'ready':False}
    if not node:return result
    try:
        proc=subprocess.run([node,str(Path(__file__).with_name('capture_browser.mjs')),'--doctor'],capture_output=True,text=True,timeout=10)
        if proc.returncode==0:result.update(json.loads(proc.stdout))
    except (OSError,subprocess.TimeoutExpired,json.JSONDecodeError):pass
    result['ready']=bool(result['nodeSupported'] and result['chrome'])
    return result


def record_failure(run, failure):
    with evidence_lock(run):
        index=index_for(run)
        index['failures'].append({**failure,'capturedAt':now()})
        write_json(Path(run)/'evidence'/'index.json',index)


def commit_snapshot(run, stage, row, refresh=False):
    stage=Path(stage).resolve()
    observation=read_json(local_file(stage,row['file']))
    # All image and source bytes are verified before the active evidence index changes.
    image=local_file(stage,row['screenshot']).read_bytes()
    if not image.startswith(b'\xff\xd8') or len(image)>16*1024*1024:raise ValueError('CDP 截图缺失或格式无效')
    pending=[]
    for sheet in observation.get('stylesheets',[]):
        data=local_file(stage,sheet['file']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=sheet['sha256']:raise ValueError('样式表摘要不一致')
        target=Path(run)/'evidence'/'stylesheets'/(sheet['sha256']+'.css')
        pending.append((target,data));sheet['file']=target.relative_to(run).as_posix()
    incoming=Path(run)/'incoming';incoming.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=incoming,suffix='.jpg',delete=False) as temp:
        temp.write(image);shot=Path(temp.name)
    try:
        # Source files are content-addressed. Failed ingest leaves the previous snapshot intact.
        with evidence_lock(run):
            for target,data in pending:
                target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists():target.write_bytes(data)
            return _ingest(run,observation,'local-cdp',row['viewport'],row['state'],row['url'],shot.relative_to(run).as_posix(),refresh)
    finally:shot.unlink(missing_ok=True)


def capture(run, target=None, viewport=None, state='default', selector=None, refresh=False,
            max_elements=1200, checkpoints=3, max_matched=80):
    run=Path(run).resolve();plan=plan_for(run)
    if state not in {'default','hover','focus'} or (state!='default' and not selector):raise ValueError('hover/focus 需要 --selector')
    if selector and (len(selector)>500 or '\n' in selector):raise ValueError('selector 无效')
    if not 1<=max_elements<=5000 or not 1<=checkpoints<=4 or not 0<=max_matched<=500:raise ValueError('采样预算无效')
    pages=[url(target)] if target else plan['pages']
    if any(p not in plan['pages'] for p in pages):raise ValueError('URL 不在计划内')
    views=[v for v in plan['viewports'] if not viewport or v['name']==viewport]
    if not views:raise ValueError('视口不在计划内')
    current=coverage(run)
    existing={row['id']:row for row in index_for(run)['snapshots']}
    snapshot_state=state if state=='default' else state+'-'+hashlib.sha256(selector.encode()).hexdigest()[:10]
    states=[snapshot_state]+(['scroll-'+str(i).zfill(2) for i in range(1,checkpoints)] if state=='default' else [])
    active={row['id']:row for row in current['snapshots']}
    failures=current['failures'];jobs=[];changed=set();requests=[]
    for page in pages:
        for view in views:
            config={'collectorVersion':5,'width':view['width'],'height':view['height'],'maxElements':max_elements,
                'maxMatched':max_matched,'checkpoints':checkpoints if state=='default' else 1,'maxSteps':24,
                'state':snapshot_state,'selector':selector if state!='default' else None}
            sha=digest(config)
            pending=any((f.get('url')==page and f.get('viewport')==view['name'] and f.get('state') in states) or
                any(t['url']==page and t['viewport']==view['name'] and t['state'] in states for t in f.get('tasks',[]))
                for f in failures if f.get('stage')!='cleanup')
            missing=refresh or pending
            for label in states:
                key=snapshot_key(page,view['name'],label);row=active.get(key)
                if not row or row.get('configSha256')!=sha:missing=True;changed.add(key)
            request={'url':page,'viewport':view['name'],'state':snapshot_state,'states':states,'config':config}
            requests.append(request)
            if missing:
                if refresh or pending:changed.update(snapshot_key(page,view['name'],label) for label in states)
                jobs.append({'url':page,'viewport':view['name'],'width':view['width'],'height':view['height'],
                    'state':state,'snapshotState':snapshot_state,'selector':selector,'captureConfig':config})
    if not jobs:
        resolve_failures(run)
        return {'status':'unchanged','message':'当前配置与计划坐标已采集','saved':0,'reused':len(states)*len(pages)*len(views),
                'failures':coverage(run)['failures']}
    environment=doctor()
    if not environment['ready']:raise ValueError('需要 Node.js 22+ 和 Chrome/Chromium；先运行 doctor，必要时配置 SPECKIT_CHROME_PATH')
    register_requests(run,requests)
    attempt_id=uuid.uuid4().hex
    for job in jobs:job['attemptId']=attempt_id
    allowed=[origin(plan['originalUrl'])]+[origin(p) for p in plan.get('authorizedOrigins',[])]
    allowed_urls=[scheme+'://'+('['+host+']' if ':' in host else host)+(':'+str(port) if port!=(443 if scheme=='https' else 80) else '') for scheme,host,port in allowed]
    with tempfile.TemporaryDirectory(prefix='speckit-capture-') as directory:
        stage=Path(directory)
        request={'jobs':jobs,'allowedOrigins':allowed_urls,'maxElements':max_elements,'checkpoints':checkpoints,
            'maxMatched':max_matched,'maxSteps':24,'readyTimeout':15000,'settleMs':500,'dwellMs':300}
        write_json(stage/'request.json',request)
        proc=subprocess.Popen([shutil.which('node'),str(Path(__file__).with_name('capture_browser.mjs')),
            '--request',str(stage/'request.json'),'--out',str(stage)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        timed_out=False;cancelled=False
        try:stdout,stderr=proc.communicate(timeout=max(90,len(jobs)*120))
        except (subprocess.TimeoutExpired,KeyboardInterrupt) as error:
            cancelled=isinstance(error,KeyboardInterrupt);timed_out=not cancelled;proc.terminate()
            try:stdout,stderr=proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();stdout,stderr=proc.communicate()
        result=read_json(stage/'result.json') if (stage/'result.json').exists() else {'snapshots':[],'failures':[]}
        saved=[]
        for row in result['snapshots']:
            try:
                key=snapshot_key(row['url'],row['viewport'],row['state'])
                saved.append(commit_snapshot(run,stage,row,refresh or key in changed))
            except (OSError,KeyError,ValueError) as error:result['failures'].append({**row,'stage':'commit','message':str(error)})
        if cancelled or timed_out or (proc.returncode and not result['failures']):
            tasks=[{'url':job['url'],'viewport':job['viewport'],'state':label,'configSha256':digest(job['captureConfig'])}
                for job in jobs for label in states]
            result['failures'].append({'stage':'browser','attemptId':attempt_id,'tasks':tasks,
                'message':'Capture cancelled' if cancelled else 'Browser timeout' if timed_out else (stderr.strip()[:500] or 'Browser failed')})
        for failure in result['failures']:
            job=next((j for j in jobs if j['url']==failure.get('url') and j['viewport']==failure.get('viewport')),None)
            if job and 'tasks' not in failure:failure['tasks']=[{'url':job['url'],'viewport':job['viewport'],'state':failure['state'],'configSha256':digest(job['captureConfig'])}]
            record_failure(run,{**failure,'attemptId':attempt_id})
        resolve_failures(run)
        cov=coverage(run);write_json(run/'evidence'/'coverage.json',cov)
        return {'status':'partial' if result['failures'] else 'captured','cancelled':cancelled,'saved':sum(row['status']=='saved' for row in saved),'reused':sum(row['status']=='unchanged' for row in saved),
            'pages':cov['pageCount'],'snapshots':cov['snapshotCount'],'failures':result['failures']}
