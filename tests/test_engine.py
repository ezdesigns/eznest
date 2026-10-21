import copy
import json
import math
import unittest
from pathlib import Path
from engine import solve, validate_job, validate_result, search_envelope
from unittest.mock import patch
from types import SimpleNamespace
import tempfile
from shapely.geometry import Point, Polygon

SAMPLE=json.loads((Path(__file__).resolve().parents[1]/'sample.json').read_text())

class EngineTests(unittest.TestCase):
    def test_search_outline_contains_the_complete_guarded_artwork(self):
        circle = Point(0,0).buffer(50,quad_segs=400)
        detailed = circle.union(Polygon([[0,-4],[70,-4],[70,4],[0,4]]))
        exact = detailed.buffer(.10,join_style=2)
        envelope = search_envelope(detailed)
        self.assertTrue(envelope.covers(exact))
        self.assertLess(len(envelope.exterior.coords),len(exact.exterior.coords)/2)
        self.assertLess(envelope.area/exact.area,1.01)

    def test_multiple_starts_keep_the_shortest_valid_layout_after_failure(self):
        job=self.job();job['settings'].update(width=100,margin=3,gap=2,seconds=30)
        job['parts']=[{'id':'a','points':[[0,0],[10,0],[10,10],[0,10]]}]
        def solution(y):
            return SimpleNamespace(placed_items=[SimpleNamespace(id='a',rotation=0,translation=(y,0))])
        with patch('engine.spyrrow.StripPackingInstance') as factory:
            factory.return_value.solve.side_effect=[solution(30),solution(10),ValueError('later attempt failed')]
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'progress.json'
                result=solve(job,path)
                self.assertEqual(result['usedLength'],26)
                self.assertEqual(json.loads(path.read_text())['result']['usedLength'],26)
            self.assertEqual(result['searchAttempts'],3)
            seeds=[call.args[0].seed for call in factory.return_value.solve.call_args_list]
            self.assertEqual(len(set(seeds)),3)
            validate_result(job,result)

    def test_valid_progress_beats_a_worse_final_solution(self):
        import itertools
        import spyrrow
        job=self.job();job['settings'].update(width=100,margin=3,gap=2,seconds=1)
        job['parts']=[{'id':'a','points':[[0,0],[10,0],[10,10],[0,10]]}]
        def solution(y):
            return SimpleNamespace(placed_items=[SimpleNamespace(id='a',rotation=0,translation=(y,0))])
        with patch('engine.spyrrow.StripPackingInstance') as factory, patch('engine.spyrrow.ProgressQueue') as queue:
            factory.return_value.solve.return_value=solution(30)
            queue.return_value.drain.side_effect=itertools.chain([[(spyrrow.ReportType.ExplFeas,solution(10)),(spyrrow.ReportType.Final,SimpleNamespace(placed_items=[]))]],itertools.repeat([]))
            result=solve(job)
            self.assertEqual(result['usedLength'],26)
            validate_result(job,result)

    def job(self):
        job=copy.deepcopy(SAMPLE)
        job['settings']['seconds']=1
        return job

    def test_six_parts_preserve_area_count_and_gap(self):
        job=self.job()
        result=solve(job)
        shapes=validate_result(job,result)
        self.assertEqual(len(shapes),6)
        self.assertAlmostEqual(sum(p.area for p in shapes),12400,places=2)
        self.assertTrue(result['validated'])
        self.assertLess(result['usedLength'],300)
        self.assertGreater(result['utilization'],.3)

    def test_rotation_required_for_width(self):
        job=self.job()
        job['parts']=[{'id':'long','points':[[0,0],[80,0],[80,20],[0,20]],'quantity':2}]
        job['settings'].update(width=40,maxLength=200,gap=3,margin=3)
        result=solve(job)
        self.assertEqual(len(result['placements']),2)
        self.assertTrue(all(abs(p['rotation'])%180==90 for p in result['placements']))

    def test_automatic_length_exceeds_old_limit_without_changing_width(self):
        job=self.job()
        job['settings'].update(width=50,maxLength=None,gap=3,margin=3,rotations=[0])
        job['parts']=[{'id':'long','points':[[0,0],[30,0],[30,2900],[0,2900]],'quantity':2}]
        result=solve(job)
        self.assertEqual(result['width'],50)
        self.assertGreater(result['usedLength'],5800)
        self.assertLess(result['usedLength'],5820)
        shapes=validate_result(job,result)
        self.assertAlmostEqual(sum(p.area for p in shapes),174000)
        limited=copy.deepcopy(job);limited['settings']['maxLength']=5000
        with self.assertRaisesRegex(ValueError,'Reported material length'):
            validate_result(limited,result)
        cropped={**result,'usedLength':2900}
        with self.assertRaisesRegex(ValueError,'maximum material length'):
            validate_result(job,cropped)

    def test_automatic_length_still_rejects_parts_wider_than_roll(self):
        job=self.job();job['settings'].update(width=25,maxLength=None,rotations=[0])
        job['parts']=[{'id':'wide','points':[[0,0],[30,0],[30,50],[0,50]]}]
        with self.assertRaisesRegex(ValueError,'too large'):
            validate_job(job)

    def test_rotation_locked_rejects_oversize(self):
        job=self.job();job['settings'].update(width=40,rotations=[0])
        with self.assertRaisesRegex(ValueError,'too large'): validate_job(job)

    def test_self_intersection_rejected(self):
        job=self.job();job['parts'][0]['points']=[[0,0],[40,40],[0,40],[40,0]]
        with self.assertRaisesRegex(ValueError,'intersects'): validate_job(job)

    def test_nan_rejected(self):
        job=self.job();job['settings']['width']=math.nan
        with self.assertRaises(ValueError):validate_job(job)

    def test_overlap_and_missing_parts_rejected(self):
        job=self.job();job['parts']=[{'id':'a','quantity':2,'points':[[0,0],[10,0],[10,10],[0,10]]}]
        p={'id':'a','x':10,'y':10,'rotation':0}
        with self.assertRaisesRegex(ValueError,'overlap'):validate_result(job,{'placements':[p,p]})
        with self.assertRaisesRegex(ValueError,'number'):validate_result(job,{'placements':[p]})

    def test_no_rotation_retained(self):
        job=self.job();job['settings']['rotations']=[0]
        result=solve(job)
        self.assertTrue(all(p['rotation']==0 for p in result['placements']))

    def test_free_rotation_fits_diagonal_part(self):
        from shapely.geometry import Polygon
        from shapely.affinity import rotate
        shape=rotate(Polygon([[0,0],[80,0],[80,15],[0,15]]), 37, origin=(0,0))
        job=self.job();job['settings'].update(width=35,maxLength=150,rotations=None)
        job['parts']=[{'id':'diagonal','points':list(shape.exterior.coords),'quantity':1}]
        result=solve(job)
        self.assertTrue(result['validated'])
        self.assertEqual(len(validate_result(job,result)),1)

    def test_several_hundred_copies_pass_the_shop_cap(self):
        job=self.job()
        job['parts']=[{'id':'dot','points':[[0,0],[10,0],[10,10],[0,10]],'quantity':200}]
        job['settings'].update(width=500,maxLength=None,gap=1,margin=1,seconds=1,rotations=[0])
        width, *_ = validate_job(job)
        self.assertEqual(width,500)
        job['parts'][0]['quantity']=801
        with self.assertRaisesRegex(ValueError,'800'):
            validate_job(job)

    def test_fixed_rotation_rejects_arbitrary_angle(self):
        job=self.job();job['parts']=[{'id':'a','points':[[0,0],[10,0],[10,10],[0,10]]}]
        with self.assertRaisesRegex(ValueError,'disallowed'):
            validate_result(job,{'placements':[{'id':'a','x':30,'y':30,'rotation':37}]})

if __name__=='__main__':unittest.main()
