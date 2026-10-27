"""Fast checks for the nesting benchmark harness. The full job set is not run here."""
import json
import unittest
from pathlib import Path

from shapely.geometry import Polygon, box

import importlib.util

ROOT = Path(__file__).resolve().parents[1]


def load_bench():
    path = ROOT / 'tools' / 'nest_bench.py'
    spec = importlib.util.spec_from_file_location('nest_bench', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BENCH = load_bench()


class NestBenchTests(unittest.TestCase):
    def test_committed_outlines_match_the_case_table(self):
        outlines, payload = BENCH.load_outlines()
        self.assertEqual(payload['version'], 1)
        names = set()
        for case in BENCH.case_table():
            for name, quantity in case['parts']:
                names.add(name)
                self.assertGreaterEqual(quantity, 1)
                polygon = Polygon(outlines[name])
                self.assertTrue(polygon.is_valid, name)
                self.assertGreater(polygon.area, 0.01, name)
        self.assertTrue(names <= set(outlines))
        sticker = Polygon(outlines['sticker_24x18']).bounds
        self.assertAlmostEqual(sticker[2] - sticker[0], 24, places=2)
        self.assertAlmostEqual(sticker[3] - sticker[1], 18, places=2)
        panel = outlines['trail_panel']
        self.assertEqual(panel[0], [0, 0])
        self.assertIn([68, 23], panel)
        self.assertLess(Polygon(outlines['trail_badge']).bounds[3], 60)

    def test_case_table_covers_the_required_jobs(self):
        cases = {case['id']: case for case in BENCH.case_table()}
        self.assertEqual(len(cases), len(BENCH.case_table()))
        self.assertEqual(sum(qty for _, qty in cases['pieces60_quarters_seed42']['parts']), 60)
        self.assertEqual(sum(qty for _, qty in cases['pieces180_quarters_seed42']['parts']), 180)
        self.assertEqual(sum(qty for _, qty in cases['continuous_1000_quarters_seed42']['parts']), 1000)
        for case_id in (
            'pieces60_quarters_seed42', 'pieces180_quarters_seed42', 'continuous_1000_quarters_seed42',
        ):
            self.assertEqual(cases[case_id]['width'], 180)
            self.assertEqual(cases[case_id]['gap'], 3)
            self.assertEqual(cases[case_id]['margin'], 5)
        self.assertTrue(cases['continuous_1000_quarters_seed42']['continuous'])
        self.assertFalse(cases['pieces60_quarters_seed42']['continuous'])
        self.assertEqual(cases['sticker_pages_quarters_seed42']['sheetLength'], 140)
        self.assertEqual(cases['sticker_sheet_locked_seed42']['rotations'], [0])
        self.assertIsNone(cases['concave_free_seed42']['rotations'])
        self.assertEqual(cases['concave_quarters_seed42']['rotations'], [0, 90, 180, 270])
        seeds = {case['seed'] for case in cases.values()}
        self.assertTrue({'42', '7', '1', '3', '11', '99'} <= {str(seed) for seed in seeds})
        demo = {name for name, _ in cases['mixed_demo_quarters_seed42']['parts']}
        self.assertTrue({'trail_panel', 'trail_badge', 'helmet_side', 'helmet_plate', 'trail_label'} <= demo)
        odd = {name for name, _ in cases['concave_quarters_seed42']['parts']}
        self.assertTrue({'c_notch', 'arrow'} <= odd)

    def test_exact_pairs_catch_overlap_and_gap_and_accept_a_spaced_pair(self):
        left = box(0, 0, 10, 10)
        overlap = box(9, 0, 19, 10)
        report = BENCH.exact_all_pairs([left, overlap], gap=3)
        self.assertGreater(report['overlapPairs'], 0)
        spaced = box(13, 0, 23, 10)
        report = BENCH.exact_all_pairs([left, spaced], gap=3)
        self.assertEqual(report['overlapPairs'], 0)
        self.assertAlmostEqual(report['minGapMm'], 3, places=6)
        short = box(12, 0, 22, 10)
        report = BENCH.exact_all_pairs([left, short], gap=3)
        self.assertEqual(report['overlapPairs'], 1)
        self.assertAlmostEqual(report['minGapMm'], 2, places=6)
        # A far pair must not hide a later collision.
        far = box(100, 100, 110, 110)
        report = BENCH.exact_all_pairs([far, left, overlap], gap=3)
        self.assertGreater(report['overlapPairs'], 0)

    def test_validate_case_checks_margin_and_sheet_local_gap(self):
        job = {
            'parts': [{'id': 'a-1', 'points': [[0, 0], [10, 0], [10, 10], [0, 10]], 'quantity': 2}],
            'settings': {'width': 40, 'gap': 3, 'margin': 5, 'rotations': [0], 'maxLength': None, 'seconds': 1, 'seed': 1},
        }
        good = {
            'width': 40,
            'usedLength': 20,
            'placements': [
                {'id': 'a-1', 'x': 5, 'y': 5, 'rotation': 0},
                {'id': 'a-1', 'x': 18, 'y': 5, 'rotation': 0},
            ],
        }
        self.assertTrue(BENCH.validate_case(job, good)['ok'])
        tight = json.loads(json.dumps(good))
        tight['placements'][1]['x'] = 16
        self.assertFalse(BENCH.validate_case(job, tight)['ok'])
        outside = json.loads(json.dumps(good))
        outside['placements'][0]['x'] = 0
        self.assertFalse(BENCH.validate_case(job, outside)['marginOk'])

    def test_compare_flags_regressions_beyond_a_third_of_a_percent(self):
        def report(length, util, valid=True):
            case = {
                'id': 'demo', 'pieces': 2, 'pieceAreaMm2': 100, 'rollLengthMm': length,
                'utilizationPct': util, 'validationOk': valid, 'wallTimeS': 1,
                'wastedAreaMm2': 10,
            }
            return {
                'fixtureSha256': 'abc',
                'caseIds': ['demo'],
                'summary': {
                    'meanRollLengthMm': length, 'meanUtilizationPct': util,
                    'totalRollLengthMm': length, 'totalWastedAreaMm2': 10, 'totalWallTimeS': 1,
                    'valid': 1 if valid else 0, 'invalid': 0 if valid else 1, 'cases': 1,
                },
                'cases': [case],
            }
        noise = BENCH.compare_reports(report(100, 50), report(100.2, 49.9))
        self.assertEqual(noise['regressions'], [])
        self.assertEqual(noise['cases'][0]['status'], 'same')
        longer = BENCH.compare_reports(report(100, 50), report(100.4, 49.8))
        self.assertEqual(longer['regressions'], ['demo'])
        shorter = BENCH.compare_reports(report(100, 50), report(99.0, 50.5))
        self.assertEqual(shorter['improvements'], ['demo'])
        self.assertEqual(shorter['regressions'], [])
        broken = BENCH.compare_reports(report(100, 50), report(90, 55, valid=False))
        self.assertEqual(broken['regressions'], ['demo'])
        missing = BENCH.compare_reports(report(100, 50), report(100, 50))
        missing['cases'] = []
        missing['caseIds'] = []
        # A dropped case is a regression even when the survivor looks identical.
        baseline = report(100, 50)
        changed = report(100, 50)
        changed['caseIds'] = []
        changed['cases'] = []
        changed['summary'] = {**changed['summary'], 'cases': 0, 'valid': 0, 'invalid': 0,
                               'meanRollLengthMm': None, 'meanUtilizationPct': None}
        self.assertIn('demo', BENCH.compare_reports(baseline, changed)['regressions'])

    def test_one_seeded_job_is_deterministic_and_clears_validation(self):
        outlines, _payload = BENCH.load_outlines()
        case = {
            'id': 'unit-two-squares',
            'seed': 42,
            'seconds': 1,
            'width': 80,
            'gap': 2,
            'margin': 3,
            'rotations': [0, 90, 180, 270],
            'continuous': False,
            'sheetLength': None,
            'parts': [('rect_18x18', 2)],
        }
        first = BENCH.run_case(case, outlines)
        second = BENCH.run_case(case, outlines)
        self.assertTrue(first['validationOk'], first.get('engineError') or first.get('error'))
        self.assertEqual(first['overlapPairs'], 0)
        self.assertGreaterEqual(first['minGapMm'], 2 - 0.001)
        self.assertEqual(first['rollLengthMm'], second['rollLengthMm'])
        self.assertEqual(first['pieces'], 2)
        self.assertEqual(first['seed'], 42)


if __name__ == '__main__':
    unittest.main()
