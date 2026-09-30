import copy
import unittest
import io
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from collections import Counter
from engine import validate_result
from nesting import run
from costing import material_cost
from production import make_package


def job_fixture():
    return {'materialId':'stock','materialName':'Vinyl','settings':{'width':80,'maxLength':None,'sheetLength':70,'gap':2,'margin':3,'seconds':1,'rotations':[0,90,180,270]},
            'parts':[{'id':'a','sourceJobId':'order-a','name':'Panel','points':[[0,0],[45,0],[45,40],[0,40]],'perSet':1,'quantity':3},
                     {'id':'b','sourceJobId':'order-b','name':'Sticker','points':[[0,0],[12,0],[12,10],[0,10]],'perSet':1,'quantity':2}],
            'productionJobs':[{'id':'order-a','code':'A','name':'Kit','sets':3,'materialId':'stock','partIds':['a'],'revision':'1'},
                              {'id':'order-b','code':'B','name':'Stickers','sets':2,'materialId':'stock','partIds':['b'],'revision':'2'}]}


class SheetCostTests(unittest.TestCase):
    def test_split_keeps_every_whole_piece_within_sheet_limits(self):
        job=job_fixture();result=run(job)['result'];shapes=validate_result(job,result)
        self.assertGreater(len(result['sheets']),1)
        self.assertEqual(Counter(p['id'] for p in result['placements']),Counter(a=3,b=2))
        self.assertEqual(len(shapes),5)
        self.assertTrue(all(s['usedLength']<=70 for s in result['sheets']))
        result['placements'][0]['sheet']=99
        with self.assertRaises(ValueError):validate_result(job,result)

    def test_too_big_piece_and_total_roll_limit(self):
        job=job_fixture();job['parts'][0]['points']=[[0,0],[200,0],[200,200],[0,200]]
        with self.assertRaises(ValueError):run(job)
        job=job_fixture();job['settings']['maxLength']=75
        with self.assertRaisesRegex(ValueError,'total roll'):run(job)

    def test_material_cost_allocates_shared_waste_and_rounds_exactly(self):
        job=job_fixture();job['settings'].update(costPerSquareMeter=17.5,currency='USD')
        result=run(job)['result'];cost=material_cost(job,result,validate_result(job,result))
        self.assertAlmostEqual(sum(j['cost'] for j in cost['jobs']),cost['total'])
        self.assertAlmostEqual(cost['materialAreaM2'],80*result['usedLength']/1e6)
        self.assertGreater(cost['jobs'][0]['allocatedMaterialAreaM2'],cost['jobs'][0]['pieceAreaM2'])
        job['settings']['costPerSquareMeter']=-1
        with self.assertRaises(ValueError):material_cost(job,result,validate_result(job,result))

    def test_optional_fill_across_sheets_preserves_sets(self):
        job=job_fixture();job['parts']=job['parts'][:1];job['productionJobs']=job['productionJobs'][:1]
        fill={'id':'f','sourceJobId':'fill','name':'Fill','points':[[0,0],[4,0],[4,4],[0,4]],'perSet':2,'quantity':20}
        job['fillJobs']=[{'source':{'id':'fill','code':'B','name':'Sticker pair','sets':10,'materialId':'stock','partIds':['f'],'revision':'3','role':'fill'},'parts':[fill],'maxSets':10}]
        payload=run(job);result=payload['result']
        validate_result(payload['job'],result)
        self.assertEqual(sum(p['id']=='a' for p in result['placements']),3)
        self.assertEqual(sum(p['id']=='f' for p in result['placements'])%2,0)
        self.assertLessEqual(sum(p['id']=='f' for p in result['placements']),20)

    def test_svg_package_has_only_each_sheets_pieces_at_local_positions(self):
        job=job_fixture();result=run(job)['result']
        ns='{http://www.w3.org/2000/svg}'
        groups=''.join(f'<g id="ez-part-{i+1}" transform="translate({p["x"]} {p["y"]})"><path d="M0 0h1v1z"/></g>' for i,p in enumerate(result['placements']))
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="80mm" height="{result["usedLength"]}mm" viewBox="0 0 80 {result["usedLength"]}"><defs/>{groups}</svg>'
        package,manifest=make_package(job,result,'test',svg,svg)
        found=[]
        with ZipFile(io.BytesIO(package)) as archive:
            for sheet in result['sheets']:
                page=ET.fromstring(archive.read(f'sheet-{sheet["index"]+1:03}.svg'))
                self.assertEqual(float(page.get('height').removesuffix('mm')),sheet['usedLength'])
                holders=page.findall(ns+'g')
                self.assertEqual(len(holders),sheet['pieces'])
                for holder in holders:
                    self.assertEqual(holder.get('transform'),f'translate(0 {-sheet["offset"]})')
                    found.append(holder[0].get('id'))
        self.assertEqual(sorted(found),sorted('ez-part-'+str(i+1) for i in range(5)))


if __name__=='__main__':unittest.main()
