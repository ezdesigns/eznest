import opt_out
import io
import json
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from cut_mapping import defaults
from pdf_io import read_document, import_to_store, load_documents, export_pdf
from pdf_piece_objects import analyze_objects, select_object_ids
from test_pdf_production import pdf_fixture, document_job
from test_mixed_cuts import mixed_fixture


def fixture(body, named=False):
    writer = PdfWriter(clone_from=io.BytesIO(pdf_fixture()))
    page = writer.pages[0]
    if named:
        page['/Resources']['/ColorSpace']['/Contour'][1] = NameObject('/CutContour_Thru-cut')
    stream = DecodedStreamObject(); stream.set_data(body.encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO(); writer.write(output)
    return output.getvalue()


class AutomaticPrepareTests(unittest.TestCase):
    def test_identical_strokes_removed_but_original_print_operations_retained(self):
        raw = pdf_fixture(overlap=True)
        clean, meta = read_document(raw)
        self.assertEqual(meta['preparedDuplicateCuts'], 1)
        self.assertEqual(len(meta['pieces']), 1)
        self.assertEqual(meta['pieces'][0]['cutCounts']['contour'], 1)
        self.assertEqual(sum(op == b'f' for _,op in PdfReader(io.BytesIO(clean)).pages[0].get_contents().operations), 2)

    def test_explicit_cut_resolves_identical_unspecified_copy(self):
        writer = PdfWriter(clone_from=io.BytesIO(pdf_fixture()))
        page = writer.pages[0]
        import copy
        space = copy.deepcopy(page['/Resources']['/ColorSpace']['/Contour'])
        space[1] = NameObject('/CutContour_Thru-cut')
        page['/Resources']['/ColorSpace'][NameObject('/Thru')] = space
        stream = DecodedStreamObject()
        stream.set_data(b'0 0 1 rg 18 18 84 64 re f /Contour CS 1 SCN 20 20 80 60 re S /Thru CS 1 SCN 20 20 80 60 re S')
        page[NameObject('/Contents')] = writer._add_object(stream)
        out = io.BytesIO();writer.write(out);raw = out.getvalue()
        _,meta = read_document(raw,cut_mapping=defaults())
        self.assertEqual(meta['preparedDuplicateCuts'],1)
        self.assertEqual(meta['pieces'][0]['cutPaths'][0]['sourceSpot'],'CutContour_Thru-cut')
        mapping=defaults();mapping['genericOperation']='kiss'
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            read_document(raw,cut_mapping=mapping)

    def test_custom_explicit_generic_rule_still_works(self):
        mapping=defaults()
        mapping['rules'].append({'source':'spot','match':'exact','name':'CutContour','operation':'contour'})
        self.assertEqual(len(read_document(pdf_fixture(),cut_mapping=mapping)[1]['pieces']),2)

    def test_duplicate_inner_closed_cut_removed_open_duplicate_still_rejected(self):
        raw=mixed_fixture(extra='/OC /Inner BDC q /Kiss CS 1 SCN 40 40 20 15 re S Q EMC')
        _,meta=read_document(raw,cut_mapping=defaults())
        self.assertEqual(meta['preparedDuplicateCuts'],2)
        self.assertEqual(meta['pieces'][0]['cutCounts']['kiss'],2)

    def test_source_groups_separate_overlapping_cuts_with_complete_art_and_bleed(self):
        raw=fixture('q 10 10 100 90 re W n 1 0 0 rg 0 0 180 180 re f Q '
                    'q 70 50 100 90 re W n 0 0 1 rg 0 0 180 180 re f Q '
                    '/Contour CS 1 SCN 20 20 80 70 re S 80 60 80 70 re S',named=True)
        with self.assertRaisesRegex(ValueError,'overlap'):read_document(raw)
        with tempfile.TemporaryDirectory() as folder:
            parsed=import_to_store(raw,folder,preserve=True,cut_mapping=defaults())
            self.assertEqual(len(parsed['parts']),2)
            job=document_job(parsed);docs=load_documents(job,folder)
            clean,meta=docs[parsed['documentId']]
            self.assertEqual([p['sourceObjectIds'] for p in meta['pieces']],[[0],[1]])
            self.assertTrue(all(p['bounds'][2]-p['bounds'][0]>100 for p in meta['pieces']))
            output=export_pdf(job,{'width':130,'usedLength':70,'placements':[
                {'id':job['parts'][0]['id'],'x':2,'y':2,'rotation':0},
                {'id':job['parts'][1]['id'],'x':70,'y':2,'rotation':0}]},docs,cut_mapping=defaults())
            _,nested=read_document(output,cut_mapping=defaults())
            self.assertEqual(len(nested['pieces']),2)
            self.assertEqual(sum(p['cutCounts']['thru'] for p in nested['pieces']),2)

    def test_orphan_print_is_kept_and_named_without_inventing_a_cut(self):
        raw=fixture('q 10 10 100 90 re W n 1 0 0 rg 0 0 120 120 re f Q '
                    '0 1 0 rg 200 30 20 20 re f /Contour CS 1 SCN 20 20 80 70 re S',named=True)
        with tempfile.TemporaryDirectory() as folder:
            parsed=import_to_store(raw,folder,preserve=True,cut_mapping=defaults())
            self.assertEqual(len(parsed['parts']),2)
            self.assertEqual(parsed['parts'][1]['cutCounts'],{'thru':0,'kiss':0,'contour':0})
            self.assertIn('no cuts',parsed['parts'][1]['name'])
            self.assertTrue(any('no cut lines were invented' in w for w in parsed['warnings']))

    def test_ambiguous_crossing_paint_is_not_sliced_or_silently_matched(self):
        raw=fixture('q 10 10 100 90 re W n 1 0 0 rg 0 0 180 180 re f Q '
                    'q 70 50 100 90 re W n 0 0 1 rg 0 0 180 180 re f Q '
                    '0 1 0 rg 30 40 120 60 re f '
                    '/Contour CS 1 SCN 20 20 80 70 re S 80 60 80 70 re S',named=True)
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(ValueError,'overlap'):
            import_to_store(raw,folder,preserve=True,cut_mapping=defaults())

    def test_move_close_only_paint_is_retained_with_no_invented_footprint(self):
        raw=fixture('q 10 10 100 90 re W n 1 0 0 rg 0 0 120 120 re f Q '
                    'q 250 250 m h f Q /Contour CS 1 SCN 20 20 80 70 re S',named=True)
        with tempfile.TemporaryDirectory() as folder:
            parsed=import_to_store(raw,folder,preserve=True,cut_mapping=defaults())
            meta=json.loads((Path(folder)/(parsed['documentId']+'.json')).read_text())
            self.assertEqual(meta['pieces'][0]['sourceObjectIds'],[0,1])
            self.assertLess(meta['pieces'][0]['bounds'][2],120)
