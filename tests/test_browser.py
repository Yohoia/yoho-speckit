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
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path=='/favicon.ico':self.send_response(204);self.end_headers();return
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(fixture)
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
            before=len(rows);self.assertEqual(capture(run,checkpoints=3)['status'],'unchanged')
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
            self.assertTrue(any('gradient(' in t['value'] for t in model['tokens'] if t['category']=='gradient'))

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


if __name__=='__main__':unittest.main()
