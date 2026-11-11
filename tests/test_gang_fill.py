"""Optional stickers retain source artwork, quantities and the main roll length."""
import opt_out
import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader
from cut_mapping import defaults
from engine import validate_result, part_polygon
from nesting import run, fill_stickers, validate_request
from pdf_io import import_to_store, load_documents, export_pdf
from production import manifest
from test_fill import fixture
from test_pdf_production import pdf_fixture, document_job


class GangFillTests(unittest.TestCase):
    def test_continuous_run_keeps_primary_layout_and_caps_each_sticker(self):
        job, baseline = fixture()
        job['settings'].update(continuous=True, sheetLength=5000)
        first = job['fillJobs'][0]
        first['source']['sets'] = first['maxSets'] = 2
        second = copy.deepcopy(first)
        second['source'].update(id='second', code='C', sets=3, partIds=['second'])
        second['parts'][0].update(id='second', sourceJobId='second')
        second['maxSets'] = 3
        job['fillJobs'].append(second)
        baseline['placements'][0]['sheet'] = 0
        baseline['sheets'] = [{'index':0,'offset':0,'usedLength':57,'pieces':1,'area':2500}]
        before = copy.deepcopy(job)
        with patch('sheets.continuous_nest', return_value=baseline):
            payload = run(job)
        result = payload['result']
        self.assertEqual(result['usedLength'], 57)
        self.assertEqual(result['fillBaseLength'], 57)
        self.assertEqual(result['placements'][0], baseline['placements'][0])
        self.assertEqual([s['sets'] for s in result['fillSummary']], [2,3])
        self.assertEqual(result['sheets'][0]['pieces'], 6)
        self.assertEqual(payload['requestJob'], before)
        self.assertEqual(job, before)
        shapes = validate_result(payload['job'], result)
        for i, shape in enumerate(shapes):
            for other in shapes[i+1:]: self.assertGreaterEqual(shape.distance(other), job['settings']['gap'])

    def test_no_fit_is_a_valid_main_job_with_every_sticker_remaining(self):
        job, result = fixture()
        part = job['fillJobs'][0]['parts'][0]
        part['points'] = [[0,0],[190,0],[190,180],[0,180]]
        validate_request(job)
        before = copy.deepcopy(result)
        resolved, filled = fill_stickers(job, result)
        self.assertEqual(filled['placements'], before['placements'])
        self.assertEqual(filled['usedLength'], before['usedLength'])
        self.assertEqual(filled['fillSummary'][0]['sets'], 0)
        self.assertEqual(len(resolved['parts']), 1)
        self.assertTrue(manifest(resolved, filled, 'a'*32)['complete'])

    def test_full_bleed_envelope_is_reserved_without_changing_source(self):
        job, result = fixture()
        sticker = job['fillJobs'][0]['parts'][0]
        sticker['nestingPoints'] = [[-5,-5],[15,-5],[15,15],[-5,15]]
        source = copy.deepcopy(sticker)
        resolved, filled = fill_stickers(job, result)
        self.assertGreater(filled['fillSummary'][0]['sets'], 0)
        shapes = validate_result(resolved, filled)
        for a, shape in enumerate(shapes):
            for other in shapes[a+1:]: self.assertGreaterEqual(shape.distance(other), 2)
        self.assertEqual(resolved['parts'][1]['points'], source['points'])
        self.assertEqual(resolved['parts'][1]['nestingPoints'], source['nestingPoints'])

    def test_sections_share_one_quantity_limit_without_growing(self):
        job, _ = fixture()
        job['parts'][0]['quantity'] = 2
        job['productionJobs'][0]['sets'] = 2
        job['settings'].update(sheetLength=60, maxLength=None)
        job['fillJobs'][0]['source']['sets'] = job['fillJobs'][0]['maxSets'] = 3
        payload = run(job)
        self.assertEqual(len(payload['result']['sheets']), 2)
        self.assertEqual(payload['result']['fillSummary'][0]['sets'], 3)
        self.assertEqual(payload['result']['usedLength'], payload['result']['fillBaseLength'])
        validate_result(payload['job'], payload['result'])

    def test_large_continuous_order_can_request_optional_stickers(self):
        job, _ = fixture()
        job['settings'].update(continuous=True, sheetLength=5000)
        job['parts'][0]['quantity'] = job['productionJobs'][0]['sets'] = 1000
        job['fillJobs'][0]['source']['sets'] = job['fillJobs'][0]['maxSets'] = 1000
        validate_request(job)
        for invalid in (0, -1, 1.5, True, 5001):
            with self.subTest(invalid=invalid):
                job['fillJobs'][0]['source']['sets'] = job['fillJobs'][0]['maxSets'] = invalid
                with self.assertRaises(ValueError): validate_request(job)


class StickerSourceTests(unittest.TestCase):
    def test_explicit_sticker_subset_exports_only_whole_selected_piece(self):
        mapping = defaults(); mapping['genericOperation'] = 'thru'
        with tempfile.TemporaryDirectory() as folder:
            parsed = import_to_store(pdf_fixture(), Path(folder), 0, cut_mapping=mapping, preserve=True)
            job = document_job(parsed)
            job['productionJobs'][0].update(role='fill', selectedPieceIds=[parsed['parts'][0]['pdfPieceId']])
            job['parts'] = job['parts'][:1]
            job['productionJobs'][0]['partIds'] = [job['parts'][0]['id']]
            before = copy.deepcopy(job['parts'][0])
            documents = load_documents(job, folder)
            part = job['parts'][0]; x0,y0,x1,y1 = part_polygon(part).bounds
            result = {'width':100,'usedLength':y1-y0+4,'placements':[{'id':part['id'],'x':2-x0,'y':2-y0,'rotation':0}]}
            output = export_pdf(job, result, documents)
            reader = PdfReader(io.BytesIO(output))
            self.assertEqual(len(reader.pages), 1)
            self.assertEqual(reader.pages[0].get_contents().get_data().count(b'\nS\n'), 1)
            self.assertEqual(part['points'], before['points'])
            for change in ('required', 'missing', 'geometry', 'duplicate'):
                broken = copy.deepcopy(job)
                if change == 'required': broken['productionJobs'][0]['role'] = 'required'
                if change == 'missing': broken['productionJobs'][0]['selectedPieceIds'] = ['missing']
                if change == 'geometry': broken['parts'][0]['points'][0][0] += .1
                if change == 'duplicate': broken['parts'].append(copy.deepcopy(broken['parts'][0]))
                with self.subTest(change=change), self.assertRaises(ValueError): load_documents(broken, folder)


if __name__ == '__main__': unittest.main()
