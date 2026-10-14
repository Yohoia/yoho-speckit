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
from model import build, validate_model, validate_value, NARRATIVE_SECTIONS
from exporter import export, verify, css_values, tokens_json, color_display
from exporter import display_value
from colors import to_hex, normalize_css, conversion_info
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
    model['sections']={key:[{'text':'Fixture contains only button/text samples; '+title+' cannot be assessed from this scope.',
        'status':'unknown','evidenceIds':[]}] for key,title in NARRATIVE_SECTIONS}
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
        self.assertEqual(json.loads(tokens_json(model))['color'][gradient['name']]['$value'],'linear-gradient(90deg, #ff0000, #0000ff)')
        types=[t for t in model['tokens'] if t['category']=='typography']
        self.assertEqual({t['value']['fontWeight'] for t in types},{'400','500'})
        for t in types:self.assertEqual(css_values(model)['--text-'+t['name']+'-line-height'],'24px')

    def test_rgb_colors_export_as_hex_and_preserve_computed_evidence(self):
        obs=observation()
        for element in obs['elements']:
            element['styles']['color']='rgb(41, 122, 58)'
            element['styleDeclarations']={'color':'#297a3a'}
        obs['sourceRules']=[{'selector':'#primary, #secondary','href':'fixture.css','context':'','values':{'color':'#297a3a'}}]
        ingest(self.run,obs,'browser','desktop')
        _,model=build(self.run);review(model);write_json(self.run/'design.json',model)
        export(self.run)
        token=next(item for item in model['tokens'] if item['category']=='color' and item['value']=='rgb(41, 122, 58)')
        exported=json.loads((self.run/'design-tokens.json').read_text(encoding='utf-8'))
        entry=exported['color'][token['name']]
        self.assertEqual(entry['$value'],'#297a3a')
        self.assertEqual(entry['$extensions']['org.yoho-design-extractor']['computedValue'],'rgb(41, 122, 58)')
        self.assertEqual(entry['$extensions']['org.yoho-design-extractor']['displayValue'],'#297a3a')
        source=entry['$extensions']['org.yoho-design-extractor']['sourceDeclarations'][0]
        self.assertEqual((source['method'],source['property'],source['value']),('css-declaration','color','#297a3a'))
        self.assertIn('#297a3a',(self.run/'DESIGN.md').read_text(encoding='utf-8'))
        self.assertIn('#297a3a',(self.run/'tokens.css').read_text(encoding='utf-8'))
        self.assertNotIn('rgb(41, 122, 58)',(self.run/'tokens.css').read_text(encoding='utf-8'))
        self.assertIn('"displayValue": "#297a3a"',(self.run/'preview.html').read_text(encoding='utf-8'))
        self.assertEqual(color_display('rgba(0, 0, 0, 0.08)'),'#00000014')

    def test_rgb_modern_syntax_alpha_and_hex_normalization(self):
        for source,expected in [('rgb(41, 122, 58)','#297a3a'),('rgb(41 122 58)','#297a3a'),
            ('rgb(100% 0% 0% / 50%)','#ff000080'),('rgba(0, 0, 0, 0)','#00000000'),
            ('#abc','#aabbcc'),('#abcd','#aabbccdd'),('hsl(120 100% 50%)','#00ff00')]:
            self.assertEqual(to_hex(source),expected)

    def test_oklab_is_a_single_hex_color_not_a_gradient_label(self):
        for source,expected in [('oklab(0.62795536 0.22486306 0.12584630)','#ff0000'),
            ('oklab(1 0 0)','#ffffff'),('oklab(0.5 0 0)','#636363'),
            ('oklch(62.795536% 0.25768331 29.233885)','#ff0000'),('color(srgb 0 1 0)','#00ff00')]:
            self.assertEqual(to_hex(source),expected)
            self.assertEqual(display_value({'category':'color','value':source}),expected)

    def test_gradient_label_and_executable_hex_stops_stay_separate(self):
        source='linear-gradient(90deg in oklab, oklab(1 0 0), rgb(41, 122, 58))'
        self.assertEqual(display_value({'category':'gradient','value':source}),'Gradient')
        self.assertEqual(normalize_css(source),'linear-gradient(90deg in oklab, #ffffff, #297a3a)')
        self.assertEqual(normalize_css('rgba(0, 0, 0, 0.5) 0px 2px 4px'),'#00000080 0px 2px 4px')
        self.assertTrue(conversion_info('oklab(.7 .5 .5)')['gamutClipped'])
        obs=observation()
        for element in obs['elements']:
            element['styles']['color']='oklab(0.5 0 0)'
            element['styles']['backgroundImage']=source
        ingest(self.run,obs,'browser','desktop')
        _,model=build(self.run);review(model);write_json(self.run/'design.json',model)
        export(self.run)
        self.assertEqual(verify(self.run)['status'],'passed')
        exported=json.loads((self.run/'design-tokens.json').read_text())
        color=next(t for t in model['tokens'] if t['category']=='color' and t['value']=='oklab(0.5 0 0)')
        gradient=next(t for t in model['tokens'] if t['category']=='gradient')
        self.assertEqual(exported['color'][color['name']]['$value'],'#636363')
        self.assertEqual(exported['color'][gradient['name']]['$value'],'linear-gradient(90deg in oklab, #ffffff, #297a3a)')
        for file in ('tokens.css','tailwind.css','DESIGN.md'):
            self.assertNotRegex((self.run/file).read_text(),r'\b(?:rgba?|lab|oklab|oklch)\(')
        self.assertIn('Gradient',(self.run/'DESIGN.md').read_text())

    def test_unreviewed_candidate_cannot_be_delivered(self):
        ingest(self.run,observation(),'browser','desktop');build(self.run)
        with self.assertRaises(ValueError):export(self.run)

    def test_unused_narrative_does_not_block_delivery(self):
        model=self.model()
        model['sections']={key:[] for key,title in NARRATIVE_SECTIONS}
        write_json(self.run/'design.json',model)
        self.assertEqual(len(export(self.run)),9)
        self.assertEqual(verify(self.run)['status'],'passed')

    def test_reference_document_structure_and_preview_exclusions(self):
        model=self.model();export(self.run)
        expected={'DESIGN.md':['Tokens — Colors','Tokens — Typography','Tokens — Spacing & Shapes',
            'Components',"Do's and Don'ts",'Surfaces','Elevation'],
            'DESIGN.compact.md':['Colors','Typography','Spacing & Layout','Components',
            "Do's and Don'ts",'Elevation','Surfaces']}
        for name in ('DESIGN.md','DESIGN.compact.md'):
            document=(self.run/name).read_text()
            self.assertEqual(re.findall(r'^## (.+)$',document,re.M),expected[name])
            self.assertNotIn('```json',document)
            self.assertNotIn('| Evidence |',document)
            self.assertIn('### Type Scale',document)
            self.assertIn('**Role:**',document)
            for heading in [title for key,title in NARRATIVE_SECTIONS]+['Coverage & Evidence','Quick Start']:
                self.assertNotRegex(document,re.compile(r'^## '+re.escape(heading)+r'$',re.M))
        html=(self.run/'preview.html').read_text()
        payload=json.loads(html.split('<script id="payload" type="application/json">',1)[1].split('</script>',1)[0])
        self.assertNotIn('sections',payload['model'])
        self.assertNotIn('evidence',payload['model'])
        for id in ('components','narrative','coverage'):
            self.assertNotIn('id="'+id+'"',html)
        self.assertEqual(verify(self.run)['status'],'passed')

    def test_all_formats_have_consistent_compact_and_extended_files(self):
        model=self.model();files=export(self.run)
        self.assertEqual(len(files),9)
        compact=json.loads((self.run/'design-tokens.compact.json').read_text())
        self.assertEqual(set(compact),{'color','font','$extensions'})
        full=json.loads((self.run/'design-tokens.json').read_text())
        self.assertIn('typography',full);self.assertIn('spacing',full)
        for name in ('tokens.compact.css','tailwind.compact.css'):
            text=(self.run/name).read_text()
            self.assertIn('--font-',text);self.assertIn('--gradient-',text)
            self.assertNotIn('--spacing-',text);self.assertNotIn('--text-',text)
        self.assertIn('--spacing-',(self.run/'tokens.css').read_text())
        self.assertEqual(verify(self.run)['status'],'passed')

    def test_preview_embeds_source_assets_for_offline_delivery(self):
        self.model();export(self.run)
        html=(self.run/'preview.html').read_text(encoding='utf-8')
        assets=Path(__file__).resolve().parent.parent/'assets'
        for mime,name in [('font/woff2','jetbrains-mono-latin.woff2'),('image/png','yohoia-avatar.png')]:
            encoded=re.search(r'data:'+re.escape(mime)+r';base64,([A-Za-z0-9+/=]+)',html)
            self.assertIsNotNone(encoded)
            self.assertEqual(base64.b64decode(encoded[1]),(assets/name).read_bytes())
        self.assertNotRegex(html,r'__PREVIEW_[A-Z_]+__')
        self.assertNotIn('__PAYLOAD__',html)
        self.assertIn((assets/'preview.js').read_text(encoding='utf-8'),html)
        self.assertNotRegex(html,r'<script[^>]+src=|<link[^>]+rel=["\']stylesheet')

    def test_layout_metrics_require_evidence_and_ranges_stay_out_of_css(self):
        model=self.model();ref=next(e['id'] for e in model['evidence'] if e['property']=='paddingLeft')
        model['layoutMetrics']={'cardPadding':{'value':'16px','status':'observed','evidenceIds':[ref]},
            'sectionGap':{'value':'96-128px','status':'inferred','evidenceIds':[ref]}}
        write_json(self.run/'design.json',model);export(self.run)
        self.assertIn('--card-padding: 16px',(self.run/'tokens.css').read_text())
        self.assertNotIn('--section-gap:',(self.run/'tokens.css').read_text())
        self.assertIn('96-128px',(self.run/'DESIGN.md').read_text())
        model['layoutMetrics']['cardPadding']['value']='24px'
        write_json(self.run/'design.json',model)
        with self.assertRaisesRegex(ValueError,'实测布局'):export(self.run)

    def test_compact_document_does_not_silently_drop_palette_items(self):
        obs=observation();sample=obs['elements'][0];obs['elements']=[]
        for i in range(15):
            el=copy.deepcopy(sample);el.update(id='e'+str(i+1),selector='#chip-'+str(i))
            el['styles']['color']='rgb('+str(i)+', 100, 150)';obs['elements'].append(el)
        ingest(self.run,obs,'browser','desktop');_,model=build(self.run)
        review(model);write_json(self.run/'design.json',model);export(self.run)
        for name in ('DESIGN.md','DESIGN.compact.md'):
            text=(self.run/name).read_text()
            for i in range(15):self.assertIn(to_hex('rgb('+str(i)+', 100, 150)'),text)

    def test_gradient_name_collision_does_not_overwrite_solid_json_token(self):
        model=self.model();solid=next(t for t in model['tokens'] if t['category']=='color')
        gradient=next(t for t in model['tokens'] if t['category']=='gradient')
        solid['name']=gradient['name']='accent'
        write_json(self.run/'design.json',model);export(self.run)
        tokens=json.loads((self.run/'design-tokens.json').read_text())['color']
        self.assertEqual(tokens['accent']['$value'],to_hex(solid['value']))
        self.assertIn('gradient(',tokens['gradient-accent']['$value'])

    def test_invalid_palette_group_cannot_silently_hide_color(self):
        model=self.model();token=next(t for t in model['tokens'] if t['category']=='color')
        token['paletteGroup']='neutral'
        write_json(self.run/'design.json',model)
        with self.assertRaisesRegex(ValueError,'颜色分组'):export(self.run)

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
