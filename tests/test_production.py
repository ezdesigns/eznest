import opt_out
import copy
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from io import BytesIO
from production import validate_identity, manifest, make_package
from folder_queue import FolderQueue


def fixture():
    return {'materialId':'vinyl','materialName':'Vinyl','settings':{'width':100,'maxLength':200,'margin':3,'gap':2,'seconds':1,'rotations':[0]},
            'productionJobs':[{'id':'job-a','code':'A','name':'Bike','sourceFile':'Bike.svg','revision':'abc','sets':2,'materialId':'vinyl','partIds':['a-1','a-2']},
                              {'id':'job-b','code':'B','name':'Helmet','sourceFile':'Helmet.svg','revision':'def','sets':1,'materialId':'vinyl','partIds':['b-1']}],
            'parts':[{'id':'a-1','sourceJobId':'job-a','name':'Side','points':[[0,0],[10,0],[10,10],[0,10]],'perSet':1,'quantity':2},
                     {'id':'a-2','sourceJobId':'job-a','name':'Fender','points':[[0,0],[10,0],[10,10],[0,10]],'perSet':1,'quantity':2},
                     {'id':'b-1','sourceJobId':'job-b','name':'Stripe','points':[[0,0],[10,0],[10,10],[0,10]],'perSet':1,'quantity':1}]}


def result():
    return {'width':100,'usedLength':16,'placements':[{'id':ident,'x':4+index*15,'y':3,'rotation':0} for index,ident in enumerate(['a-1','b-1','a-2','a-1','a-2'])]}


class ProductionTests(unittest.TestCase):
    def test_mixed_jobs_map_back_to_complete_sets(self):
        info=manifest(fixture(),result(),'f'*32)
        self.assertEqual([p['label'] for p in info['pieces']],['A1.01','B1.01','A1.02','A2.01','A2.02'])
        self.assertEqual([j['expected'] for j in info['jobs']],[4,1])
        self.assertTrue(all(j['expected']==j['placed'] for j in info['jobs']))

    def test_missing_design_piece_is_not_a_complete_job(self):
        job=fixture();job['parts'].pop(0)
        with self.assertRaisesRegex(ValueError,'missing'):validate_identity(job)

    def test_partial_sets_and_mixed_materials_rejected(self):
        job=fixture();job['parts'][0]['quantity']=1
        with self.assertRaisesRegex(ValueError,'complete'):validate_identity(job)
        job=fixture();job['productionJobs'][1]['materialId']='paper'
        with self.assertRaisesRegex(ValueError,'same material'):validate_identity(job)

    def test_actual_missing_placement_is_rejected(self):
        placed=result();placed['placements'].pop()
        with self.assertRaisesRegex(ValueError,'number'):manifest(fixture(),placed,'a'*32)

    def test_pack_contains_matching_artwork_map_and_checklist(self):
        source='<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="16mm" viewBox="0 0 100 16">'+''.join(f'<g id="ez-part-{i+1}"/>' for i in range(5))+'</svg>'
        data,details=make_package(fixture(),result(),'a'*32,source,source)
        with ZipFile(BytesIO(data)) as archive:
            self.assertEqual(set(archive.namelist()),{'artwork.svg','sheet-map.svg','sorting-guide.html','piece-checklist.csv','batch.json','READ ME.txt'})
            saved=json.loads(archive.read('batch.json'))
            self.assertEqual(saved['totalPieces'],5)
            self.assertEqual(saved['jobs'][0]['sets'],2)
            self.assertIn('A2.02',archive.read('piece-checklist.csv').decode('utf-8-sig'))
            artwork = archive.read('artwork.svg').decode()
            self.assertIn('a' * 32, artwork)
            self.assertNotIn('barcode', artwork.casefold())
            self.assertNotIn('LNRegmark', artwork)

    def test_optional_regmarks_and_media_stay_out_of_the_default_pack(self):
        source='<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="16mm" viewBox="0 0 100 16">'+''.join(f'<g id="ez-part-{i+1}"/>' for i in range(5))+'</svg>'
        job=fixture()
        job['settings']['drawRegmarks']=True
        job['settings']['markMargin']=6
        job['media']={'name':'White gloss','printer':'Example printer','quickSet':'Example RIP quick set','hotFolderLabel':'Example RIP Input','printableWidthMm':1308.1,'rollWidthMm':1371.6,'markMarginMm':12.7}
        data,details=make_package(job,result(),'a'*32,source,source)
        self.assertEqual(details['media']['hotFolderLabel'],'Example RIP Input')
        self.assertEqual(details['media']['quickSet'],'Example RIP quick set')
        with ZipFile(BytesIO(data)) as archive:
            artwork=archive.read('artwork.svg').decode()
        self.assertIn('LNRegmark', artwork)
        self.assertNotIn('barcode', artwork.casefold())

    def test_pack_rejects_missing_artwork_and_executable_svg(self):
        source='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 16"/>'
        with self.assertRaisesRegex(ValueError,'every placed'):make_package(fixture(),result(),'a'*32,source,source)
        with self.assertRaisesRegex(ValueError,'active'):make_package(fixture(),result(),'a'*32,source.replace('/>','><script/></svg>'),source)


class FolderTests(unittest.TestCase):
    def test_waits_for_stable_file_and_detects_new_revision(self):
        now=[0.0]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ready=root/'Ready';ready.mkdir();file=ready/'bike.svg';file.write_text('<svg/>')
            queue=FolderQueue(root/'folder.json',clock=lambda:now[0]);first=queue.connect(str(ready));self.assertEqual(first['files'][0]['status'],'settling')
            now[0]=3;item=queue.scan()['files'][0];self.assertEqual(item['status'],'ready');self.assertEqual(queue.read(item['id'],item['revision']),'<svg/>')
            file.write_text('<svg>changed</svg>');self.assertEqual(queue.scan()['files'][0]['status'],'settling')
            with self.assertRaisesRegex(ValueError,'changed'):queue.read(item['id'],item['revision'])
            now[0]=6;updated=queue.scan()['files'][0];self.assertNotEqual(updated['revision'],item['revision']);self.assertEqual(updated['id'],item['id'])

    def test_folder_is_read_only_and_rejects_unknown_file_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ready=root/'Ready';ready.mkdir();file=ready/'original.svg';file.write_text('original')
            queue=FolderQueue(root/'folder.json');queue.connect(str(ready));queue.scan()
            with self.assertRaises(ValueError):queue.read('../elsewhere','x')
            queue.disconnect();self.assertEqual(file.read_text(),'original');self.assertFalse(queue.scan()['connected'])

    def test_missing_folder_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ready=root/'Ready';ready.mkdir();queue=FolderQueue(root/'folder.json');queue.connect(str(ready));ready.rmdir()
            self.assertIn('unavailable',queue.scan()['error'])


if __name__=='__main__':unittest.main()
