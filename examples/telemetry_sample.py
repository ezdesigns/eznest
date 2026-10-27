"""Synthetic material.allocated atom through a fake hub. No network or artwork."""
import json
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import telemetry


def main():
    received = []

    def emit(atom):
        received.append(atom)
        return True  # Real receiver must durably deduplicate atom['id'] first.

    with tempfile.TemporaryDirectory(prefix='eznest-atom-sample-') as directory:
        job = {'webOptions': {'material': 'chrome'}, 'settings': {'rollWidth': 1371.6},
               'productionJobs': [{'order': 'EZ-1234'}]}
        result = {'width': 1308.1, 'usedLength': 1000, 'area': 900000,
                  'placements': [{}] * 20, 'elapsed': 90}
        ident, roll = uuid.uuid4().hex, uuid.uuid4().hex
        telemetry.observe(directory, ident, job, result)
        material = telemetry.measurements(job, result)['materialKey']
        telemetry.record_stock(directory, roll, material, 20000, uuid.uuid4().hex, 0)
        telemetry.link(directory, ident, ['EZ-1234'], roll)
        telemetry.observe(directory, ident, job, result, 'nest.committed')
        telemetry.dispatch(directory, emit, enabled=True, registered_schema=telemetry.SCHEMA)
    print(json.dumps(next(atom for atom in received if atom['type'] == 'material.allocated'), indent=2))


if __name__ == '__main__':
    main()
