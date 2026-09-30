import copy
import json
import unittest
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from shop_profiles import validate_profile, inspect_output
from production import make_package
from test_production import fixture, result

CASES=json.loads((Path(__file__).parent/'shop-profile-cases.json').read_text(encoding='utf-8'))

class ShopProfileTests(unittest.TestCase):
    def test_contract_matches_browser_profile_rules(self):
        for case in CASES:
            with self.subTest(case=case['profile']['name']):
                self.assertEqual(validate_profile(case['profile']),case['clean'])
                self.assertEqual(inspect_output(case['profile']),case['check'])

    def test_untrusted_fields_and_invalid_values_cannot_claim_readiness(self):
        p={**CASES[1]['profile'],'outputPath':'private','ready':True}
        self.assertNotIn('outputPath',validate_profile(p))
        self.assertFalse(inspect_output(p)['ready'])
        for bleed in (-1,101,True,float('nan')):
            with self.assertRaises(ValueError):validate_profile({**p,'bleedMm':bleed})
        with self.assertRaises(ValueError):validate_profile({**p,'cutSpot':''})

    def test_working_pack_snapshots_requirements_without_claiming_production_output(self):
        job=fixture();job['outputProfile']=copy.deepcopy(CASES[1]['profile'])
        svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 16">'+''.join(f'<g id="ez-part-{i+1}"/>' for i in range(5))+'</svg>'
        data,detail=make_package(job,result(),'a'*32,svg,svg)
        job['outputProfile']['cutSpot']='Changed later'
        self.assertEqual(detail['outputProfile']['cutSpot'],'CutContour')
        self.assertFalse(detail['outputCheck']['ready'])
        with ZipFile(BytesIO(data)) as archive:
            self.assertIn('NOT READY FOR ONYX',archive.read('READ ME.txt').decode())
            self.assertFalse(json.loads(archive.read('batch.json'))['outputCheck']['ready'])
            self.assertIn('Working files only',archive.read('sorting-guide.html').decode())
            self.assertEqual(len(archive.namelist()),6)
            self.assertNotIn('print.pdf',archive.namelist())
