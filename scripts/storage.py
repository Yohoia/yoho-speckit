"""Lossless observation storage: compressed envelopes and content-addressed shared records."""
import copy
import gzip
import json
import os
import tempfile
from pathlib import Path
from common import digest, local_file, read_json, write_json, evidence_lock, index_for


def atomic_gzip(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    encoded=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as handle:
        handle.write(gzip.compress(encoded,mtime=0));temporary=Path(handle.name)
    try:os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def inline_rules(data):
    """Expand collector tables using shared objects, preserving the legacy logical schema."""
    if data.get('method')=='dom-computed-style' and 'matchedRuleTable' in data:
        table=data.pop('matchedRuleTable')
        for element in data['elements']:
            if 'matchedRuleRefs' in element:
                refs=element.pop('matchedRuleRefs')
                if any(type(i) is not int or not 0<=i<len(table) for i in refs):raise ValueError('匹配规则引用损坏')
                element['matchedRules']=[table[i] for i in refs]
    return data


def expand(path, data):
    if data.get('storageVersion')!=1:return inline_rules(data)
    root=Path(path).resolve().parent.parent.parent
    observation=data['observation']
    records={}
    for key,ref in data['shared'].items():
        value=read_json(local_file(root,ref['file']))
        if digest(value)!=ref['sha256']:raise ValueError('共享证据摘要不一致：'+key)
        records[key]=value
    for key in ('sourceRules','sourceVariables'):
        if key in records:observation[key]=records[key]
    if 'matchedRuleTable' in records:
        observation['matchedRuleTable']=records['matchedRuleTable'];inline_rules(observation)
    if digest(observation)!=data['logicalSha256']:raise ValueError('压缩观察逻辑摘要不一致')
    return observation


def store_observation(run, key, observation):
    run=Path(run).resolve();logical=digest(observation);packed=copy.deepcopy(observation)
    shared={}
    def record(name,value):
        sha=digest(value);relative='evidence/records/'+sha+'.json.gz';target=local_file(run,relative)
        if target.exists():
            if digest(read_json(target))!=sha:raise ValueError('现存共享记录损坏')
        else:atomic_gzip(target,value)
        shared[name]={'file':relative,'sha256':sha}
    for name in ('sourceRules','sourceVariables'):
        if name in packed:record(name,packed.pop(name))
    rules=[];positions={}
    for element in packed['elements']:
        if 'matchedRules' not in element:continue
        references=[]
        for rule in element.pop('matchedRules'):
            sha=digest(rule)
            if sha not in positions:positions[sha]=len(rules);rules.append(rule)
            references.append(positions[sha])
        element['matchedRuleRefs']=references
    if positions or any('matchedRuleRefs' in e for e in packed['elements']):record('matchedRuleTable',rules)
    path=run/'evidence'/'observations'/(key+'-'+logical[:16]+'.json.gz')
    if path.exists():
        if digest(read_json(path))!=logical:raise ValueError('现存压缩观察损坏')
    else:atomic_gzip(path,{'storageVersion':1,'logicalSha256':logical,'observation':packed,'shared':shared})
    return path


def compact(run):
    """Repack existing evidence without deleting original files or altering measured values."""
    run=Path(run).resolve();mapping={};before=after=0
    with evidence_lock(run):
        index=index_for(run)
        for row in index['snapshots']+index.get('history',[]):
            old=local_file(run,row['file']);obs=read_json(old)
            if digest(obs)!=row['sha256']:raise ValueError('旧观察摘要不一致')
            target=store_observation(run,row['id'],obs)
            mapping[row['file']]=target.relative_to(run).as_posix()
            before+=old.stat().st_size;after+=target.stat().st_size;row['file']=mapping[row['file']]
        # Update pointers only, including archived JSON models; annotations and values stay intact.
        models=[]
        for path in run.rglob('*.json'):
            if 'evidence' in path.relative_to(run).parts:continue
            if path.is_symlink():raise ValueError('无法安全更新符号链接模型：'+str(path.relative_to(run)))
            model=read_json(path)
            if not isinstance(model,dict) or not isinstance(model.get('coverage'),dict):continue
            changed=False
            for row in model['coverage'].get('snapshots',[]):
                if row.get('file') in mapping and row['file']!=mapping[row['file']]:row['file']=mapping[row['file']];changed=True
            if changed:write_json(path,model);models.append(path.relative_to(run).as_posix())
        write_json(run/'evidence'/'index.json',index)
    return {'status':'compacted','observationsBeforeBytes':before,'envelopesAfterBytes':after,
            'sharedRecordsBytes':sum(p.stat().st_size for p in (run/'evidence'/'records').glob('*.json.gz')),
            'updatedModels':models,'originalFilesRetained':True,'next':'export and verify reviewed models; clean is dry-run by default'}


def clean(run, apply=False, keep_history=None):
    """Explicit reference-checked pruning; all history is pinned unless a limit is requested."""
    run=Path(run).resolve()
    if keep_history is not None and (type(keep_history) is not int or keep_history<0):raise ValueError('历史保留数必须为非负整数')
    with evidence_lock(run):
        from common import coverage
        index=index_for(run);valid={r['id'] for r in coverage(run)['snapshots']}
        active=[r for r in index['snapshots'] if r['id'] in valid]
        history=index.get('history',[])+[r for r in index['snapshots'] if r['id'] not in valid]
        history.sort(key=lambda r:r['capturedAt']);retained=[];counts={}
        for row in reversed(history):
            count=counts.get(row['id'],0);counts[row['id']]=count+1
            if keep_history is None or count<keep_history:retained.append(row)
        retained.reverse();protected=set();queued=[]
        def identity(path):
            stat=path.stat();return stat.st_dev,stat.st_ino
        def reference(value,strict=False):
            if isinstance(value,dict):
                for item in value.values():reference(item)
            elif isinstance(value,list):
                for item in value:reference(item,strict)
            elif isinstance(value,str):
                # Resolve aliases before deciding whether this is managed evidence.
                # File identity also handles case aliases and hard links safely.
                if not strict and ('evidence' not in value.lower() or '://' in value):return
                try:path=local_file(run,value)
                except ValueError:
                    if strict:raise
                    return  # An external path in arbitrary metadata is not a managed file.
                if not path.relative_to(run).parts or path.relative_to(run).parts[0].lower()!='evidence' or not path.is_file():
                    if strict:raise ValueError('pins 必须指向运行目录内现存的证据文件：'+value)
                    return
                key=identity(path)
                if key not in protected:
                    protected.add(key)
                    if path.name.endswith(('.json','.json.gz')):queued.append(path)
        reference(active);reference(retained)
        pins=run/'evidence'/'pins.json'
        if pins.exists():
            pinned=read_json(pins)
            if not isinstance(pinned,list) or any(not isinstance(p,str) for p in pinned):raise ValueError('pins 必须为证据路径字符串数组')
            reference(pinned,strict=True)
        # Inspect every persisted JSON artifact outside evidence, including archive subdirectories.
        for path in run.rglob('*'):
            if path.relative_to(run).parts[0]=='evidence':continue
            if path.is_symlink():raise ValueError('存在未解析符号链接归档：'+str(path.relative_to(run)))
            if not path.is_file():continue
            if path.name.endswith(('.zip','.tar','.tgz','.tar.gz')):
                raise ValueError('存在未解析归档，无法证明清理安全：'+str(path.relative_to(run)))
            if path.name.endswith(('.json','.json.gz')):reference(read_json(path))
        while queued:
            path=queued.pop()
            raw=json.loads(gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes())
            reference(raw)
        candidates=[]
        for name in ('observations','screenshots','stylesheets','records'):
            for path in sorted((run/'evidence'/name).glob('*')):
                relative=path.relative_to(run).as_posix()
                if path.is_file() and not path.is_symlink() and identity(path) not in protected:
                    candidates.append({'file':relative,'bytes':path.stat().st_size})
        if apply:
            index['snapshots']=active;index['history']=retained;write_json(run/'evidence'/'index.json',index)
            for item in candidates:local_file(run,item['file']).unlink()
        return {'status':'cleaned' if apply else 'dry-run','files':candidates,
                'bytes':sum(x['bytes'] for x in candidates),'retainedHistory':len(retained),'historyRemoved':len(history)-len(retained)}
