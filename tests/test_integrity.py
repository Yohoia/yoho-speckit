"""End-to-end data protection and model regressions for the final integrity audit."""
import copy
import gzip
import hashlib
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor,TimeoutError
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import coverage,digest,ingest,index_for,local_file,now,read_json,write_json
from design import init_run
from exporter import export,verify
from model import build
from storage import clean
from capture import record_failure
from ledger import register_requests,resolve_failures
from test_pipeline import observation,review


class IntegrityTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def run_for(self,name):
        run=self.root/name;init_run('https://fixture.test/',run,'single',None)
        p=read_json(run/'plan.json');p['viewports']=p['viewports'][:1];write_json(run/'plan.json',p)
        return run
    def history(self,run):
        obs=observation();rule={'selector':'#primary','values':{'--old':'#123456'},'active':True}
        obs['sourceRules']=[rule];obs['elements'][0]['matchedRules']=[rule]
        css=run/'evidence/stylesheets/old.css';css.parent.mkdir(parents=True);css.write_text('body{color:#123456}')
        obs['stylesheets']=[{'file':css.relative_to(run).as_posix(),'sha256':hashlib.sha256(css.read_bytes()).hexdigest()}]
        ingest(run,obs,'local-cdp','desktop');old=index_for(run)['snapshots'][0]
        envelope=json.loads(gzip.decompress(local_file(run,old['file']).read_bytes()))
        dependencies=[old['file'],obs['stylesheets'][0]['file']]+[r['file'] for r in envelope['shared'].values()]
        fresh=observation();fresh['capturedAt']=now();ingest(run,fresh,'local-cdp','desktop',replace=True)
        return old,dependencies

    def test_cleanup_normalizes_pin_and_archive_aliases_and_keeps_dependencies(self):
        for mode in ('pins','archive'):
            for prefix in ('','./','unused/../'):
                with self.subTest(mode=mode,prefix=prefix):
                    run=self.run_for(mode+str(len(list(self.root.iterdir()))));old,dependencies=self.history(run)
                    if mode=='pins':write_json(run/'evidence/pins.json',[prefix+old['file']])
                    else:write_json(run/'archive.json',{'coverage':{'snapshots':[{**old,'file':prefix+old['file']}]}})
                    result=clean(run,apply=True,keep_history=0)
                    self.assertFalse(set(dependencies)&{r['file'] for r in result['files']})
                    self.assertTrue(all(local_file(run,p).is_file() for p in dependencies))
                    self.assertEqual(coverage(run)['snapshotCount'],1)

    def test_invalid_pins_never_mutate_index_or_evidence(self):
        run=self.run_for('bad-pins');old,dependencies=self.history(run)
        for pins in ({'files':[old['file']]},[7],['../escape'],['evidence/observations/missing.json'],['plan.json']):
            with self.subTest(pins=pins):
                write_json(run/'evidence/pins.json',pins);before=(run/'evidence/index.json').read_bytes()
                for apply in (False,True):
                    with self.assertRaises(ValueError):clean(run,apply=apply,keep_history=0)
                    self.assertEqual((run/'evidence/index.json').read_bytes(),before)
                    self.assertTrue(all(local_file(run,p).exists() for p in dependencies))

    def test_stale_document_identity_cannot_reenter_a_model(self):
        for case in ('legacy-error','mismatched-identity','valid-future-response'):
            run=self.run_for(case);obs=observation()
            obs['mainDocument']={'frameId':'main','loaderId':'initial','status':200,'url':obs['url']}
            if case=='legacy-error':
                obs['url']='https://fixture.test/error'
                obs['health']={'failures':[{'type':'Document','frameId':'main','loaderId':'later','url':obs['url'],'status':404}]}
            elif case=='mismatched-identity':obs['documentIdentity']={'frameId':'main','loaderId':'later'}
            else:
                obs['documentIdentity']={'frameId':'main','loaderId':'initial'}
                obs['health']={'failures':[{'type':'Document','frameId':'main','loaderId':'future','url':obs['url'],'status':404}]}
            ingest(run,obs,'local-cdp','desktop',requested_url='https://fixture.test/')
            if case!='valid-future-response':
                self.assertEqual(coverage(run)['snapshotCount'],0)
                with self.assertRaisesRegex(ValueError,'DOM'):build(run)
            else:self.assertEqual(coverage(run)['snapshotCount'],1)

    def test_form_styles_work_for_new_and_legacy_observations(self):
        for case in ('new','legacy','non-text-control'):
            run=self.run_for(case);obs=observation();el=obs['elements'][0]
            el.update(tag='input',hasText=False,text='')
            el['styles'].update(fontFamily='Georgia',fontSize='37px',fontWeight='700',lineHeight='43px',color='rgb(161, 83, 188)')
            if case!='legacy':el['textStyleRelevant']=case!='non-text-control'
            ingest(run,obs,'local-cdp','desktop');_,m=build(run);review(m);write_json(run/'design.json',m)
            export(run);self.assertEqual(verify(run)['status'],'passed')
            fonts=[t['value'] for t in m['tokens'] if t['category']=='font']
            colors=[t['value'] for t in m['tokens'] if t['category']=='color']
            self.assertEqual('Georgia' in fonts,case!='non-text-control')
            self.assertEqual('rgb(161, 83, 188)' in colors,case!='non-text-control')

    def test_side_border_variants_survive_model_and_markdown(self):
        run=self.run_for('borders');obs=observation();first,second=obs['elements']
        first['styles'].update(borderTopWidth='0px',borderRightWidth='4px',borderRightStyle='solid',borderRightColor='rgb(204, 51, 68)')
        second.update(tag='button',role='button',hasText=True);second['styles']=copy.deepcopy(first['styles'])
        second['styles']['borderRightStyle']='dashed'
        ingest(run,obs,'local-cdp','desktop');_,m=build(run);review(m);write_json(run/'design.json',m)
        self.assertEqual(len(m['components']),2);export(run);verify(run)
        for name in ('DESIGN.md','DESIGN.compact.md'):
            text=(run/name).read_text();self.assertIn('Right border 4px dashed #cc3344',text)
            self.assertIn('Right border 4px solid #cc3344',text)

    def test_model_publication_cannot_race_history_cleanup(self):
        run=self.run_for('publication');ingest(run,observation(),'local-cdp','desktop')
        old=index_for(run)['snapshots'][0];ready=threading.Event();release=threading.Event()
        import model as model_module
        original_write=model_module.write_json
        def delayed_publish(path,data):
            if Path(path).name=='design.json':
                ready.set()
                if not release.wait(3):raise AssertionError('Model publication was not released')
            return original_write(path,data)
        def refresh_and_clean():
            fresh=observation();fresh['capturedAt']=now()
            ingest(run,fresh,'local-cdp','desktop',replace=True)
            return clean(run,apply=True,keep_history=0)
        with patch.object(model_module,'write_json',side_effect=delayed_publish),ThreadPoolExecutor(max_workers=2) as pool:
            building=pool.submit(build,run)
            self.assertTrue(ready.wait(2))
            maintenance=pool.submit(refresh_and_clean)
            try:
                with self.assertRaises(TimeoutError):maintenance.result(timeout=.1)
            finally:release.set()
            building.result();maintenance.result()
        archived=read_json(run/'design.json')['coverage']['snapshots'][0]
        self.assertEqual(archived['file'],old['file'])
        self.assertTrue(local_file(run,archived['file']).is_file())

    def test_changed_configuration_supersedes_task_failure_without_faking_resolution(self):
        run=self.run_for('failure-config');old={'width':1440,'height':1000,'maxElements':10}
        task={'url':'https://fixture.test/','viewport':'desktop','state':'default','configSha256':digest(old)}
        record_failure(run,{**task,'tasks':[task],'attemptId':'failed','stage':'capture','message':'Old configuration failed'})
        new={**old,'maxElements':20}
        register_requests(run,[{'url':task['url'],'viewport':'desktop','state':'default','states':['default'],'config':new}])
        obs=observation();obs.update(captureConfig=new,captureAttempt='new',capturedAt=now())
        ingest(run,obs,'local-cdp','desktop');resolve_failures(run)
        failure=index_for(run)['failures'][0]
        self.assertIn('supersededAt',failure);self.assertNotIn('resolvedAt',failure)
        self.assertFalse(coverage(run)['failures'])


if __name__=='__main__':unittest.main()
