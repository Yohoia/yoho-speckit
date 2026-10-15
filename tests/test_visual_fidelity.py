"""Capture-to-delivery regressions for gradient semantics, scroll origins and focus rings."""
import json
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import zlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from capture import capture,doctor
from colors import conversion_info,normalize_css
from common import coverage,digest,ingest,local_file,read_json,write_json
from exporter import export,verify
from model import build
from test_pipeline import review
from test_delivery_fixes import single_run

GRADIENTS=[
    'linear-gradient(90deg, oklab(0.62795536 0.22486306 0.1258463), oklab(0.45201372 -0.03245698 -0.31152815))',
    'linear-gradient(oklab(.6 .1 .1), oklab(.7 -.05 -.05))',
    'radial-gradient(circle at 30% 40%, oklab(.6 .1 .1), oklab(.7 -.05 -.05))',
    'conic-gradient(from 30deg at 40% 50%, oklab(.6 .1 .1), oklab(.7 -.05 -.05))',
    'repeating-linear-gradient(90deg, oklab(.6 .1 .1) 0 25px, oklab(.7 -.05 -.05) 50px)',
    'linear-gradient(90deg in oklch longer hue, red, blue)',
    'linear-gradient(90deg, color(srgb .2 .4 .6 / .3), color(srgb .6 .3 .2 / .8))',
    'linear-gradient(90deg in oklab, oklab(60% none none), oklab(60% .2 .1))',
    'linear-gradient(90deg in srgb, rgb(none 0 0), rgb(255 0 0))',
    'linear-gradient(90deg, red, blue)',
]


def png_pixels(path):
    """Decode Chrome's 8-bit RGB/RGBA PNG using only the test suite's standard library."""
    data=Path(path).read_bytes();assert data[:8]==b'\x89PNG\r\n\x1a\n'
    offset=8;compressed=b''
    while offset<len(data):
        size=struct.unpack('>I',data[offset:offset+4])[0];kind=data[offset+4:offset+8];body=data[offset+8:offset+8+size];offset+=size+12
        if kind==b'IHDR':width,height,depth,color,_,_,interlace=struct.unpack('>IIBBBBB',body)
        if kind==b'IDAT':compressed+=body
    assert depth==8 and color in {2,6} and interlace==0
    channels=3 if color==2 else 4;stride=width*channels;raw=zlib.decompress(compressed);rows=[];prior=bytearray(stride)
    for y in range(height):
        start=y*(stride+1);mode=raw[start];row=bytearray(raw[start+1:start+1+stride]);assert 0<=mode<=4
        for x in range(stride):
            a=row[x-channels] if x>=channels else 0;b=prior[x];c=prior[x-channels] if x>=channels else 0
            p=a+b-c;distances=[abs(p-a),abs(p-b),abs(p-c)]
            predictor=(a,b,c)[distances.index(min(distances))]
            row[x]=(row[x]+(0,a,b,(a+b)//2,predictor)[mode])&255
        rows.append(row);prior=row
    return lambda x,y:tuple(rows[y][x*channels:x*channels+3])


def restored_page(container=False,middle=False,blocked=False,jump=False,navigate=False):
    layout='html,body{height:100%;margin:0;overflow:hidden}main{height:100%;overflow:auto}' if container else 'body{margin:0}'
    target='scroller' if container else 'document.scrollingElement'
    event='scroller' if container else 'window'
    hook="target.scrollTo=()=>location.replace('/error');" if navigate else 'target.scrollTo=()=>{};' if blocked else ''
    scroll="if(target.scrollTop>100&&target.scrollTop<target.scrollHeight-target.clientHeight-2)target.scrollTop=target.scrollHeight;" if jump else ''
    initial='0' if jump else 'target.scrollHeight*.5' if middle else 'target.scrollHeight'
    return f'''<!doctype html><title>Restored view</title><style>{layout}#space{{height:6500px}}#top-action{{color:#247a35}}</style>
<main id="scroller"><div id="slot"></div><div id="space"></div><p>Bottom</p></main><script>
const target={target};function render(){{{scroll}slot.innerHTML=target.scrollTop<100?'<button id="top-action">Virtual top</button>':''}}
{event}.addEventListener('scroll',render);addEventListener('load',()=>{{target.scrollTop={initial};render();{hook}}});
</script>'''


class FidelityBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not doctor()['ready']:raise unittest.SkipTest('Node 22+ and Chrome/Chromium required')
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path=='/error':self.send_response(404);self.end_headers();self.wfile.write(b'Error');return
                if self.path=='/gradients':
                    body='<!doctype html><title>Gradients</title><style>div{width:256px;height:100px}</style>'+''.join('<div id="g'+str(i)+'" style="background-image:'+value+'"></div>' for i,value in enumerate(GRADIENTS))
                elif self.path=='/focus':
                    body='''<!doctype html><title>Focus</title><style>button{background:white;color:black;border:0;font:16px Arial;padding:20px;outline:none}#action:focus{outline:5px solid #a51be7;outline-offset:7px}#hidden-outline{outline-color:#e7951b;outline-style:none}#zero{outline:0 solid #19c79a}#transparent{outline:5px solid rgba(123,45,67,0)}</style><button id="action">Focus action</button><button id="hidden-outline">No outline</button><button id="zero">Zero outline</button><button id="transparent">Transparent outline</button>'''
                else:
                    body=restored_page(container='container' in self.path,middle='middle' in self.path,blocked='blocked' in self.path,jump='jump' in self.path,navigate='navigate' in self.path)
                self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body.encode())
            def log_message(self,*args):pass
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.source='http://127.0.0.1:'+str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,'server'):cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def test_captured_gradients_preserve_actual_rendering_in_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/'run';single_run(self.source+'/gradients',run)
            self.assertEqual(capture(run,checkpoints=1)['status'],'captured')
            _,model=build(run);review(model);write_json(run/'design.json',model);export(run);verify(run)
            refs={e['id']:e for e in model['evidence']};exported=read_json(run/'design-tokens.json');pairs=[]
            for i in range(len(GRADIENTS)):
                token=next(t for t in model['tokens'] if t['category']=='gradient' and any(refs[r]['selector']=='#g'+str(i) for r in t['evidenceIds']))
                entry=exported['color'][token['name']];info=entry['$extensions']['org.yoho-design-extractor']['normalization']
                pairs.append({'original':token['value'],'exported':entry['$value']})
                if 'none' in token['value']:
                    self.assertEqual(entry['$value'],token['value']);self.assertEqual(info['status'],'unsupported')
                    self.assertTrue(any(token['id'] in gap for gap in read_json(run/'evidence/coverage.json')['gaps']))
                else:
                    self.assertEqual(info['status'],'converted');self.assertFalse(info['gamutClipped'])
                for name in ('tokens.css','tailwind.css'):
                    self.assertIn(entry['$value'],(run/name).read_text())
            request={'pairs':pairs,'screenshot':str(root/'paired.png')};write_json(root/'request.json',request)
            proc=subprocess.run(['node',str(Path(__file__).with_name('check_gradients.mjs')),str(root/'request.json')],capture_output=True,text=True,timeout=30)
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr);pixel=png_pixels(root/'paired.png')
            for i,pair in enumerate(pairs):
                for x in (32,128,224):
                    for y in (20,50,80):
                        a,b=pixel(x,i*100+y),pixel(x+256,i*100+y)
                        self.assertLessEqual(max(abs(u-v) for u,v in zip(a,b)),4,(i,pair,a,b))

    def test_restored_window_and_containers_start_at_top_and_keep_virtual_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in ('document-bottom','document-middle','container-bottom','container-middle'):
                with self.subTest(path=path):
                    run=Path(directory)/path;single_run(self.source+'/'+path,run);self.assertEqual(capture(run)['status'],'captured')
                    rows={r['state']:read_json(local_file(run,r['file'])) for r in coverage(run)['snapshots']}
                    self.assertTrue(all(t['y']<=2 and t['startedAtTop'] for t in rows['default']['scrollWalk']['targets']))
                    self.assertTrue(any(e['selector']=='#top-action' for e in rows['default']['elements']))
                    last=rows['scroll-02'];self.assertTrue(last['walkComplete']);self.assertLessEqual(last['scrollWalk']['stepsUsed'],24)
                    self.assertTrue(all(t['rangeComplete'] for t in last['scrollWalk']['targets']))
                    _,model=build(run);review(model);write_json(run/'design.json',model);export(run);verify(run)
                    self.assertIn('#247a35',(run/'tokens.css').read_text())

    def test_blocked_resets_and_discontinuous_jumps_do_not_claim_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in ('document-blocked','container-blocked','document-jump','container-jump'):
                with self.subTest(path=path):
                    run=Path(directory)/path;single_run(self.source+'/'+path,run);self.assertEqual(capture(run,max_matched=0)['status'],'captured')
                    cov=coverage(run);last=next(read_json(local_file(run,r['file'])) for r in cov['snapshots'] if r['state']=='scroll-02')
                    self.assertFalse(last['walkComplete']);self.assertLessEqual(last['scrollWalk']['stepsUsed'],24)
                    phrase='start not observed' if 'blocked' in path else 'unvisited range'
                    self.assertTrue(any(phrase in gap for gap in cov['gaps']),cov['gaps'])

    def test_navigation_during_reset_rejects_error_document(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'run';single_run(self.source+'/document-navigate',run)
            result=capture(run);self.assertEqual(result['status'],'partial');self.assertEqual(result['saved'],0)
            self.assertEqual(coverage(run)['snapshotCount'],0)
            self.assertTrue(any('404' in failure['message'] for failure in result['failures']))

    def test_visible_focus_outline_reaches_tokens_sources_and_component_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'run';single_run(self.source+'/focus',run)
            capture(run,checkpoints=1);capture(run,state='focus',selector='#action',checkpoints=1)
            _,model=build(run);review(model);write_json(run/'design.json',model);export(run);verify(run)
            token=next(t for t in model['tokens'] if t['category']=='color' and t['value']=='rgb(165, 27, 231)')
            refs={e['id']:e for e in model['evidence']};self.assertTrue(all(refs[r]['property']=='outlineColor' for r in token['evidenceIds']))
            entry=read_json(run/'design-tokens.json')['color'][token['name']]
            self.assertEqual(entry['$value'],'#a51be7')
            self.assertTrue(any(s['property'] in {'outline-color','outline'} for s in entry['$extensions']['org.yoho-design-extractor']['sourceDeclarations']))
            self.assertFalse(any(t['category']=='color' and t['value'] in {'rgb(231, 149, 27)','rgb(25, 199, 154)','rgba(123, 45, 67, 0)'} for t in model['tokens']))
            for name in ('DESIGN.md','DESIGN.compact.md'):
                text=(run/name).read_text();self.assertIn('Outline 5px solid #a51be7',text);self.assertIn('Outline offset 7px',text)
            for name in ('tokens.css','tailwind.css','preview.html'):self.assertIn('#a51be7',(run/name).read_text())

    def test_previous_collector_snapshots_are_refreshed_and_new_ones_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'run';single_run(self.source+'/focus',run);capture(run,checkpoints=1)
            row=coverage(run)['snapshots'][0];old=read_json(local_file(run,row['file']));old['captureConfig']['collectorVersion']=5
            ingest(run,old,'local-cdp','desktop',requested_url=self.source+'/focus',replace=True)
            result=capture(run,checkpoints=1);self.assertEqual(result['saved'],1)
            current=coverage(run)['snapshots'][0];self.assertNotEqual(current['configSha256'],digest(old['captureConfig']))
            self.assertEqual(current['configSha256'],row['configSha256'])
            self.assertEqual(read_json(local_file(run,current['file']))['captureConfig']['collectorVersion'],6)
            self.assertEqual(capture(run,checkpoints=1)['status'],'unchanged')


class GradientFallbackTests(unittest.TestCase):
    def test_unknown_geometry_and_missing_components_remain_executable_originals(self):
        for value in ('linear-gradient(calc(90deg), oklab(.6 .1 .1), oklab(.7 -.1 -.1))',
                'radial-gradient(calc(30px) at center, oklab(.6 .1 .1), oklab(.7 -.1 -.1))',
                'linear-gradient(oklab(.6 none none), oklab(.7 .1 .1)), linear-gradient(red, blue)'):
            self.assertEqual(normalize_css(value),value);self.assertEqual(conversion_info(value)['status'],'unsupported')


if __name__=='__main__':unittest.main()
