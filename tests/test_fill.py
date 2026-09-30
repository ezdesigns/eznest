import copy
import io
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from nesting import fill_stickers, validate_request, run
from engine import validate_result
from production import manifest
from output_folder import OutputFolder, FILES


def fixture():
    def part(ident,w,h,source):
        return {'id':ident,'sourceJobId':source,'perSet':1,'quantity':1,'points':[[0,0],[w,0],[w,h],[0,h]]}
    def source(ident,partid,code):
        return {'id':ident,'code':code,'name':ident,'sourceFile':ident+'.svg','revision':'hash','sets':1,'materialId':'vinyl','partIds':[partid]}
    primary=source('kit','body','A'); sticker=source('stickers','sticker','B');sticker.update(role='fill',sets=100)
    job={'materialId':'vinyl','settings':{'width':100,'maxLength':100,'margin':3,'gap':2,'seconds':1,'rotations':[0]},'parts':[part('body',50,50,'kit')],'productionJobs':[primary],
         'fillArea':'gaps','fillJobs':[{'source':sticker,'parts':[part('sticker',10,10,'stickers')],'maxSets':100}]}
    result={'width':100,'usedLength':57,'placements':[{'id':'body','x':3.1,'y':3.1,'rotation':0}], 'elapsed':0}
    return job,result


class FillTests(unittest.TestCase):
    def test_required_parts_are_unchanged_and_gaps_stay_in_original_length(self):
        job,result=fixture();before=copy.deepcopy(job);validate_request(job)
        resolved,layout=fill_stickers(job,result,budget=2)
        self.assertEqual(layout['placements'][0],result['placements'][0])
        self.assertEqual(layout['usedLength'],57)
        self.assertGreater(layout['fillSummary'][0]['pieces'],0)
        self.assertLessEqual(len(layout['placements']),100)
        self.assertEqual(job,before)
        validate_result(resolved,layout)
        detail=manifest(resolved,layout,'a'*32)
        self.assertEqual(detail['jobs'][0]['expected'],1)
        self.assertTrue(all(j['complete'] for j in detail['jobs']))

    def test_fill_only_respects_requested_size_and_maximum(self):
        job,_=fixture();job['parts']=[];job['productionJobs']=[]
        job['fillJobs'][0]['maxSets']=3;job['fillJobs'][0]['source']['sets']=3
        payload=run(job)
        self.assertEqual(len(payload['result']['placements']),3)
        self.assertEqual(payload['result']['usedLength'],100)
        self.assertEqual(payload['job']['productionJobs'][0]['sets'],3)

    def test_automatic_roll_length_keeps_stickers_in_required_job_length(self):
        job,result=fixture();job['settings']['maxLength']=None
        validate_request(job)
        resolved,layout=fill_stickers(job,result,budget=1)
        self.assertEqual(layout['width'],100)
        self.assertEqual(layout['usedLength'],57)
        self.assertGreater(layout['fillSummary'][0]['pieces'],0)
        validate_result(resolved,layout)

    def test_sticker_area_needs_explicit_length(self):
        job,_=fixture();job['settings']['maxLength']=None
        job['fillArea']='length'
        with self.assertRaisesRegex(ValueError,'Enter a roll length'):
            validate_request(job)
        job['fillArea']='gaps';job['parts']=[];job['productionJobs']=[]
        with self.assertRaisesRegex(ValueError,'Enter a roll length'):
            validate_request(job)

    def test_partial_fill_set_is_rolled_back(self):
        job,result=fixture();fill=job['fillJobs'][0]
        too_large={**fill['parts'][0],'id':'second','points':[[0,0],[90,0],[90,90],[0,90]]}
        fill['parts'].append(too_large);fill['source']['partIds'].append('second')
        validate_request(job)
        resolved,layout=fill_stickers(job,result,budget=1)
        self.assertEqual(layout['placements'],result['placements'])
        self.assertEqual(layout['fillSummary'][0]['sets'],0)
        self.assertEqual(len(resolved['productionJobs']),1)

    def test_fixed_length_fill_and_duplicate_identity_rejected(self):
        job,result=fixture();job['fillArea']='length'
        resolved,layout=fill_stickers(job,result,budget=1)
        self.assertEqual(layout['usedLength'],100)
        validate_result(resolved,layout)
        job['fillJobs'][0]['source']['code']='A'
        with self.assertRaisesRegex(ValueError,'Repeated'):validate_request(job)

    def test_invalid_lengths_and_reported_extent_rejected(self):
        job,result=fixture();result['usedLength']=10
        with self.assertRaises(ValueError):validate_result(job,result)
        job['settings']['maxLength']=float('nan')
        with self.assertRaises(ValueError):validate_request(job)


class OutputTests(unittest.TestCase):
    def package(self):
        stream=io.BytesIO()
        with ZipFile(stream,'w') as archive:
            for name in FILES:archive.writestr(name,'test '+name)
        return stream.getvalue()

    def test_save_retry_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=OutputFolder(root/'config.json');destination=root/'Output';destination.mkdir()
            out.connect(str(destination));saved=Path(out.save('a'*32,self.package()))
            self.assertEqual({p.name for p in saved.iterdir()},FILES)
            self.assertEqual(out.save('a'*32,self.package()),str(saved))
            (saved/'artwork.svg').write_text('edited')
            with self.assertRaisesRegex(ValueError,'overwritten'):out.save('a'*32,self.package())
            self.assertEqual((saved/'artwork.svg').read_text(),'edited')

    def test_no_output_inside_source_and_blank_survives_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=OutputFolder(root/'config.json');child=root/'Output';child.mkdir()
            with self.assertRaisesRegex(ValueError,'outside'):out.connect(str(child),root)
            out.connect('');self.assertIsNone(OutputFolder(root/'config.json').root)


if __name__=='__main__':unittest.main()
