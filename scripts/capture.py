"""Validate a plan and commit staged local CDP captures; no API credentials or cloud backend."""
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from common import coverage, evidence_lock, index_for, ingest, local_file, now, origin, plan_for, read_json, snapshot_key, url, write_json


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
        for target,data in pending:
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():target.write_bytes(data)
        return ingest(run,observation,'local-cdp',row['viewport'],row['state'],row['url'],shot.relative_to(run).as_posix(),refresh)
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
    existing={row['id']:row for row in index_for(run)['snapshots']}
    snapshot_state=state if state=='default' else state+'-'+hashlib.sha256(selector.encode()).hexdigest()[:10]
    states=[snapshot_state]+(['scroll-'+str(i).zfill(2) for i in range(1,checkpoints)] if state=='default' else [])
    jobs=[];changed=set()
    for page in pages:
        for view in views:
            missing=False
            for label in states:
                key=snapshot_key(page,view['name'],label);row=existing.get(key)
                if not row:missing=True;continue
                old=read_json(local_file(run,row['file']))
                if any(abs(old['viewport'][k]-view[k])>1 for k in ('width','height')):
                    missing=True;changed.add(key)
            if refresh or missing:jobs.append({'url':page,'viewport':view['name'],'width':view['width'],
                'height':view['height'],'state':state,'snapshotState':snapshot_state,'selector':selector})
    if not jobs:
        coverage(run)  # Do not reuse an index whose observations/images/CSS were corrupted.
        return {'status':'unchanged','message':'计划坐标已采集'}
    environment=doctor()
    if not environment['ready']:raise ValueError('需要 Node.js 22+ 和 Chrome/Chromium；先运行 doctor，必要时配置 SPECKIT_CHROME_PATH')
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
            result['failures'].append({'stage':'browser','message':'Capture cancelled' if cancelled else 'Browser timeout' if timed_out else (stderr.strip()[:500] or 'Browser failed')})
        for failure in result['failures']:record_failure(run,failure)
        cov=coverage(run);write_json(run/'evidence'/'coverage.json',cov)
        return {'status':'partial' if result['failures'] else 'captured','cancelled':cancelled,'saved':len(saved),
            'pages':cov['pageCount'],'snapshots':cov['snapshotCount'],'failures':result['failures']}
