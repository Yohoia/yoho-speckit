"""End-to-end local browser checks; no public site, cloud or credential access."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from capture import capture, doctor
from common import coverage, index_for, local_file, read_json, write_json
from design import init_run
from model import build
from exporter import export, verify


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not doctor()['ready']:raise unittest.SkipTest('Node 22+ and local Chrome/Chromium required')
        fixture=(Path(__file__).parent/'fixtures'/'design.html').read_bytes()
        edges=(Path(__file__).parent/'fixtures'/'edge-cases.html').read_bytes()
        crowded=('<!doctype html><title>Crowded sampling</title><style>body{font:16px sans-serif}a{display:block}'
            '#target{background:#112233;padding:12px}#target:hover{background:#10ee20}#target:focus{background:#20b440}</style>'
            +''.join('<a href="/link'+str(i)+'">Link '+str(i)+'</a>' for i in range(1250))
            +'<button id="target"><span>Target action</span></button>').encode()
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path=='/favicon.ico':self.send_response(204);self.end_headers();return
                if self.path=='/redirect':self.send_response(302);self.send_header('Location','/');self.end_headers();return
                status={'/missing':404,'/forbidden':403,'/broken':500,'/missing-image':404}.get(self.path,200)
                body=edges if self.path=='/edges' else fixture+(b'<img src="/missing-image">' if self.path=='/image-failure' else b'')
                if self.path=='/crowded':body=crowded
                if self.path=='/same-url-resource':body+=b'<script>fetch(location.href,{method:"POST"})</script>'
                if self.path=='/hidden-target':body=b'<button id="target" style="display:none">Hidden</button>'
                if self.path in ('/client-404','/client-ok','/client-cross'):
                    destination='/missing' if self.path=='/client-404' else '/nav-final'
                    if self.path=='/client-cross':destination='http://localhost:'+str(self.server.server_port)+'/nav-final'
                    body=('<!doctype html><title>Entry</title><p>Original page</p><script>setTimeout(()=>location.replace('
                        +json.dumps(destination)+'),100)</script>').encode()
                if self.path=='/nav-final':body=b'<!doctype html><title>Final document</title><style>body{font:21px Georgia;color:#297a3a}</style><p>Final page</p>'
                if self.path=='/history':body=fixture+b'<script>history.replaceState(null,"","/history-view")</script>'
                if self.path in ('/scroll-nav','/scroll-error'):
                    destination='/nav-final' if self.path=='/scroll-nav' else '/missing'
                    body=('<!doctype html><title>Scroll entry</title><p>Entry</p><div style="height:2200px"></div>'
                        '<script>let moved=false;addEventListener("scroll",()=>{if(scrollY>0&&!moved){moved=true;location.replace('
                        +json.dumps(destination)+')}})</script>').encode()
                if self.path=='/controls-borders':body=b'''<!doctype html><title>Controls and borders</title><style>
body{font:16px Arial;color:black}input,textarea,select{font:700 37px/43px Georgia;color:#a153bc;background:white;padding:12px}
#check{font-family:CheckboxOnly}button{font:16px Arial;background:white;color:black;padding:12px;border:0;border-right:4px solid #cc3344}
#dashed{border-right-style:dashed}</style><label for="control">Input</label><input id="control" value="INPUT_NOT_TO_COLLECT" readonly>
<textarea id="area">TEXTAREA_NOT_TO_COLLECT</textarea><select id="choices"><option value="SELECT_NOT_TO_COLLECT">OPTION_NOT_TO_COLLECT</option></select>
<input id="check" type="checkbox"><button id="solid">Action</button><button id="dashed">Action</button>'''
                self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body)
            def do_POST(self):self.send_response(404);self.end_headers();self.wfile.write(b'API unavailable')
            def log_message(self,*args):pass
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.source='http://127.0.0.1:'+str(cls.server.server_port)+'/'

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,'server'):cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def test_real_cdp_capture_sources_states_and_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'run';init_run(self.source,run,'single',None)
            result=capture(run,checkpoints=3)
            self.assertEqual(result['status'],'captured',result)
            self.assertEqual(result['saved'],6)
            rows=index_for(run)['snapshots']
            observations=[read_json(local_file(run,row['file'])) for row in rows]
            self.assertTrue(all(row['backend']=='local-cdp' for row in rows))
            self.assertTrue(all(local_file(run,row['screenshot']).read_bytes().startswith(b'\xff\xd8') for row in rows))
            pseudo=next(el['pseudos']['::before'] for el in observations[0]['elements'] if el['selector']=='#decor')
            self.assertIn('gradient(',pseudo['backgroundImage'])
            self.assertTrue(any(el.get('renderedFonts') for el in observations[0]['elements']))
            pill=next(el for el in observations[0]['elements'] if el['selector']=='#pill')
            self.assertTrue(any('var(--brand)' in str(rule['values']) for rule in pill['matchedRules']))
            self.assertFalse(any('.never-matches'==rule['selector'] for rule in pill['matchedRules']))
            text=next(el for el in observations[0]['elements'] if el['selector']=='#body-text')
            self.assertTrue(any(rule['active'] and 'letter-spacing' in rule['values'] for rule in text['matchedRules']))
            self.assertTrue(all(local_file(run,sheet['file']).exists() for obs in observations for sheet in obs['stylesheets']))
            headings={row['viewport']:next(el['styles']['fontSize'] for el in obs['elements'] if el['tag']=='h1')
                for row,obs in zip(rows,observations) if row['state']=='default'}
            self.assertEqual(headings,{'desktop':'40px','mobile':'28px'})
            self.assertTrue(any(el['selector']=='#lazy' for obs in observations for el in obs['elements']))
            before=len(rows)
            with patch('capture.doctor',side_effect=AssertionError('completed configuration must not need browser')):
                self.assertEqual(capture(run,checkpoints=3)['status'],'unchanged')
            self.assertEqual(len(index_for(run)['snapshots']),before)
            self.assertEqual(capture(run,viewport='desktop',state='hover',selector='#pill',checkpoints=1)['status'],'captured')
            hover=next(r for r in index_for(run)['snapshots'] if r['state'].startswith('hover-'))
            hover_obs=read_json(local_file(run,hover['file']))
            self.assertEqual(next(el['styles']['backgroundColor'] for el in hover_obs['elements'] if el['selector']=='#pill'),'rgb(0, 112, 243)')
            self.assertEqual(capture(run,viewport='desktop',state='focus',selector='#pill',checkpoints=1)['status'],'captured')
            self.assertEqual(capture(run,viewport='desktop',state='hover',selector='nav a',checkpoints=1)['status'],'captured')
            self.assertEqual(len([r for r in index_for(run)['snapshots'] if r['state'].startswith('hover-')]),2)
            self.assertFalse(coverage(run)['missing'])
            _,model=build(run)
            model['review']['status']='reviewed'
            model['overview']={'tagline':'Controlled fixture','description':'Desktop/mobile default and sampled scroll/hover states.',
                'status':'inferred','evidenceIds':[model['tokens'][0]['evidenceIds'][0]]}
            write_json(run/'design.json',model)
            self.assertEqual(len(export(run)),9);self.assertEqual(verify(run)['status'],'passed')
            fonts=read_json(run/'design-tokens.json')['font']
            self.assertTrue(any(f['$extensions']['org.yoho-design-extractor']['renderedFonts'] for f in fonts.values()))
            data=read_json(run/'design-tokens.json')
            self.assertTrue(any(t['$extensions']['org.yoho-design-extractor']['sourceDeclarations'] for t in data['spacing'].values()))
            self.assertTrue(any(s.get('computedProperty')=='fontSize' for t in data['typography'].values()
                for s in t['$extensions']['org.yoho-design-extractor']['sourceDeclarations']))
            self.assertTrue(any('gradient(' in t['value'] for t in model['tokens'] if t['category']=='gradient'))

    def test_same_url_failed_post_is_only_a_resource_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'same-url';init_run(self.source+'same-url-resource',run,'single',None)
            p=read_json(run/'plan.json');p['viewports']=p['viewports'][:1];write_json(run/'plan.json',p)
            result=capture(run,checkpoints=1,max_matched=10)
            self.assertEqual(result['status'],'captured',result);self.assertEqual(result['snapshots'],1)
            row=coverage(run)['snapshots'][0];obs=read_json(local_file(run,row['file']))
            self.assertEqual(obs['mainDocument']['status'],200)
            self.assertTrue(any(f.get('status')==404 and f.get('type')=='Fetch' and f.get('url')==obs['url'] for f in obs['health']['failures']))
            self.assertTrue(any('resource failures' in g for g in coverage(run)['gaps']))
            _,m=build(run);m['review']['status']='reviewed'
            m['overview']={'description':'Healthy main document with failed API request','status':'inferred','evidenceIds':[m['tokens'][0]['evidenceIds'][0]]}
            write_json(run/'design.json',m);export(run);self.assertEqual(verify(run)['status'],'passed')

    def test_interaction_targets_survive_full_and_minimal_budgets(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'crowded';init_run(self.source+'crowded',run,'single',None)
            p=read_json(run/'plan.json');p['viewports']=p['viewports'][:1];write_json(run/'plan.json',p)
            capture(run,checkpoints=1,max_elements=1,max_matched=0)
            for state,selector,elements,matched,color in [('hover','#target',1200,1,'rgb(16, 238, 32)'),
                    ('focus','button:last-child',1,1,'rgb(32, 180, 64)'),('hover','#target',1,0,'rgb(16, 238, 32)')]:
                with self.subTest(state=state,elements=elements,matched=matched):
                    result=capture(run,viewport='desktop',state=state,selector=selector,checkpoints=1,max_elements=elements,max_matched=matched)
                    self.assertEqual(result['status'],'captured',result)
                    row=next(r for r in coverage(run)['snapshots'] if r['state'].startswith(state+'-'))
                    obs=read_json(local_file(run,row['file']));interaction=obs['interaction']
                    target=next(e for e in obs['elements'] if e['id']==interaction['elementId'])
                    self.assertEqual(target['selector'],interaction['elementSelector']);self.assertEqual(target['selector'],'#target')
                    self.assertEqual(target['styles']['backgroundColor'],color)
                    self.assertEqual(len(obs['elements']),elements)
                    if matched:self.assertTrue(target.get('matchedRules'))
                    else:
                        self.assertFalse(target.get('matchedRules'))
                        self.assertTrue(any('interaction target' in g and 'disabled' in g for g in obs['gaps']))
            self.assertFalse(coverage(run)['missing'])
            _,m=build(run);m['review']['status']='reviewed'
            m['overview']={'description':'Measured requested targets under bounded sampling','status':'inferred','evidenceIds':[m['tokens'][0]['evidenceIds'][0]]}
            self.assertTrue(any(t['value']=='rgb(16, 238, 32)' for t in m['tokens']))
            write_json(run/'design.json',m);export(run);self.assertEqual(verify(run)['status'],'passed')

    def test_unmeasurable_interaction_target_is_not_a_success(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'hidden';init_run(self.source+'hidden-target',run,'single',None)
            p=read_json(run/'plan.json');p['viewports']=p['viewports'][:1];write_json(run/'plan.json',p)
            result=capture(run,state='hover',selector='#target',max_elements=1,max_matched=1)
            self.assertEqual(result['status'],'partial');self.assertEqual(result['saved'],0)
            self.assertEqual(coverage(run)['snapshotCount'],0)

    def test_client_navigation_uses_live_loader_and_allows_history_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in ('client-404','client-ok','client-cross','history'):
                with self.subTest(path=path):
                    run=Path(directory)/path;init_run(self.source+path,run,'single',None)
                    p=read_json(run/'plan.json');p['viewports']=p['viewports'][:1];write_json(run/'plan.json',p)
                    result=capture(run,checkpoints=1,max_matched=10)
                    if path in ('client-404','client-cross'):
                        self.assertEqual(result['status'],'partial',result);self.assertEqual(coverage(run)['snapshotCount'],0)
                        self.assertIn('HTTP 404' if path=='client-404' else 'authorized scope',result['failures'][0]['message'])
                    else:
                        self.assertEqual(result['status'],'captured',result)
                        row=coverage(run)['snapshots'][0];obs=read_json(local_file(run,row['file']))
                        self.assertTrue(obs['url'].endswith('/nav-final' if path=='client-ok' else '/history-view'))
                        self.assertEqual(obs['mainDocument']['status'],200)
                        self.assertTrue(all(obs['documentIdentity'][k]==obs['mainDocument'][k] for k in ('frameId','loaderId')))
                        if path=='client-ok':self.assertEqual(obs['mainDocument']['url'],obs['url'])
                        else:self.assertNotEqual(obs['mainDocument']['url'],obs['url'])
                        _,m=build(run);m['review']['status']='reviewed'
                        m['overview']={'description':'Current loader and history route checked','status':'inferred','evidenceIds':[m['tokens'][0]['evidenceIds'][0]]}
                        write_json(run/'design.json',m);export(run);self.assertEqual(verify(run)['status'],'passed')

    def test_navigation_during_scroll_recovers_or_rejects_the_new_error(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in ('scroll-nav','scroll-error'):
                with self.subTest(path=path):
                    run=Path(directory)/path;init_run(self.source+path,run,'single',None)
                    p=read_json(run/'plan.json');p['viewports']=p['viewports'][:1];write_json(run/'plan.json',p)
                    result=capture(run,checkpoints=2,max_matched=10)
                    rows=coverage(run)['snapshots']
                    if path=='scroll-error':
                        self.assertEqual(result['status'],'partial',result);self.assertEqual(len(rows),1)
                        self.assertIn('HTTP 404',result['failures'][0]['message'])
                    else:
                        self.assertEqual(result['status'],'captured',result);self.assertEqual(len(rows),2)
                        observations=[read_json(local_file(run,r['file'])) for r in rows]
                        self.assertEqual(len({o['documentIdentity']['loaderId'] for o in observations}),2)
                        self.assertTrue(observations[-1]['url'].endswith('/nav-final'))
                    self.assertTrue(all(read_json(local_file(run,r['file']))['mainDocument']['status']==200 for r in rows))

    def test_controls_keep_style_tokens_without_values_and_borders_keep_variants(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'controls';init_run(self.source+'controls-borders',run,'single',None)
            p=read_json(run/'plan.json');p['viewports']=p['viewports'][:1];write_json(run/'plan.json',p)
            result=capture(run,checkpoints=1,max_matched=80);self.assertEqual(result['status'],'captured',result)
            obs=read_json(local_file(run,coverage(run)['snapshots'][0]['file']))
            self.assertNotIn('NOT_TO_COLLECT',json.dumps(obs))
            for selector in ('#control','#area','#choices'):
                el=next(e for e in obs['elements'] if e['selector']==selector)
                self.assertFalse(el['hasText']);self.assertEqual(el['text'],'');self.assertTrue(el['textStyleRelevant'])
                self.assertEqual(el['styles']['fontFamily'],'Georgia')
                if not el.get('renderedFonts'):self.assertTrue(any('rendered fonts unknown for '+selector==g for g in obs['gaps']))
            self.assertFalse(next(e for e in obs['elements'] if e['selector']=='#check')['textStyleRelevant'])
            _,m=build(run);m['review']['status']='reviewed'
            m['overview']={'description':'Control style privacy and border variants checked','status':'inferred','evidenceIds':[m['tokens'][0]['evidenceIds'][0]]}
            self.assertIn('Georgia',[t['value'] for t in m['tokens'] if t['category']=='font'])
            self.assertNotIn('CheckboxOnly',[t['value'] for t in m['tokens'] if t['category']=='font'])
            self.assertTrue(any(t['category']=='typography' and t['value']['fontSize']=='37px' for t in m['tokens']))
            self.assertTrue(any(t['category']=='color' and t['value']=='rgb(161, 83, 188)' for t in m['tokens']))
            buttons=[c for c in m['components'] if c['kind']=='button'];self.assertEqual(len(buttons),2)
            self.assertEqual({c['styles']['borderRightStyle'] for c in buttons},{'solid','dashed'})
            write_json(run/'design.json',m);export(run);self.assertEqual(verify(run)['status'],'passed')
            self.assertIn('#a153bc',(run/'tokens.css').read_text())
            text=(run/'DESIGN.md').read_text();self.assertIn('Right border 4px dashed #cc3344',text)
            self.assertIn('Right border 4px solid #cc3344',text)

    @unittest.skipIf(os.name=='nt','POSIX interrupt behavior; Windows awaits platform verification')
    def test_interrupt_cleans_owned_browser_and_keeps_recovery_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/'run';profiles=root/'profiles';profiles.mkdir()
            init_run(self.source,run,'single',None)
            process=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve().parents[1]/'scripts'/'design.py'),
                'capture','--run',str(run)],env={**os.environ,'TMPDIR':str(profiles)},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                deadline=time.monotonic()+15
                while not list(profiles.glob('speckit-chrome-*/DevToolsActivePort')):
                    if process.poll() is not None:self.fail('Collector stopped before Chrome startup: '+str(process.communicate()))
                    if time.monotonic()>deadline:self.fail('Chrome startup timed out')
                    time.sleep(.05)
                process.send_signal(signal.SIGINT)
                stdout,stderr=process.communicate(timeout=20)
                self.assertEqual(process.returncode,130,stdout+stderr)
                self.assertFalse(list(profiles.glob('speckit-chrome-*')))
                failures=index_for(run)['failures']
                self.assertTrue(any('cancelled' in row['message'].lower() for row in failures))
                commands=subprocess.run(['ps','-ax','-o','command='],capture_output=True,text=True,check=True).stdout
                self.assertNotIn('--user-data-dir='+str(profiles),commands)
            finally:
                if process.poll() is None:process.terminate();process.communicate(timeout=20)

    def test_main_http_errors_are_failures_but_redirect_and_image_errors_are_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in ('missing','forbidden','broken','image-failure','redirect'):
                run=Path(directory)/path;init_run(self.source+path,run,'single',None)
                p=read_json(run/'plan.json');p['viewports']=p['viewports'][:1];write_json(run/'plan.json',p)
                result=capture(run,checkpoints=1,max_matched=0)
                if path in ('missing','forbidden','broken'):
                    self.assertEqual(result['status'],'partial');self.assertEqual(coverage(run)['snapshotCount'],0)
                    self.assertIn('HTTP',result['failures'][0]['message'])
                else:
                    self.assertEqual(result['status'],'captured',result);self.assertEqual(coverage(run)['snapshotCount'],1)
                    if path=='image-failure':self.assertTrue(any('resource failures' in g for g in coverage(run)['gaps']))

    def test_checkpoint_budget_variants_provenance_and_retry_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'edges';init_run(self.source+'edges',run,'single',None)
            p=read_json(run/'plan.json');p['viewports']=p['viewports'][:1];write_json(run/'plan.json',p)
            self.assertEqual(capture(run,checkpoints=2,max_matched=0)['saved'],2)
            result=capture(run,checkpoints=3,max_matched=80);self.assertEqual(result['saved'],3)
            observations={r['state']:read_json(local_file(run,r['file'])) for r in index_for(run)['snapshots']}
            self.assertLess(observations['scroll-01']['scroll']['y'],observations['scroll-02']['scroll']['y'])
            self.assertTrue(any(e.get('matchedRules') for e in observations['default']['elements']))
            _,m=build(run)
            self.assertTrue(any(c['text']=='Distinct appearance' and c['styles']['fontWeight']=='700' for c in m['components']))
            self.assertTrue(any(c['kind']=='button' and 'Anchor action' in c['text'] for c in m['components']))
            m['review']['status']='reviewed';m['overview']={'tagline':'Edges','description':'Controlled source checks','status':'inferred','evidenceIds':[m['tokens'][0]['evidenceIds'][0]]}
            write_json(run/'design.json',m);export(run);self.assertEqual(verify(run)['status'],'passed')
            from exporter import _source_candidates
            child=next(e for e in observations['default']['elements'] if e['selector']=='#child')
            ev=next(e for e in m['evidence'] if e['selector']=='#child' and e['property']=='backgroundColor')
            token=next(t for t in m['tokens'] if t['category']=='color' and ev['id'] in t['evidenceIds'])
            declarations=_source_candidates(ev,child,token,observations['default'])
            self.assertFalse(any(d.get('ancestorSelector')=='#parent' for d in declarations))
            self.assertTrue(any(d.get('variableDeclarations') for d in declarations))
            self.assertEqual(capture(run,checkpoints=1,max_matched=80)['saved'],1)
            self.assertEqual(coverage(run)['snapshotCount'],1)
            row=coverage(run)['snapshots'][0]
            from capture import record_failure
            task={'url':self.source+'edges','viewport':'desktop','state':'default','configSha256':row['configSha256']}
            record_failure(run,{'stage':'browser','attemptId':'failed-attempt','tasks':[task],'message':'Controlled timeout record'})
            self.assertEqual(capture(run,checkpoints=1,max_matched=80)['saved'],1)
            self.assertFalse(coverage(run)['failures'])


if __name__=='__main__':unittest.main()
