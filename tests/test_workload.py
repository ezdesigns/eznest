import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import workload
import server
import json
from urllib.request import urlopen
import test_web_mvp
from output_folder import OutputFolder


class WorkloadTests(unittest.TestCase):
    def test_employee_preview_and_local_delivery_activity(self):
        from playwright.sync_api import sync_playwright
        fixture = test_web_mvp.WebMvpTests()
        fixture.setUp()
        try:
            hot = server.WORK / 'hot'
            hot.mkdir()
            with patch.object(server, 'OUTPUT', OutputFolder(server.WORK / 'output-folder.json')):
                with sync_playwright() as playwright:
                    browser = test_web_mvp.launch_browser(playwright)
                    try:
                        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                        page.goto(fixture.url() + '/web')
                        fixture.wait_ready(page)
                        page.fill('#setup-hot', str(hot))
                        page.fill('#setup-printer', 'Pilot printer')
                        page.click('#setup-save')
                        page.wait_for_function("() => document.querySelector('#setup').hidden")
                        page.set_input_files('#file', str(Path(__file__).parents[1] / 'sample-artwork.svg'))
                        page.click('#start-nesting')
                        page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate').textContent)", timeout=90000)
                        preview_box = page.locator('#sheet-frame').bounding_box()
                        controls_box = page.locator('.job-panel').bounding_box()
                        self.assertGreater(preview_box['width'], controls_box['width'] * 3)
                        self.assertLessEqual(preview_box['x'] + preview_box['width'], controls_box['x'])
                        self.assertNotRegex(page.locator('body').inner_text(), r'[Ââ]')
                        page.select_option('#preview-zoom', '2')
                        self.assertGreater(page.locator('#preview').bounding_box()['width'],
                                           page.locator('#sheet-frame').bounding_box()['width'] * 1.8)
                        for _ in range(2):
                            page.click('#export')
                            page.click('#confirm-send')
                            page.wait_for_function("() => document.querySelector('#confirm').hidden")
                        summary = json.load(urlopen(fixture.url() + '/api/workload'))
                        self.assertEqual(summary['events']['sent_to_folder']['packs'], 1)
                        self.assertEqual(summary['events']['sent_to_folder']['pieces'], 4)
                        page.locator('#settings').evaluate('node => node.open = true')
                        page.locator('#local-activity').evaluate('node => node.open = true')
                        page.wait_for_function("() => document.querySelector('#activity-summary').textContent.includes('1 sent')")
                        self.assertGreater(page.locator('#local-activity summary').bounding_box()['width'], 200)
                        self.assertFalse(page.locator('#output-network').is_checked())
                    finally:
                        browser.close()
        finally:
            fixture.tearDown()

    def test_deduplicated_events_survive_reopen_without_private_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            result = {'width': 1000, 'usedLength': 2000, 'area': 1500000,
                      'placements': [{'id': 'private-art-name'}, {'id': 'other'}],
                      'filename': 'Customer secret.pdf'}
            for _ in range(2):
                workload.record(directory, 'opaque-pack', 'prepared', result)
                workload.record(directory, 'opaque-pack', 'sent_to_folder', result)
            summary = workload.summary(directory)
            self.assertEqual(summary['events']['sent_to_folder'],
                             {'packs': 1, 'pieces': 2, 'lengthMm': 2000, 'materialM2': 2})
            self.assertNotIn(b'Customer secret', (Path(directory) / 'workload.sqlite3').read_bytes())
            self.assertNotIn(b'private-art-name', (Path(directory) / 'workload.sqlite3').read_bytes())
            workload.record(directory, 'opaque-pack', 'removed_from_folder', result)
            self.assertEqual(workload.summary(directory)['events']['removed_from_folder']['packs'], 1)

    def test_prepared_is_not_a_delivery_and_old_records_expire(self):
        with tempfile.TemporaryDirectory() as directory:
            workload.record(directory, 'old', 'prepared', {})
            db = workload.connect(directory)
            with db:
                db.execute("UPDATE events SET occurred_at='2000-01-01T00:00:00+00:00'")
            db.close()
            workload.record(directory, 'new', 'prepared', {})
            totals = workload.summary(directory)['events']
            self.assertNotIn('sent_to_folder', totals)
            self.assertEqual(totals['prepared']['packs'], 1)
            db = workload.connect(directory)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)
            db.close()

    def test_disk_error_does_not_fail_delivery(self):
        before = dict(server.STATE)
        try:
            server.STATE.update(id='pack', result={}, deliveryCompleted=True)
            with patch.object(workload, 'record', side_effect=sqlite3.OperationalError('disk full')):
                server.record_workload('sent_to_folder')
            self.assertTrue(server.STATE['deliveryCompleted'])
            self.assertIn('trackingWarning', server.STATE)
        finally:
            server.STATE.clear()
            server.STATE.update(before)

    def test_nonfinite_measurement_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                workload.record(directory, 'pack', 'prepared', {'width': float('nan')})
