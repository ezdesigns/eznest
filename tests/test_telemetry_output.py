import opt_out
import copy
import json
import tempfile
import unittest
from pathlib import Path
import telemetry
import telemetry_output as output


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.atom = {'schema': telemetry.SCHEMA, 'id': 'c'*64, 'type': 'nest.created',
                     'source': 'eznest', 'instanceId': 'a'*32, 'nestId': 'b'*32,
                     'appVersion': '1.0.0-rc.5', 'occurredAt': '2026-10-28T01:02:03.123456+00:00',
                     'payload': {'materialClass': 'moto_regular', 'lengthMmBand': '[250,500)',
                                 'jobCodes': ['EZ-1234'], 'rollId': 'd'*32,
                                 'fileName': 'synthetic-customer.pdf', 'lengthMm': 257.5}}

    def test_projection_is_explicit_stable_and_excludes_local_details(self):
        projected = output.project(self.atom)
        self.assertEqual(projected, output.project(copy.deepcopy(self.atom)))
        self.assertEqual(projected['kind'], 'nest.created')
        self.assertEqual(projected['occurredAt'], '2026-10-28T01:02:03.123456Z')
        self.assertEqual(projected['bands']['lengthMmBand'], '[250,500)')
        self.assertEqual(len(projected['bands']), 12)
        raw = json.dumps(projected)
        for private in ('EZ-1234', 'rollId', 'fileName', 'synthetic-customer', '257.5'):
            self.assertNotIn(private, raw)
        changed = copy.deepcopy(self.atom);changed['id']='e'*64
        self.assertNotEqual(output.project(changed)['requestId'], projected['requestId'])

    def test_local_event_meanings_remain_local_observations(self):
        for kind in telemetry.KINDS:
            self.atom['type']=kind
            self.atom['nestId']=None if kind=='material.stock_recorded' else 'b'*32
            self.assertEqual(output.project(self.atom)['kind'],kind)

    def test_corrupt_or_private_allowed_fields_fail_without_reflection(self):
        for field in ('instanceId', 'appVersion', 'occurredAt', 'type'):
            atom=copy.deepcopy(self.atom);atom[field]='synthetic@example.test'
            with self.assertRaises(ValueError) as error:output.project(atom)
            self.assertNotIn('synthetic@example.test',str(error.exception))
        for value in (False, 123, '[1,2)', '[250,501)', 'synthetic@example.test'):
            self.atom['payload']['lengthMmBand']=value
            with self.assertRaises(ValueError):output.project(self.atom)

    def test_real_local_outbox_projects_without_upload_or_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(__file__).resolve().parents[1]
            job=json.loads((root/'sample.json').read_text())
            telemetry.observe(directory,'b'*32,job,{'width':180,'usedLength':100,'area':10000,'placements':[{}], 'elapsed':5})
            before=telemetry.pending(directory)
            result=[output.project(atom) for atom in before]
            self.assertEqual([a['kind'] for a in result],['nest.created','nest.waste'])
            self.assertEqual(telemetry.pending(directory),before)

    def test_scientific_local_bands_canonicalize_but_impossible_ranges_fail(self):
        self.assertEqual(output.band('[1e+06,1.00025e+06)','lengthMmBand'),'[1000000,1000250)')
        for value in ('[1e+99,2e+99)','[-250,0)','[1000000000250,1000000000500)'):
            with self.assertRaises(ValueError):output.band(value,'lengthMmBand')


if __name__=='__main__':unittest.main()
