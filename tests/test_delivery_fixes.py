"""Resource boundaries, scroll coverage, and offline preview regression tests."""
import copy
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from capture import capture,doctor
from common import coverage,ingest,index_for,local_file,read_json,write_json
from design import init_run
from exporter import export,verify
from model import build
from test_pipeline import observation,review

UNSAFE = [
    'linear-gradient(red,blue), image-set("http://127.0.0.1:1/pixel" 1x)',
    r'linear-gradient(red,blue), \69mage-set("http://127.0.0.1:1/pixel" 1x)',
    r'linear-gradient(red,blue), u\72l(http://127.0.0.1:1/pixel)',
    r'linear-gradient(red,blue), \000075rl(http://127.0.0.1:1/pixel)',
    'linear-gradient(red,blue), -webkit-image-set("http://127.0.0.1:1/pixel" 1x)',
    'linear-gradient(red,blue), image("http://127.0.0.1:1/pixel")',
]


def single_run(source,run):
    init_run(source,run,'single',None)
    plan=read_json(run/'plan.json');plan['viewports']=plan['viewports'][:1];write_json(run/'plan.json',plan)


class ValueBoundaryTests(unittest.TestCase):
    def test_resource_declarations_and_proposals_cannot_be_exported(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'run';single_run('https://fixture.test/',run)
            obs=observation();obs['sourceRules']=[{'selector':':root','values':{'--source':v}} for v in UNSAFE]
            ingest(run,obs,'local-cdp','desktop');_,model=build(run);review(model)
            snapshot=model['coverage']['snapshots'][0]['id']
            for i,value in enumerate(UNSAFE):
                for status in ('observed','proposed'):
                    with self.subTest(value=value,status=status):
                        current=copy.deepcopy(model)
                        current['evidence'].append({'id':'unsafe','snapshotId':snapshot,'method':'css-declaration',
                            'sourceRuleIndex':i,'selector':':root','property':'--source','value':value})
                        current['tokens'].append({'id':'unsafe','name':'unsafe','label':'Unsafe','category':'gradient',
                            'type':'gradient','value':value,'status':status,'evidenceIds':['unsafe'] if status=='observed' else []})
                        write_json(run/'design.json',current)
                        with self.assertRaisesRegex(ValueError,'无外部资源'):export(run)
            row=index_for(run)['snapshots'][0]
            self.assertEqual(read_json(local_file(run,row['file']))['sourceRules'],obs['sourceRules'])

    def test_margin_values_keep_evidence_and_nonscale_values_stay_out(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'run';single_run('https://fixture.test/',run);obs=observation()
            obs['elements'][0]['styles'].update(marginTop='53px',marginLeft='67px',marginRight='auto',marginBottom='-7px')
            obs['elements'][1]['styles'].update(marginTop='0px')
            ingest(run,obs,'local-cdp','desktop');_,model=build(run);review(model);write_json(run/'design.json',model)
            export(run);verify(run);refs={e['id']:e for e in model['evidence']}
            for value,prop in [('53px','marginTop'),('67px','marginLeft'),('-7px','marginBottom')]:
                token=next(t for t in model['tokens'] if t['category']=='spacing' and t['value']==value)
                self.assertTrue(any(refs[e]['property']==prop for e in token['evidenceIds']))
                self.assertIn(value,(run/'tokens.css').read_text())
            self.assertFalse(any(t['value'] in {'0px','auto'} for t in model['tokens'] if t['category']=='spacing'))


CONTAINER = '''<!doctype html><title>Internal scroll</title><style>
html,body{margin:0;height:100%;overflow:hidden}main{height:100%;overflow:auto}
#space{height:5000px}#start{margin:53px 0 0 67px}
#lazy{color:#ad2959;font:700 37px/43px Georgia;padding:47px}
</style><main id="scroller"><p id="start">Container top</p><div id="space"></div></main>
<script>scroller.addEventListener('scroll',()=>{if(scroller.scrollTop>1000&&!document.getElementById('lazy')){
const b=document.createElement('button');b.id='lazy';b.textContent='Lazy action';scroller.append(b)}})</script>'''


class DeliveryBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not doctor()['ready']:raise unittest.SkipTest('Node 22+ and Chrome/Chromium required')
        cls.pixel_requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path=='/pixel':
                    cls.pixel_requests.append(self.path);self.send_response(204);self.end_headers();return
                body=CONTAINER
                if self.path=='/body':
                    body=body.replace('main{height:100%;overflow:auto}','body{overflow:auto}')
                    body=body.replace('<main id="scroller">','<body id="scroller">').replace('</main>','')
                if self.path=='/long':body=body.replace('height:5000px','height:100000px')
                if self.path=='/many':
                    body='<!doctype html><title>Many scrollers</title><style>body{margin:0;display:grid;grid-template-columns:repeat(3,1fr)}section{height:150px;overflow:auto}p{height:2400px;margin:0}</style>'+''.join('<section id="s'+str(i)+'"><p>Scrollable content</p></section>' for i in range(6))
                if self.path=='/horizontal':body='<!doctype html><title>Horizontal</title><div style="overflow:auto;width:300px"><p style="width:2500px">Wide content</p></div>'
                self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body.encode())
            def log_message(self,*args):pass
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.source='http://127.0.0.1:'+str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,'server'):cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def test_container_lazy_content_and_margins_reach_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in ('container','body'):
                with self.subTest(path=path):
                    run=Path(directory)/path;single_run(self.source+'/'+path,run)
                    self.assertEqual(capture(run)['status'],'captured')
                    rows={r['state']:read_json(local_file(run,r['file'])) for r in coverage(run)['snapshots']}
                    last=rows['scroll-02'];self.assertTrue(last['walkComplete'])
                    self.assertEqual(last['scroll']['y'],0)
                    self.assertGreater(next(t['y'] for t in last['scrollWalk']['targets'] if t['selector']=='#scroller'),1000)
                    self.assertTrue(any(e['selector']=='#lazy' for e in last['elements']))
                    self.assertLessEqual(last['scrollWalk']['stepsUsed'],24)
                    _,model=build(run);review(model);write_json(run/'design.json',model);export(run);verify(run)
                    self.assertTrue(any(t['category']=='color' and t['value']=='rgb(173, 41, 89)' for t in model['tokens']))
                    for value in ('53px','67px'):
                        self.assertIn(value,(run/'DESIGN.md').read_text());self.assertIn(value,(run/'tokens.css').read_text())
                        self.assertTrue(any(t['$value']==value for t in read_json(run/'design-tokens.json')['spacing'].values()))

    def test_container_and_step_limits_never_claim_complete_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in ('many','long','horizontal'):
                with self.subTest(path=path):
                    run=Path(directory)/path;single_run(self.source+'/'+path,run)
                    self.assertEqual(capture(run,max_matched=0)['status'],'captured')
                    cov=coverage(run);last=next(read_json(local_file(run,r['file'])) for r in cov['snapshots'] if r['state']=='scroll-02')
                    self.assertFalse(last['walkComplete']);self.assertLessEqual(last['scrollWalk']['stepsUsed'],24)
                    self.assertLessEqual(len(last['scrollWalk']['targets']),5)
                    self.assertTrue(any('scroll' in g for g in cov['gaps']))
                    if path=='many':self.assertGreaterEqual(last['scrollWalk']['omittedContainers'],2)
                    if path=='long':self.assertEqual(last['scrollWalk']['stepsUsed'],24)
                    if path=='horizontal':self.assertGreater(last['scrollWalk']['horizontalRegions'],0)

    def test_offline_preview_theme_controls_keyboard_download_and_resource_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'run';single_run('https://fixture.test/',run)
            ingest(run,observation(),'local-cdp','desktop');_,model=build(run);review(model)
            write_json(run/'design.json',model);export(run);verify(run)
            before=len(self.pixel_requests)
            request={'preview':str(run/'preview.html'),'downloads':str(Path(directory)/'downloads'),
                'pixel':self.source+'/pixel','unsafe':UNSAFE}
            write_json(Path(directory)/'request.json',request)
            proc=subprocess.run(['node',str(Path(__file__).with_name('check_preview.mjs')),str(Path(directory)/'request.json')],capture_output=True,text=True,timeout=40)
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            result=json.loads(proc.stdout);self.assertEqual(result['variants'],8)
            self.assertEqual(result['downloads'],8);self.assertEqual(result['keyboardCopies'],2)
            self.assertEqual(len(self.pixel_requests),before)


if __name__=='__main__':unittest.main()
