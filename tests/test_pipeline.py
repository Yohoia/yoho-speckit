import copy
import io
import json
import os
import sys
import tempfile
import gzip
import base64
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import ingest, coverage, read_json, write_json, plan_for, index_for, local_file
from design import init_run, doctor
from model import build, validate_model, validate_value
from exporter import export, verify, css_values, tokens_json
from capture_firecrawl import capture, ApiClient, ProviderError, interact_result, download_capture


def observation(width=1440,height=1000):
    styles={'color':'rgb(23, 23, 23)','backgroundColor':'rgb(255, 255, 255)',
        'backgroundImage':'linear-gradient(90deg, rgb(255, 0, 0), rgb(0, 0, 255))',
        'fontFamily':'"Test Sans", sans-serif','fontSize':'16px','fontWeight':'400','lineHeight':'24px',
        'letterSpacing':'0px','fontFeatureSettings':'normal','fontVariationSettings':'normal',
        'textTransform':'none','paddingTop':'12px','paddingRight':'16px','paddingBottom':'12px',
        'paddingLeft':'16px','gap':'normal','borderTopLeftRadius':'6px',
        'boxShadow':'rgba(0, 0, 0, 0.1) 0px 2px 4px 0px'}
    return {'schemaVersion':1,'method':'dom-computed-style','url':'https://fixture.test/',
        'title':'Fixture','capturedAt':'2026-01-01T00:00:00Z','viewport':{'width':width,'height':height,'dpr':1},
        'fontStatus':'loaded','sampling':{'truncated':False},'inaccessibleStylesheets':[],
        'elements':[{'id':'e1','selector':'#primary','tag':'button','role':'button','text':'Continue',
                     'hasText':True,'styles':styles},
                    {'id':'e2','selector':'#secondary','tag':'p','role':'','text':'Body',
                     'hasText':True,'styles':{**styles,'fontWeight':'500'}}],
        'links':[{'url':'https://fixture.test/pricing','label':'Pricing','inNavigation':True}]}


def review(model):
    model['review']['status']='reviewed'
    model['overview']={'tagline':'Fixture reference','description':'Measured fixture style combinations.',
        'status':'inferred','evidenceIds':[model['tokens'][0]['evidenceIds'][0]]}
    return model


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.run=Path(self.temp.name)/'run'
        init_run('https://fixture.test/',self.run,'standard',None)

    def tearDown(self): self.temp.cleanup()

    def model(self):
        ingest(self.run,observation(),'browser','desktop')
        ingest(self.run,observation(390,844),'browser','mobile')
        _,model=build(self.run);review(model);write_json(self.run/'design.json',model)
        return model

    def test_default_budget_and_single(self):
        plan=plan_for(self.run);self.assertEqual((plan['targetPages'],plan['maxPages']),(3,5))
        self.assertEqual(len(plan['pages']),1)
        self.assertEqual(init_run('https://fixture.test/',self.run,'standard',None)['status'],'unchanged')
        with self.assertRaises(ValueError):init_run('https://another.test/',self.run,'single',None)

    def test_plan_limits_origin_and_duplicates(self):
        plan=plan_for(self.run)
        for pages in [['https://fixture.test/']*2,['https://fixture.test/','https://other.test/'],
                      ['https://fixture.test/']+['https://fixture.test/'+str(i) for i in range(5)]]:
            write_json(self.run/'plan.json',{**plan,'pages':pages})
            with self.assertRaises(ValueError):plan_for(self.run)
        with self.assertRaises(ValueError):init_run('https://fixture.test/',Path(self.temp.name)/'extra','extended',None)

    def test_ingest_resume_and_mismatched_view(self):
        first=ingest(self.run,observation(),'browser','desktop')
        self.assertEqual(ingest(self.run,observation(),'browser','desktop')['status'],'unchanged')
        self.assertEqual(len(index_for(self.run)['snapshots']),1)
        self.assertEqual(first['status'],'saved')
        with self.assertRaises(ValueError):ingest(self.run,observation(),'browser','mobile')

    def test_reject_summary_as_measurement(self):
        with self.assertRaises(ValueError):ingest(self.run,{'branding':{'color':'red'}},'browser','desktop')

    def test_real_values_roundtrip_and_typography_pairs(self):
        model=self.model();export(self.run)
        self.assertEqual(verify(self.run)['status'],'passed')
        gradient=next(t for t in model['tokens'] if t['category']=='gradient')
        self.assertEqual(json.loads(tokens_json(model))['gradient'][gradient['name']]['$value'],gradient['value'])
        types=[t for t in model['tokens'] if t['category']=='typography']
        self.assertEqual({t['value']['fontWeight'] for t in types},{'400','500'})
        for t in types:self.assertEqual(css_values(model)['--text-'+t['name']+'-line-height'],'24px')

    def test_unreviewed_candidate_cannot_be_delivered(self):
        ingest(self.run,observation(),'browser','desktop');build(self.run)
        with self.assertRaises(ValueError):export(self.run)

    def test_export_and_raw_tampering(self):
        self.model();export(self.run)
        (self.run/'tokens.css').write_text('wrong',encoding='utf-8')
        with self.assertRaises(ValueError):verify(self.run)
        export(self.run)
        path=local_file(self.run,index_for(self.run)['snapshots'][0]['file'])
        obj=read_json(path);obj['title']='changed';write_json(path,obj)
        with self.assertRaises(ValueError):verify(self.run)

    def test_observed_token_and_component_cannot_be_rewritten(self):
        model=self.model()
        changed=copy.deepcopy(model);changed['tokens'][0]['value']='rgb(0, 0, 0)'
        with self.assertRaises(ValueError):validate_model(changed,self.run)
        changed=copy.deepcopy(model);changed['components'][0]['styles']['color']='pink'
        with self.assertRaises(ValueError):validate_model(changed,self.run)

    def test_new_capture_does_not_overwrite_explanation(self):
        model=self.model();before=read_json(self.run/'design.json')
        obs=observation();obs['elements'][0]['styles']['color']='rgb(1, 2, 3)'
        ingest(self.run,obs,'browser','desktop','button-focus')
        path,new=build(self.run)
        self.assertEqual(path.name,'design.candidate.json')
        self.assertEqual(before,read_json(self.run/'design.json'))
        with self.assertRaises(ValueError):validate_model(model,self.run)
        self.assertNotEqual(model['coverage']['snapshots'],new['coverage']['snapshots'])

    def test_dimension_range_and_css_injection_rejected(self):
        for value in ['96-128px','16px; color:red','url(https://other.test/)', '</style>']:
            with self.assertRaises(ValueError):validate_value('spacing',value)
        validate_value('spacing','clamp(96px, 8vw, 128px)')

    def test_script_like_source_is_only_data(self):
        model=self.model();model['siteName']='</script><script>alert(1)</script>'
        write_json(self.run/'design.json',model);export(self.run)
        html=(self.run/'preview.html').read_text(encoding='utf-8')
        self.assertNotIn(model['siteName'],html)
        self.assertIn('\\u003c/script',html)

    def test_missing_states_and_page_candidates_visible(self):
        self.model();cov=coverage(self.run)
        self.assertEqual(cov['pageCount'],1);self.assertFalse(cov['missing'])
        self.assertIn('https://fixture.test/pricing',[x['url'] for x in cov['unvisitedCandidates']])
        self.assertTrue(any('hover/focus' in x for x in cov['gaps']))

    def test_sensitive_url_and_external_file_rejected(self):
        with self.assertRaises(ValueError):init_run('https://fixture.test/?token=private',Path(self.temp.name)/'bad','single',None)
        with self.assertRaises(ValueError):local_file(self.run,'../outside.json')

    def test_api_consumes_runtime_key_without_echo(self):
        with patch.dict(os.environ,{'FIRECRAWL_API_KEY':'unit-test-secret-do-not-use'}):
            client=ApiClient()
        class Response(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        requests=[]
        def open_request(request,timeout):
            requests.append(request)
            return Response(json.dumps({'success':True,'data':{'ok':True}}).encode())
        client.opener.open=open_request
        result=client.request('POST','/scrape',{'url':'https://fixture.test/'})
        self.assertEqual(requests[0].get_header('Authorization'),'Bearer unit-test-secret-do-not-use')
        self.assertNotIn('unit-test-secret',json.dumps(result))

    def test_cloud_failure_stops_once_and_cleans_session(self):
        class Failing:
            calls=0;stops=0
            def scrape(self,*args):return {'metadata':{'statusCode':200,'scrapeId':'00000000-0000-0000-0000-000000000000'}}
            def interact(self,*args):self.calls+=1;raise ProviderError('http_401')
            def stop(self,*args):self.stops+=1
        client=Failing()
        with self.assertRaises(ProviderError):capture(client,self.run,'https://fixture.test/',plan_for(self.run)['viewports'][0])
        self.assertEqual((client.calls,client.stops),(1,1))
        self.assertEqual(index_for(self.run)['failures'][0]['stage'],'interact')

    def test_provider_stdout_contract(self):
        result={'observation':observation(),'screenshot':None}
        self.assertEqual(interact_result({'stdout':'log\n'+json.dumps(result),'exitCode':0}),result)
        with self.assertRaises(ProviderError):interact_result({'exitCode':1,'stdout':'anything'})
        self.assertEqual(interact_result({'chunk':'example'}),{'chunk':'example'})
        with self.assertRaises(ProviderError):interact_result({'stdout':'partial','truncated':True})

    def test_local_doctor_never_queries_cloud(self):
        class Result:stdout='v24.21.0';returncode=0
        with patch('design.shutil.which',side_effect=lambda name:'/fake/'+name), patch('design.subprocess.run',return_value=Result()) as invoked:
            result=doctor()
        self.assertIsNone(result['firecrawlCli']['authenticated'])
        self.assertTrue(all('--status' not in call.args[0] for call in invoked.call_args_list))

    def test_concurrent_snapshots_preserve_both_rows(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            one=pool.submit(ingest,self.run,observation(),'browser','desktop')
            two=pool.submit(ingest,self.run,observation(390,844),'browser','mobile')
            one.result();two.result()
        self.assertEqual(len(index_for(self.run)['snapshots']),2)
        self.assertFalse(coverage(self.run)['missing'])

    def test_large_capture_chunk_integrity(self):
        raw=json.dumps(observation()).encode();compressed=gzip.compress(raw)
        files={'observation':compressed,'screenshot':b'\x89PNG\r\n\x1a\n'+b'x'*600000}
        manifest={k:{'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()} for k,v in files.items()}
        manifest['observation'].update(compression='gzip',rawBytes=len(raw))
        class Chunks:
            def interact(self,id,code):
                start,end=map(int,re.search(r'subarray\((\d+),(\d+)\)',code).groups())
                kind='observation' if '-observation.' in code else 'screenshot'
                return {'chunk':base64.b64encode(files[kind][start:end]).decode()}
        result=download_capture(Chunks(),'session','key',manifest)
        self.assertEqual(result['observation'],observation())
        self.assertEqual(base64.b64decode(result['screenshot']),files['screenshot'])
        manifest['screenshot']['sha256']='wrong'
        with self.assertRaises(ProviderError):download_capture(Chunks(),'session','key',manifest)

    def test_original_css_declarations_and_pseudos_are_traceable(self):
        obs=observation()
        obs['sourceRules']=[{'selector':'body','values':{'background':'#faf9f6'}}]
        obs['elements'][0]['pseudos']={'::before':{'backgroundImage':'linear-gradient(red, blue)'}}
        ingest(self.run,obs,'browser','desktop');_,model=build(self.run)
        self.assertTrue(any(t['value']=='linear-gradient(red, blue)' for t in model['tokens']))
        snap=model['coverage']['snapshots'][0]['id'];ref='source-background'
        model['evidence'].append({'id':ref,'snapshotId':snap,'selector':'body','property':'background',
            'value':'#faf9f6','method':'css-declaration','sourceRuleIndex':0})
        model['tokens'].append({'id':ref,'name':'paper','label':'Paper','category':'color','type':'color',
            'value':'#faf9f6','status':'observed','evidenceIds':[ref],'role':''})
        validate_model(model,self.run)
        model['evidence'][-1]['value']='#fff'
        with self.assertRaises(ValueError):validate_model(model,self.run)


if __name__=='__main__':unittest.main()
