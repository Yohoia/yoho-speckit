"""Current collection scope and task identity, separate from retained historical evidence."""
import hashlib
from pathlib import Path
from common import digest, index_for, read_json, local_file, plan_for, origin, url, now, write_json, evidence_lock, snapshot_key


def current_scope(row, plan):
    return row.get('requestedUrl',row.get('url')) in plan['pages'] and any(v['name']==row.get('viewport') for v in plan['viewports'])


def request_for(index,row):
    base=row['state'] if not row['state'].startswith('scroll-') else 'default'
    return index.get('requests',{}).get(snapshot_key(row['requestedUrl'],row['viewport'],base))


def main_document_failed(obs):
    document=obs.get('mainDocument',{});status=document.get('status')
    if isinstance(status,(int,float)):
        if status>=400:return True
        # Older collectors could attach the initial loader to a later error page.
        # Do not apply this heuristic to new snapshots whose live identity was checked.
        if not obs.get('documentIdentity') and document.get('frameId'):
            return any(f.get('type')=='Document' and f.get('frameId')==document['frameId'] and
                f.get('loaderId')!=document.get('loaderId') and f.get('url')==obs['url'] and f.get('status',0)>=400
                for f in obs.get('health',{}).get('failures',[]))
        return False
    # Legacy observations lack frame/loader identity. Typed subresources are never
    # promoted to documents merely because their URL equals the page URL.
    return any(f.get('url')==obs['url'] and f.get('status',0)>=400 and
        f.get('type') in {None,'Document'} for f in obs.get('health',{}).get('failures',[]))


def coverage(run):
    plan,index=plan_for(run),index_for(run);gaps=list(plan.get('gaps',[]));active=[];stale=[];excluded=[];candidates={}
    allowed=[origin(plan['originalUrl'])]+[origin(x) for x in plan.get('authorizedOrigins',[])]
    for row in index['snapshots']:
        if not current_scope(row,plan):excluded.append({'id':row['id'],'reason':'outside current page/viewport selection'});continue
        obs=read_json(local_file(run,row['file']))
        if digest(obs)!=row['sha256']:raise ValueError('证据摘要不一致：'+row['id'])
        if row.get('screenshot') and hashlib.sha256(local_file(run,row['screenshot']).read_bytes()).hexdigest()!=row.get('screenshotSha256'):
            raise ValueError('截图摘要不一致：'+row['id'])
        for sheet in obs.get('stylesheets',[]):
            if hashlib.sha256(local_file(run,sheet['file']).read_bytes()).hexdigest()!=sheet['sha256']:raise ValueError('原始样式表摘要不一致：'+row['id'])
        view=next(v for v in plan['viewports'] if v['name']==row['viewport']);reason=None
        request=request_for(index,row)
        if any(abs(obs['viewport'][k]-view[k])>1 for k in ('width','height')):reason='snapshot viewport differs from current plan'
        elif origin(obs['url']) not in allowed:reason='final origin no longer authorized'
        elif obs.get('documentIdentity') and any(obs['documentIdentity'].get(k)!=obs.get('mainDocument',{}).get(k) for k in ('frameId','loaderId')):
            reason='observation and main document identity differ'
        elif main_document_failed(obs):
            reason='main document HTTP error'
        elif request and (row['state'] not in request['states'] or row.get('configSha256')!=digest(request['config'])):
            reason='collection configuration/checkpoint no longer current'
        if reason:
            stale.append(row['id']);excluded.append({'id':row['id'],'reason':reason});gaps.append(row['id']+': '+reason);continue
        active.append(row)
        for link in obs.get('links',[]):
            try:
                target=url(link['url'])
                if origin(target)==origin(plan['originalUrl']) and target not in plan['pages']:candidates[target]=link
            except (KeyError,ValueError):continue
        for flag in ('truncated','declarationsTruncated'):
            if obs.get('sampling',{}).get(flag):gaps.append(row['id']+': '+flag)
        if obs.get('walkComplete') is False:gaps.append(row['id']+': scroll walk incomplete')
        if obs.get('fontStatus')!='loaded':gaps.append(row['id']+': fonts not ready')
        if obs.get('inaccessibleStylesheets'):gaps.append(row['id']+': some stylesheet declarations unreadable')
        if not row.get('screenshot'):gaps.append(row['id']+': screenshot missing')
        if obs.get('canvasCount'):gaps.append(row['id']+': canvas graphics not measured as DOM styles')
        gaps.extend(row['id']+': '+x for x in obs.get('gaps',[]))
        for field,label in [('failures','resource failures observed'),('errors','browser errors observed')]:
            if obs.get('health',{}).get(field):gaps.append(row['id']+': '+label)
        if obs.get('readiness',{}).get('unloadedImages'):gaps.append(row['id']+': images not ready')
    expected={(p,v['name'],'default') for p in plan['pages'] for v in plan['viewports']}
    for request in index.get('requests',{}).values():
        view=next((v for v in plan['viewports'] if v['name']==request['viewport']),None)
        if request['url'] in plan['pages'] and view and all(request['config'][k]==view[k] for k in ('width','height')):
            expected.update((request['url'],request['viewport'],state) for state in request['states'])
    successful={(r['requestedUrl'],r['viewport'],r['state']) for r in active}
    missing=[{'url':p,'viewport':v,'state':s} for p,v,s in sorted(expected-successful)]
    kinds={r['state'].split('-')[0] for r in active}
    unverified={'hover','focus','expanded'}-kinds
    if unverified:gaps.append('Unverified interaction kinds (hover/focus/expanded): '+', '.join(sorted(unverified)))
    failures=[]
    for failure in index['failures']:
        if failure.get('resolvedAt') or failure.get('supersededAt'):continue
        tasks=failure.get('tasks')
        if tasks is not None and not any(current_scope({'requestedUrl':t['url'],**t},plan) for t in tasks):continue
        if failure.get('url') and (failure['url'] not in plan['pages'] or failure.get('viewport') not in {v['name'] for v in plan['viewports']}):continue
        failures.append(failure)
    return {'planSha256':digest(plan),'plannedPages':plan['pages'],'pageCount':len({r['requestedUrl'] for r in active}),
            'snapshotCount':len(active),'snapshots':active,'missing':missing,'staleSnapshots':stale,
            'excludedSnapshots':excluded,'historyCount':len(index.get('history',[])),
            'failures':failures,'failureHistory':index['failures'],'gaps':sorted(set(gaps)),
            'unvisitedCandidates':sorted(candidates.values(),key=lambda x:(not x.get('inNavigation'),x['url'])),
            'selectionNotes':plan.get('selectionNotes',[])}


def register_requests(run, requests):
    with evidence_lock(run):
        index=index_for(run)
        for request in requests:index.setdefault('requests',{})[snapshot_key(request['url'],request['viewport'],request['state'])]=request
        write_json(Path(run)/'evidence'/'index.json',index)


def resolve_failures(run):
    cov=coverage(run);active={r['id']:r for r in cov['snapshots']};plan=plan_for(run)
    with evidence_lock(run):
        index=index_for(run)
        for failure in index['failures']:
            if failure.get('resolvedAt') or failure.get('supersededAt') or failure.get('stage')=='cleanup':continue
            tasks=failure.get('tasks')
            if tasks:
                in_scope=[]
                for task in tasks:
                    coordinate={'requestedUrl':task['url'],**task}
                    request=request_for(index,coordinate)
                    if current_scope(coordinate,plan) and (not request or (task['state'] in request['states'] and task['configSha256']==digest(request['config']))):
                        in_scope.append(task)
                if not in_scope:failure['supersededAt']=now();continue
                complete=all((row:=active.get(snapshot_key(t['url'],t['viewport'],t['state']))) and
                    row.get('configSha256')==t['configSha256'] and row.get('attemptId')!=failure.get('attemptId') and
                    row['capturedAt']>failure['capturedAt'] for t in in_scope)
                if complete:failure['resolvedAt']=now()
            elif not failure.get('url') and failure.get('stage')=='browser' and not cov['missing'] and active:
                failure['supersededAt']=now();failure['resolution']='Legacy unscoped failure superseded by verified current coordinates'
        write_json(Path(run)/'evidence'/'index.json',index)
