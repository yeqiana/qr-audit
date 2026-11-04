import json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import inventory_images, analyze_contributions, render_reports, validate_evidence, build_report_models, audit_source

class InventoryTests(unittest.TestCase):
    def test_pair_missing_and_unpaired(self):
        with tempfile.TemporaryDirectory() as t:
            l=Path(t)/'g'/'WAVES_QR';r=Path(t)/'g'/'WAVES_QR_RAW';l.mkdir(parents=True);r.mkdir()
            (l/'x.png').write_bytes(b'1');(l/'y.png').write_bytes(b'2');(r/'x.png').write_bytes(b'3')
            inv=inventory_images.build_inventory(t)
            self.assertEqual(inv['groups'][0]['stats']['pair_count'],1)
            self.assertEqual(inv['groups'][0]['stats']['left_only_count'],1)
    def test_single_and_report_excluded(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t)/'x.png').write_bytes(b'1');(Path(t)/'report').mkdir()
            (Path(t)/'report'/'y.png').write_bytes(b'2')
            self.assertEqual(inventory_images.build_inventory(t)['groups'][0]['stats']['image_file_count'],1)
    def test_missing_side(self):
        with tempfile.TemporaryDirectory() as t:
            l=Path(t)/'g'/'WAVES_QR';l.mkdir(parents=True);(l/'x.png').write_bytes(b'1')
            self.assertEqual(inventory_images.build_inventory(t)['groups'][0]['stats']['missing_side_count'],1)

class ContributionTests(unittest.TestCase):
    def data(self):
        reg={'strategies':[{'strategy_id':'V01','family':'pure','tags':['pure_mode']},
                           {'strategy_id':'V02','family':'pure','tags':['pure_mode']},
                           {'strategy_id':'V03','family':'base','tags':[]}]}
        m={'mode':'contribution','strategy_order':['V01','V02','V03'],'strategies':reg['strategies'],
           'decoders':['d1'],'images':[{'image_id':'i1','group_id':'g','side_id':'L','pair_key':'x'},
                                       {'image_id':'i2','group_id':'g','side_id':'R','pair_key':'x'}]}
        a=[{'image_id':img,'strategy_id':sid,'decoder_id':'d1',
            'status':'DECODED' if img=='i1' and sid in ('V01','V02') else 'NO_DECODE',
            'payload':'ok' if img=='i1' and sid in ('V01','V02') else None,'duration_ms':1}
            for img in ('i1','i2') for sid in ('V01','V02','V03')]
        return m,a,reg
    def test_whole_family_loss_not_individual(self):
        m,a,r=self.data();res=analyze_contributions.analyze(m,a,r)
        self.assertTrue(res['contribution_metrics_valid'])
        self.assertEqual(res['strategy_metrics'][0]['exclusive_contribution'],0)
        pure=next(x for x in res['group_removal_loss'] if x['scope']=='GLOBAL' and x['strategy_group']=='pure_mode')
        self.assertEqual(pure['removal_loss'],1)
        self.assertTrue(any(x['scope']=='PAIR:x' for x in res['strategy_metrics_by_scope']))
    def test_missing_and_not_run_invalid(self):
        m,a,r=self.data();self.assertFalse(analyze_contributions.analyze(m,a[:-1],r)['contribution_metrics_valid'])
        a[0]['status']='NOT_RUN';a[0]['skip_reason']='NOT_IMPLEMENTED'
        self.assertFalse(analyze_contributions.analyze(m,a,r)['contribution_metrics_valid'])
    def test_early_stop_invalid(self):
        m,a,r=self.data();a[0]['status']='SKIPPED_EARLY_STOP';a[0]['skip_reason']='stop'
        self.assertFalse(analyze_contributions.analyze(m,a,r)['contribution_metrics_valid'])
        self.assertEqual(validate_evidence.validate(m,a,r)['status'],'FAIL')

class ReportTests(unittest.TestCase):
    def test_escape_preservation_and_files(self):
        model={'schema_version':'1.0','reports':[{'file_stem':'x','title':'<script>','status':'PARTIAL',
             'sections':[{'type':'table','title':'t','headers':['payload','status'],
                          'rows':[[{'text':'https://ex.com/?a=1|<script>alert(1)</script>','code':True},'DECODED']]}]}]}
        with tempfile.TemporaryDirectory() as t:
            file=Path(t)/'model.json';file.write_text(json.dumps(model),encoding='utf-8')
            res=render_reports.render(file,Path(t)/'output');self.assertEqual(len(res),1)
            md=(Path(t)/'output'/'x.md').read_text(encoding='utf-8')
            h=(Path(t)/'output'/'x.html').read_text(encoding='utf-8')
            self.assertIn('\\|',md);self.assertIn('` https://ex.com/',md)
            self.assertIn('&lt;script&gt;',h);self.assertNotIn('<script>alert(1)</script>',h)
            self.assertIn("default-src 'none'",h)
    def test_bad_table_fails_before_writing(self):
        m={'schema_version':'1.0','reports':[{'file_stem':'x','title':'x','sections':[
            {'type':'table','headers':['a','b'],'rows':[['onlyone']]}]}]}
        with tempfile.TemporaryDirectory() as t:
            f=Path(t)/'in.json';f.write_text(json.dumps(m),encoding='utf-8')
            with self.assertRaises(ValueError):render_reports.render(f,Path(t)/'out')
            self.assertFalse((Path(t)/'out'/'x.md').exists())
    def test_group_generates_three_reports(self):
        with tempfile.TemporaryDirectory() as t:
            l=Path(t)/'g'/'WAVES_QR';l.mkdir(parents=True);(l/'a.png').write_bytes(b'1')
            inv=inventory_images.build_inventory(t);fid=inv['groups'][0]['sides'][0]['files'][0]['file_id']
            m={'run_id':'run','strategy_order':['V01'],'images':[{'image_id':fid}]}
            a=[{'image_id':fid,'strategy_id':'V01','decoder_id':'d','status':'DECODED',
                'payload':'hello','duration_ms':1}]
            reports=build_report_models.report_model(inv,m,a)[0]['reports']
            self.assertEqual(len(reports),3)
            self.assertEqual(reports[2]['metrics'][2]['value'],1)

class AuditTests(unittest.TestCase):
    def test_readonly_hints(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t)/'x.py').write_text('cv2.QRCodeDetector()',encoding='utf-8')
            self.assertEqual(audit_source.analyze(t)['source_hints'][0]['audit_state'],'HINT_ONLY')

if __name__=='__main__': unittest.main()
