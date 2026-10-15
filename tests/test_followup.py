"""Boundary regressions for archive protection, inference, sources and normalization."""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import coverage, ingest, index_for, local_file, now, read_json, write_json
from colors import conversion_info, normalize_css
from design import init_run
from exporter import export, verify
from model import build
from storage import clean
from test_pipeline import observation, review


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.run=self.root/'run'
        init_run('https://fixture.test/',self.run,'single',None)
        plan=read_json(self.run/'plan.json');plan['viewports']=plan['viewports'][:1];write_json(self.run/'plan.json',plan)

    def tearDown(self):self.temp.cleanup()

    def model(self,obs=None):
        ingest(self.run,obs or observation(),'local-cdp','desktop')
        _,model=build(self.run);review(model);write_json(self.run/'design.json',model)
        return model

    @unittest.skipIf(os.name=='nt','symlink creation permissions require Windows verification')
    def test_clean_refuses_all_archive_symlinks_before_any_mutation(self):
        self.model();old=copy.deepcopy(index_for(self.run)['snapshots'][0])
        obs=observation();obs['capturedAt']=now();ingest(self.run,obs,'local-cdp','desktop',replace=True)
        archive=self.root/'archive';archive.mkdir();write_json(archive/'model.json',{'coverage':{'snapshots':[old]}})
        for kind in ('directory','file','dangling','cycle'):
            with self.subTest(kind=kind):
                link=self.run/'archive-link'
                target=archive if kind=='directory' else archive/'model.json' if kind=='file' else self.root/'missing' if kind=='dangling' else link
                link.symlink_to(target,target_is_directory=kind=='directory')
                try:
                    before=(self.run/'evidence/index.json').read_bytes()
                    for apply in (False,True):
                        with self.assertRaisesRegex(ValueError,'符号链接归档'):clean(self.run,apply=apply,keep_history=0)
                        self.assertEqual(before,(self.run/'evidence/index.json').read_bytes())
                        self.assertTrue(local_file(self.run,old['file']).exists())
                finally:link.unlink()

    def test_nested_archive_named_evidence_still_protects_its_references(self):
        self.model();old=copy.deepcopy(index_for(self.run)['snapshots'][0])
        obs=observation();obs['capturedAt']=now();ingest(self.run,obs,'local-cdp','desktop',replace=True)
        (self.run/'design.json').unlink()
        write_json(self.run/'archive/evidence/model.json',{'coverage':{'snapshots':[old]}})
        result=clean(self.run,apply=True,keep_history=0)
        self.assertNotIn(old['file'],[row['file'] for row in result['files']])
        self.assertTrue(local_file(self.run,old['file']).exists())

    def test_explicit_document_status_wins_over_same_url_resource_failures(self):
        obs=observation();obs['mainDocument']={'status':200};obs['health']={'failures':[{'url':obs['url'],'status':404,'type':'Fetch'}]}
        self.model(obs);export(self.run);self.assertEqual(verify(self.run)['status'],'passed')
        self.assertEqual(coverage(self.run)['snapshotCount'],1)
        obs['mainDocument']['status']=500;obs['capturedAt']=now();ingest(self.run,obs,'local-cdp','desktop',replace=True)
        self.assertEqual(coverage(self.run)['snapshotCount'],0)

    def test_inferred_tokens_require_evidence_but_allow_interpretation(self):
        model=self.model();base=copy.deepcopy(model['tokens'][0]);base.update(id='inference',name='inference',value='#123456',category='color',type='color',status='inferred',evidenceIds=[])
        model['tokens'].append(base);write_json(self.run/'design.json',model)
        with self.assertRaisesRegex(ValueError,'推断 Token'):export(self.run)
        base['evidenceIds']=['not-a-real-reference'];write_json(self.run/'design.json',model)
        with self.assertRaisesRegex(ValueError,'引用无效'):export(self.run)
        base['evidenceIds']=list(model['tokens'][0]['evidenceIds']);write_json(self.run/'design.json',model)
        export(self.run);self.assertEqual(verify(self.run)['status'],'passed')
        for status in ('proposed','unknown'):
            base.update(status=status,evidenceIds=[]);write_json(self.run/'design.json',model)
            export(self.run);self.assertEqual(verify(self.run)['status'],'passed')

    def test_spacing_shorthands_and_typography_keep_property_sources(self):
        obs=observation();el=obs['elements'][0]
        el['styles'].update(rowGap='20px',columnGap='30px')
        values={'padding':'12px 16px','gap':'20px 30px','font-family':'"Test Sans", sans-serif',
            'font-size':'16px','font-weight':'400','line-height':'24px','letter-spacing':'0px',
            'font-feature-settings':'normal','font-variation-settings':'normal','text-transform':'none'}
        el['matchedRules']=[{'selector':'#primary','values':values,'active':True,'inherited':False}]
        model=self.model(obs);export(self.run);self.assertEqual(verify(self.run)['status'],'passed')
        data=read_json(self.run/'design-tokens.json');refs={e['id']:e for e in model['evidence']}
        for prop in ('paddingTop','paddingRight','paddingBottom','paddingLeft','rowGap','columnGap'):
            token=next(t for t in model['tokens'] if t['category']=='spacing' and any(refs[r]['selector']=='#primary' and refs[r]['property']==prop for r in t['evidenceIds']))
            sources=data['spacing'][token['name']]['$extensions']['org.yoho-design-extractor']['sourceDeclarations']
            self.assertTrue(any(s['property']==('gap' if 'Gap' in prop else 'padding') for s in sources),prop)
        token=next(t for t in model['tokens'] if t['category']=='typography' and t['value']['fontWeight']=='400')
        sources=data['typography'][token['name']]['$extensions']['org.yoho-design-extractor']['sourceDeclarations']
        self.assertEqual({s['computedProperty'] for s in sources},set(token['value']))
        self.assertTrue(all(s['computedValue']==token['value'][s['computedProperty']] for s in sources))

    def test_interpreted_colors_keep_each_actual_evidence_value(self):
        obs=observation()
        obs['elements'][1]['styles']['color']='rgb(45, 67, 89)'
        for el in obs['elements']:
            el['matchedRules']=[{'selector':el['selector'],'active':True,'values':{'color':el['styles']['color']}}]
        model=self.model(obs)
        cited=[e for e in model['evidence'] if e['property']=='color']
        token=copy.deepcopy(next(t for t in model['tokens'] if t['category']=='color'))
        token.update(id='interpreted',name='interpreted',status='inferred',value='#123456',
            evidenceIds=[e['id'] for e in cited],sourceDeclarations=[{'value':'stale'}],
            renderedFonts=[{'familyName':'Stale Font'}])
        model['tokens'].append(token)
        for status in ('inferred','proposed','unknown'):
            token['status']=status
            if status!='inferred':token['evidenceIds']=[]
            write_json(self.run/'design.json',model);export(self.run)
            self.assertEqual(verify(self.run)['status'],'passed')
            for name in ('design-tokens.json','design-tokens.compact.json'):
                entry=read_json(self.run/name)['color']['interpreted']
                info=entry['$extensions']['org.yoho-design-extractor']
                self.assertEqual(entry['$value'],'#123456');self.assertEqual(info['modelValue'],'#123456')
                self.assertNotIn('computedValue',info)
                self.assertEqual(info['renderedFonts'],[])
                if status=='inferred':
                    self.assertEqual({e['value'] for e in info['evidenceValues']},{e['value'] for e in cited})
                    self.assertEqual({s['computedValue'] for s in info['sourceDeclarations']},{e['value'] for e in cited})
                    self.assertTrue(all(e['method']=='dom-computed-style' for e in info['evidenceValues']))
                else:
                    self.assertEqual(info['evidenceValues'],[]);self.assertEqual(info['sourceDeclarations'],[])

    def test_interpreted_typography_sources_use_measured_subproperties(self):
        obs=observation();el=obs['elements'][0]
        values={'font-family':el['styles']['fontFamily'],'font-size':'16px','font-weight':'400',
            'line-height':'24px','letter-spacing':'0px','font-feature-settings':'normal',
            'font-variation-settings':'normal','text-transform':'none'}
        el['matchedRules']=[{'selector':el['selector'],'values':values,'active':True}]
        model=self.model(obs)
        token=copy.deepcopy(next(t for t in model['tokens'] if t['category']=='typography' and t['value']['fontWeight']=='400'))
        measured=copy.deepcopy(token['value'])
        token.update(id='interpreted-type',name='interpreted-type',status='inferred')
        token['value'].update(fontSize='20px',lineHeight='28px',fontFamily='Georgia')
        model['tokens'].append(token);write_json(self.run/'design.json',model);export(self.run);verify(self.run)
        info=read_json(self.run/'design-tokens.json')['typography'][token['name']]['$extensions']['org.yoho-design-extractor']
        self.assertNotIn('computedValue',info)
        self.assertEqual(info['evidenceValues'][0]['value'],measured)
        sources=info['sourceDeclarations']
        self.assertEqual({s['computedProperty'] for s in sources},set(measured))
        self.assertTrue(all(s['computedValue']==measured[s['computedProperty']] for s in sources))

    def test_declaration_evidence_does_not_claim_a_computed_value(self):
        value='rgb(17, 34, 51)';obs=observation()
        obs['sourceRules']=[{'selector':'#primary','values':{'color':value}}]
        model=self.model(obs);snapshot=model['coverage']['snapshots'][0]['id']
        model['evidence'].append({'id':'declaration','snapshotId':snapshot,'method':'css-declaration',
            'sourceRuleIndex':0,'selector':'#primary','property':'color','value':value})
        model['tokens'].append({'id':'declaration','name':'declaration','label':'Declaration',
            'category':'color','type':'color','value':value,'status':'observed','evidenceIds':['declaration'],'role':''})
        write_json(self.run/'design.json',model);export(self.run);verify(self.run)
        info=read_json(self.run/'design-tokens.json')['color']['declaration']['$extensions']['org.yoho-design-extractor']
        self.assertNotIn('computedValue',info)
        self.assertEqual(info['modelValue'],value)
        self.assertEqual(info['evidenceValues'][0]['method'],'css-declaration')
        self.assertEqual(info['evidenceValues'][0]['value'],value)
        self.assertNotIn('computedValue',info['sourceDeclarations'][0])

    def test_unresolved_color_operations_do_not_claim_hex_conversion(self):
        values=['color-mix(in oklab, #ff0000, #0000ff)','light-dark(#ffffff, #000000)',
            'rgb(from #123456 r g b)','rgb(calc(10 + 20) 0 0)',
            'linear-gradient(#ffffff, color-mix(in oklab, red, blue))',
            '0 2px 4px mystery-color(#000000)']
        for value in values:
            with self.subTest(value=value):
                info=conversion_info(value);self.assertEqual(info['status'],'unsupported')
                self.assertIsNone(info['encoding']);self.assertTrue(info['unsupportedSourceColors'])
        for value in ('rgb(41, 122, 58)','oklab(60% 0.1 0.1)',
                      'linear-gradient(in oklab, red, blue)','rgba(0,0,0,.1) 0 2px 4px',
                      'linear-gradient(#ffffff 0, #000000 calc(100% - 2px))'):
            self.assertEqual(conversion_info(value)['status'],'converted',value)
        self.assertEqual(normalize_css('rgb(41, 122, 58)'),'#297a3a')

    def test_unresolved_declaration_is_exported_with_unsupported_gap(self):
        value='color-mix(in oklab, #ff0000, #0000ff)';obs=observation()
        obs['sourceRules']=[{'selector':'#primary','values':{'background-color':value}}]
        model=self.model(obs);snapshot=model['coverage']['snapshots'][0]['id']
        model['evidence'].append({'id':'mix-source','snapshotId':snapshot,'method':'css-declaration',
            'sourceRuleIndex':0,'selector':'#primary','property':'background-color','value':value})
        model['tokens'].append({'id':'mix','name':'mix','label':'Mix','category':'color','type':'color',
            'value':value,'status':'observed','evidenceIds':['mix-source'],'role':''})
        write_json(self.run/'design.json',model);export(self.run);self.assertEqual(verify(self.run)['status'],'passed')
        token=read_json(self.run/'design-tokens.json')['color']['mix']
        self.assertEqual(token['$value'],value)
        self.assertEqual(token['$extensions']['org.yoho-design-extractor']['normalization']['status'],'unsupported')
        self.assertTrue(any('mix: color encoding unsupported' in gap for gap in read_json(self.run/'evidence/coverage.json')['gaps']))


if __name__=='__main__':unittest.main()
