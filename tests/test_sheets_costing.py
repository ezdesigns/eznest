import opt_out
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
    def test_interlocking_parts_use_one_sheet_instead_of_separate_bounding_boxes(self):
        job={'settings':{'width':110,'maxLength':None,'sheetLength':120,'gap':2,'margin':3,'seconds':2,'rotations':[0,90,180,270],'seed':42},
             'parts':[{'id':'corner','points':[[0,0],[80,0],[80,20],[20,20],[20,80],[0,80]],'quantity':2}]}
        result=run(job)['result']
        self.assertEqual(len(result['sheets']),1)
        self.assertEqual(len(validate_result(job,result)),2)
        self.assertLessEqual(result['usedLength'],120)

    def test_split_keeps_every_whole_piece_within_sheet_limits(self):
        job=job_fixture();result=run(job)['result'];shapes=validate_result(job,result)
        self.assertGreater(len(result['sheets']),1)
        self.assertEqual(Counter(p['id'] for p in result['placements']),Counter(a=3,b=2))
        self.assertEqual(len(shapes),5)
        self.assertTrue(all(s['usedLength']<=70 for s in result['sheets']))
        result['placements'][0]['sheet']=99
        with self.assertRaises(ValueError):validate_result(job,result)

    def test_sheet_measured_to_the_piece_extent_still_validates(self):
        # Settling onto the margin makes used length equal the piece extent.
        # The fit check has to tolerate the leftover floating-point difference.
        height, width, margin = 66.99937458038329, 67.99936199188232, 16.509999999999998
        used = margin + height + margin
        job={'settings':{'width':1308.1,'maxLength':None,'sheetLength':1524,'gap':3.048,'margin':margin,'seconds':1,'rotations':[0,90,180,270]},
             'parts':[{'id':'svg-1','points':[[0,0],[width,0],[width,height],[0,height]],'quantity':1}]}
        result={'width':1308.1,'usedLength':used,'placements':[{'id':'svg-1','x':margin,'y':margin,'rotation':0,'sheet':0}],
                'sheets':[{'index':0,'offset':0,'usedLength':used,'pieces':1,'area':width*height}]}
        self.assertEqual(len(validate_result(job,result)),1)
        job['parts'][0]['points']=[[0,0],[width,0],[width,height+1],[0,height+1]]
        with self.assertRaisesRegex(ValueError,'too large'):
            validate_result(job,result)

    def test_too_big_piece_and_total_roll_limit(self):
        job=job_fixture();job['parts'][0]['points']=[[0,0],[200,0],[200,200],[0,200]]
        with self.assertRaises(ValueError):run(job)
        job=job_fixture();job['settings']['maxLength']=75
        with self.assertRaisesRegex(ValueError,'total roll'):run(job)

    def test_available_roll_can_be_longer_than_one_sheet(self):
        job=job_fixture();job['settings']['maxLength']=45720
        result=run(job)['result']
        self.assertGreater(len(result['sheets']),1)
        self.assertEqual(len(validate_result(job,result)),5)
        self.assertTrue(all(sheet['usedLength']<=70 for sheet in result['sheets']))

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
