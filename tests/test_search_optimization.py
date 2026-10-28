import copy
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from engine import placed_polygon, solve, validate_result
from local_search import repack
from nesting import run
from tests.test_fill import fixture


def job_for(points, quantity, gap=3):
    return {'settings': {'width':200, 'maxLength':1000, 'margin':5,
                         'gap':gap, 'seconds':5, 'rotations':[0,90,180,270]},
            'parts':[{'id':'a','points':points,'quantity':quantity}]}


class IndexedValidationTests(unittest.TestCase):
    def test_matches_all_pairs_on_concave_rotated_and_protected_shapes(self):
        rng = random.Random(8128)
        for gap in (0,.0005,1,3):
            for sample in range(12):
                job = job_for([[0,0],[2,0],[2,2],[0,2]],24,gap)
                job['parts'][0]['nestingPoints'] = [[0,0],[14,0],[14,4],[4,4],[4,14],[0,14]]
                placements = [{'id':'a','rotation':rng.choice([0,90,180,270]),
                               'x':30+(i%6)*24+rng.uniform(-7,7),
                               'y':30+(i//6)*24+rng.uniform(-7,7)} for i in range(24)]
                shapes = [placed_polygon(job['parts'][0],p) for p in placements]
                conflict = any(a.intersection(b).area > .0001 or a.distance(b)+.001 < gap
                               for i,a in enumerate(shapes) for b in shapes[:i])
                with self.subTest(gap=gap,sample=sample):
                    if conflict:
                        with self.assertRaisesRegex(ValueError,'overlap/spacing'):
                            validate_result(job,{'placements':placements})
                    else:
                        actual=validate_result(job,{'placements':placements})
                        self.assertTrue(all(a.equals(b) for a,b in zip(actual,shapes)))

    def test_threshold_pairs_are_not_excluded_by_index(self):
        square=[[0,0],[10,0],[10,10],[0,10]]
        for gap in (0,.0005,3,100):
            for offset in (-.002,0,.0005,.001,.002):
                distance=gap-offset
                job=job_for(square,2,gap)
                placements=[{'id':'a','x':5,'y':5,'rotation':0},
                            {'id':'a','x':15+distance,'y':5,'rotation':0}]
                a,b=[placed_polygon(job['parts'][0],p) for p in placements]
                invalid=a.intersection(b).area>.0001 or a.distance(b)+.001<gap
                if invalid:
                    with self.assertRaises(ValueError): validate_result(job,{'placements':placements})
                else:
                    self.assertEqual(len(validate_result(job,{'placements':placements})),2)

    def test_large_separated_layout_avoids_quadratic_narrow_phase(self):
        from shapely.geometry.base import BaseGeometry
        job=job_for([[0,0],[5,0],[5,5],[0,5]],800,1)
        placements=[{'id':'a','x':5+(i%20)*9,'y':5+(i//20)*9,'rotation':0} for i in range(800)]
        original=BaseGeometry.intersection
        calls=[]
        def counted(a,b,*args,**kwargs):
            calls.append(1)
            return original(a,b,*args,**kwargs)
        with patch.object(BaseGeometry,'intersection',counted):
            self.assertEqual(len(validate_result(job,{'placements':placements})),800)
        self.assertLess(len(calls),800)  # All-pairs would require 319,600 calls.


class LocalSearchTests(unittest.TestCase):
    def test_compacts_sparse_neighborhood_without_mutating_source(self):
        job=job_for([[0,0],[10,0],[10,10],[0,10]],8)
        job['settings']['rotations']=[0]
        result={'width':200,'usedLength':315,
                'placements':[{'id':'a','x':10+(i%4)*30,'y':100+(i//4)*200,'rotation':0} for i in range(8)]}
        before=copy.deepcopy((job,result))
        improved=repack(job,result,.8)
        self.assertLess(improved['usedLength'],result['usedLength'])
        self.assertEqual((job,result),before)
        shapes=validate_result(job,improved)
        self.assertTrue(all(p['rotation']==0 for p in improved['placements']))
        self.assertGreaterEqual(min(a.distance(b) for i,a in enumerate(shapes) for b in shapes[:i]),3)

    def test_timeout_and_impossible_complete_set_keep_incumbent(self):
        job=job_for([[0,0],[10,0],[10,10],[0,10]],1)
        result={'width':200,'usedLength':21,'placements':[{'id':'a','x':5.1,'y':5.1,'rotation':0}]}
        self.assertIs(repack(job,result,0),result)
        trial=copy.deepcopy(job)
        trial['parts'].append({'id':'extra','quantity':2,'points':[[0,0],[180,0],[180,12],[0,12]]})
        self.assertIs(repack(trial,result,.1,['extra','extra']),result)


class AdaptiveSearchTests(unittest.TestCase):
    def test_productive_attempt_receives_more_time_and_keeps_best(self):
        import spyrrow
        job=job_for([[0,0],[10,0],[10,10],[0,10]],1)
        job['settings'].update(seconds=30,rotations=[0])
        incumbent={'width':200,'usedLength':65,'placements':[{'id':'a','x':5,'y':50,'rotation':0}]}
        def native(y):
            return SimpleNamespace(placed_items=[SimpleNamespace(id='a',rotation=0,translation=(y,0))])
        with patch('engine.spyrrow.StripPackingConfig',wraps=spyrrow.StripPackingConfig) as configs, patch('engine.spyrrow.StripPackingInstance') as factory, patch('local_search.repack',side_effect=lambda j,r,b:r) as repair:
            factory.return_value.solve.side_effect=[native(30),native(20),ValueError('failed restart')]
            result=solve(job,incumbent=incumbent)
            budgets=[call.kwargs['total_computation_time'] for call in configs.call_args_list]
        self.assertEqual(budgets[0],5)
        self.assertEqual(len(budgets),3)
        repair.assert_not_called()
        self.assertLess(result['usedLength'],incumbent['usedLength'])
        validate_result(job,result)
        self.assertEqual(incumbent['usedLength'],65)

    def test_all_failed_restarts_preserve_valid_incumbent(self):
        job=job_for([[0,0],[10,0],[10,10],[0,10]],1)
        job['settings']['seconds']=1
        incumbent={'width':200,'usedLength':25,'placements':[{'id':'a','x':5,'y':10,'rotation':0}]}
        original=copy.deepcopy(incumbent)
        with patch('engine.spyrrow.StripPackingInstance') as factory:
            factory.return_value.solve.side_effect=ValueError('no fit')
            result=solve(job,incumbent=incumbent)
        # A failed native attempt must not replace the incumbent. Settling may
        # slide that same piece toward the margin; it does not change the
        # caller's object, the x position, or the rotation.
        self.assertEqual(incumbent, original)
        placed=result['placements'][0]
        self.assertEqual((placed['id'], placed['x'], placed['rotation']), ('a', 5, 0))
        self.assertLessEqual(placed['y'], 10)
        self.assertLessEqual(result['usedLength'], original['usedLength'])
        validate_result(job,result)

    def test_required_search_keeps_its_full_allocation(self):
        job,result=fixture();job['settings']['seconds']=6
        result['searchGain']=.02
        before=copy.deepcopy(job)
        with patch('nesting.solve',return_value=copy.deepcopy(result)) as native, patch('nesting.fill_stickers',side_effect=lambda j,r:(copy.deepcopy(j),r)), patch('nesting.refine_fill',side_effect=lambda j,res,r,b:(res,r)) as filler:
            payload=run(job)
        self.assertEqual([call.args[0]['settings']['seconds'] for call in native.call_args_list],[6])
        self.assertNotIn('incumbent',native.call_args_list[0].kwargs)
        filler.assert_not_called()
        self.assertNotIn('reserveStrategy',payload['result'])
        self.assertEqual(job,before)


if __name__=='__main__': unittest.main()
