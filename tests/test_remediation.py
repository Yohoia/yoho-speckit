"""Regression cases for current scope, real variants, provenance and lossless storage."""
import copy
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from test_pipeline import observation,review
from common import ingest,coverage,write_json,read_json,index_for,local_file,digest,now
from design import init_run
from model import build,validate_model
from exporter import export,verify
from storage import compact,clean
from ledger import register_requests,resolve_failures
from capture import record_failure

class RemediationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.run=Path(self.temp.name)/'run'
        init_run('https://fixture.test/',self.run,'standard',None)
    def tearDown(self):self.temp.cleanup()
    def plan(self,edit):
        p=read_json(self.run/'plan.json');edit(p);write_json(self.run/'plan.json',p)
    def model(self):
        _,m=build(self.run);review(m);write_json(self.run/'design.json',m);return m
    def sample(self,obs=None,view='desktop',state='default',replace=False):
        return ingest(self.run,obs or observation(),'local-cdp',view,state,replace=replace)
    def test_removed_page_cannot_contribute_tokens_or_missing_entries(self):
        self.plan(lambda p:p['pages'].append('https://fixture.test/other'))
        self.sample();other=observation();other['url']='https://fixture.test/other'
        for el in other['elements']:el['styles']['backgroundColor']='rgb(199, 21, 133)'
        self.sample(other)
        self.plan(lambda p:p.update(pages=['https://fixture.test/']))
        m=self.model();self.assertEqual(m['coverage']['pageCount'],1)
        self.assertFalse(any(t['value']=='rgb(199, 21, 133)' for t in m['tokens']))
        self.assertTrue(all(x['url']=='https://fixture.test/' for x in m['coverage']['missing']))
        self.assertEqual(len(index_for(self.run)['snapshots']),2)
    def test_changed_viewport_does_not_become_valid_by_rebuilding(self):
        self.sample();mobile=observation(390,844)
        for e in mobile['elements']:e['styles']['fontSize']='28px'
        self.sample(mobile,'mobile');old=self.model()
        self.plan(lambda p:p['viewports'][0].update(width=1200))
        _,m=build(self.run)
        self.assertEqual(m['coverage']['snapshotCount'],1)
        self.assertEqual({t['value']['fontSize'] for t in m['tokens'] if t['category']=='typography'},{'28px'})
        with self.assertRaises(ValueError):validate_model(old,self.run)
    def test_removed_origin_and_old_error_documents_are_excluded(self):
        self.plan(lambda p:p['authorizedOrigins'].append('https://other.test'))
        o=observation();o['url']='https://other.test/'
        ingest(self.run,o,'local-cdp','desktop',requested_url='https://fixture.test/')
        self.plan(lambda p:p.update(authorizedOrigins=[]))
        self.assertEqual(coverage(self.run)['snapshotCount'],0)
        o=observation();o['health']={'failures':[{'url':o['url'],'status':404}]};self.sample(o,replace=True)
        with self.assertRaisesRegex(ValueError,'DOM'):build(self.run)
    def test_image_http_failure_does_not_invalidate_main_page(self):
        o=observation();o['health']={'failures':[{'url':o['url']+'image.png','status':404}]};self.sample(o)
        self.assertEqual(coverage(self.run)['snapshotCount'],1)
    def test_full_button_appearance_and_repeated_contexts_are_retained(self):
        o=observation();o['elements'][1]['tag']='button';o['elements'][1]['role']='button'
        o['elements'][1]['styles'].update(color='rgb(255,255,255)',paddingTop='24px')
        self.sample(o);self.sample(copy.deepcopy(o),state='scroll-01')
        m=self.model();self.assertEqual(len(m['components']),2)
        self.assertTrue(all({c['state'] for c in x['contexts']}=={'default','scroll-01'} for x in m['components']))
        self.assertTrue(any(x['styles']['paddingTop']=='24px' for x in m['components']))
    def test_component_limit_is_reported_and_contexts_cover_both_views(self):
        o=observation();base=o['elements'][0];o['elements']=[]
        for i in range(90):
            e=copy.deepcopy(base);e.update(id='e'+str(i+1),selector='#b'+str(i));e['styles']['backgroundColor']='rgb('+str(i)+',80,120)';o['elements'].append(e)
        self.sample(o);mobile=copy.deepcopy(o);mobile['viewport'].update(width=390,height=844);self.sample(mobile,'mobile')
        m=self.model();self.assertEqual(len(m['components']),64)
        self.assertEqual(m['coverage']['omittedComponentCandidates'],26)
        self.assertTrue(all({c['viewport'] for c in x['contexts']}=={'desktop','mobile'} for x in m['components']))
        self.assertTrue(any('Component candidate limit' in x for x in m['coverage']['gaps']))
    def source_model(self,explicit=False,variable=False):
        o=observation();e=o['elements'][0];e['styles']['backgroundColor']='rgb(0,255,0)'
        e['styleDeclarations']={} if explicit or variable else {'background-color':'#00ff00'}
        e['matchedRules']=[{'selector':'.parent','values':{'background-color':'red','font-family':'Parent Font','--brand':'#00ff00'},
            'active':True,'inherited':True,'ancestorSelector':'.parent','ancestorDepth':1,'origin':'regular'}]
        if explicit or variable:e['matchedRules'].insert(0,{'selector':'#primary','values':{'background-color':'inherit' if explicit else 'var(--brand)'},'active':True,'inherited':False})
        self.sample(o);m=self.model();export(self.run);return read_json(self.run/'design-tokens.json')
    def test_non_inherited_background_not_attributed_to_parent(self):
        j=self.source_model();green=next(t for t in j['color'].values() if t['$value']=='#00ff00')
        self.assertFalse(any(d['selector']=='.parent' for d in green['$extensions']['org.yoho-design-extractor']['sourceDeclarations']))
        font=next(iter(j['font'].values()))
        self.assertTrue(any(d.get('inherited') and d.get('ancestorSelector')=='.parent' for d in font['$extensions']['org.yoho-design-extractor']['sourceDeclarations']))
    def test_explicit_inherit_and_variable_ancestors_are_traceable(self):
        j=self.source_model(explicit=True);green=next(t for t in j['color'].values() if t['$value']=='#00ff00')
        self.assertTrue(any(d.get('inherited') for d in green['$extensions']['org.yoho-design-extractor']['sourceDeclarations']))
    def test_variable_dependency_preserves_ancestor_without_false_background(self):
        j=self.source_model(variable=True);green=next(t for t in j['color'].values() if t['$value']=='#00ff00')
        declarations=green['$extensions']['org.yoho-design-extractor']['sourceDeclarations']
        self.assertTrue(any(d.get('variableDeclarations',[{}])[0].get('ancestorSelector')=='.parent' for d in declarations if d.get('variableDeclarations')))
        self.assertFalse(any(d['selector']=='.parent' for d in declarations))
    def test_packed_roundtrip_matches_legacy_and_shares_rule_records(self):
        o=observation();rule={'selector':':root','values':{'--brand':'#00ff00'},'inherited':True,'active':True}
        for e in o['elements']:e['matchedRules']=[copy.deepcopy(rule)]*100
        o['sourceRules']=[rule];o['sourceVariables']=[{'name':'--brand','value':'#00ff00'}]
        self.sample(o);row=index_for(self.run)['snapshots'][0];path=local_file(self.run,row['file'])
        self.assertEqual(read_json(path),o);self.assertTrue(path.name.endswith('.json.gz'))
        envelope=json.loads(gzip.decompress(path.read_bytes()))
        table=read_json(local_file(self.run,envelope['shared']['matchedRuleTable']['file']))
        self.assertEqual(len(table),1)
        legacy=self.run/'legacy.json';write_json(legacy,o);self.assertEqual(read_json(legacy),read_json(path))
        total=path.stat().st_size+sum(p.stat().st_size for p in (self.run/'evidence/records').glob('*'))
        self.assertLess(total,legacy.stat().st_size/5)
    def test_shared_record_tampering_is_rejected(self):
        o=observation();o['sourceRules']=[{'selector':'body','values':{'color':'red'}}];self.sample(o)
        row=index_for(self.run)['snapshots'][0];path=local_file(self.run,row['file'])
        env=json.loads(gzip.decompress(path.read_bytes()));ref=local_file(self.run,env['shared']['sourceRules']['file'])
        write_json(ref,[])
        with self.assertRaisesRegex(ValueError,'摘要'):coverage(self.run)
    def test_corrupt_compressed_observation_is_a_controlled_error(self):
        self.sample();row=index_for(self.run)['snapshots'][0];local_file(self.run,row['file']).write_bytes(b'not gzip')
        with self.assertRaisesRegex(ValueError,'压缩JSON'):coverage(self.run)
    def test_lossless_compaction_keeps_exports_and_original_files(self):
        self.sample();row=index_for(self.run)['snapshots'][0];obs=read_json(local_file(self.run,row['file']))
        legacy='evidence/observations/legacy.json';write_json(local_file(self.run,legacy),obs);row['file']=legacy
        write_json(self.run/'evidence/index.json',{'snapshots':[row],'failures':[]})
        self.model();export(self.run)
        before={n:(self.run/n).read_bytes() for n in ('DESIGN.md','tokens.css','tailwind.css','design-tokens.json','preview.html')}
        compact(self.run);self.assertTrue(local_file(self.run,legacy).exists());export(self.run);verify(self.run)
        self.assertEqual(before,{n:(self.run/n).read_bytes() for n in before})
        self.assertEqual(compact(self.run)['updatedModels'],[])
    def test_cleanup_protects_history_archives_pins_and_shared_records(self):
        self.sample();old=index_for(self.run)['snapshots'][0]
        o=observation();o['capturedAt']=now();self.sample(o,replace=True)
        self.assertEqual(len(index_for(self.run)['history']),1)
        self.assertNotIn(old['file'],[f['file'] for f in clean(self.run)['files']])
        write_json(self.run/'archive.json',{'coverage':{'snapshots':[old]}})
        self.assertNotIn(old['file'],[f['file'] for f in clean(self.run,keep_history=0)['files']])
        (self.run/'archive.json').unlink();write_json(self.run/'evidence/pins.json',[old['file']])
        self.assertNotIn(old['file'],[f['file'] for f in clean(self.run,keep_history=0)['files']])
        (self.run/'evidence/pins.json').unlink();dry=clean(self.run,keep_history=0)
        self.assertIn(old['file'],[f['file'] for f in dry['files']]);self.assertTrue(local_file(self.run,old['file']).exists())
        clean(self.run,apply=True,keep_history=0);self.assertFalse(local_file(self.run,old['file']).exists());coverage(self.run)
    def test_cleanup_refuses_unknown_archive(self):
        self.sample();(self.run/'backup.zip').write_bytes(b'archive')
        with self.assertRaisesRegex(ValueError,'归档'):clean(self.run,apply=True)
    def test_cleanup_can_retire_removed_pages_without_touching_current_evidence(self):
        self.plan(lambda p:p['pages'].append('https://fixture.test/other'));self.sample()
        other=observation();other['url']='https://fixture.test/other';self.sample(other)
        removed=index_for(self.run)['snapshots'][1]
        self.plan(lambda p:p.update(pages=['https://fixture.test/']))
        dry=clean(self.run,keep_history=0);self.assertIn(removed['file'],[x['file'] for x in dry['files']])
        clean(self.run,apply=True,keep_history=0)
        self.assertEqual(len(index_for(self.run)['snapshots']),1);self.assertEqual(coverage(self.run)['pageCount'],1)
    def test_batch_failure_resolves_only_after_new_valid_task_evidence(self):
        config={'width':1440,'height':1000,'checkpoints':1}
        request={'url':'https://fixture.test/','viewport':'desktop','state':'default','states':['default'],'config':config}
        register_requests(self.run,[request]);o=observation();o.update(captureConfig=config,captureAttempt='old');self.sample(o)
        task={'url':o['url'],'viewport':'desktop','state':'default','configSha256':digest(config)}
        record_failure(self.run,{'stage':'browser','attemptId':'failed','tasks':[task],'message':'timeout'})
        resolve_failures(self.run);self.assertTrue(coverage(self.run)['failures'])
        o['capturedAt']=now();o['captureAttempt']='retry';self.sample(o,replace=True);resolve_failures(self.run)
        self.assertFalse(coverage(self.run)['failures']);self.assertTrue(index_for(self.run)['failures'][0]['resolvedAt'])

if __name__=='__main__':unittest.main()
