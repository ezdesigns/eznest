import base64
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from zipfile import ZipFile
from pypdf import PdfReader
import illustrator_bridge as bridge
import server
import test_web_mvp
from test_mixed_cuts import mixed_fixture
from output_folder import OutputFolder


def handoff(raw=None):
    return {'requestId': 'd' * 32, 'sourceKey': 'C:/private/customer-kit.ai',
            'content': base64.b64encode(raw or mixed_fixture()).decode(),
            'material': 'regular', 'sets': 1, 'widthIn': 51.5, 'bleedMm': 0}


class IllustratorBridgeTests(unittest.TestCase):
    def test_idempotent_intake_and_conflicting_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            data = handoff()
            a = bridge.accept(folder, data)
            self.assertEqual(a, bridge.accept(folder, data))
            self.assertEqual(bridge.read(folder, a['id'])['content'], data['content'])
            self.assertNotIn('customer-kit', (Path(folder)/'illustrator'/(a['id']+'.json')).read_text())
            with self.assertRaises(ValueError):
                bridge.accept(folder, {**data, 'sets': 2})
            (Path(folder)/'illustrator'/(a['id']+'.pdf')).write_bytes(b'%PDF-corrupted')
            with self.assertRaises(ValueError):
                bridge.read(folder, a['id'])

    def test_invalid_inputs_and_unconfigured_material(self):
        with tempfile.TemporaryDirectory() as folder:
            for change in [{'requestId':'../escape'}, {'content':'not base64!'},
                           {'sets':1.5}, {'widthIn':float('nan')}, {'material':'chrome'}]:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    bridge.accept(folder, {**handoff(), **change})

    def test_workload_identity_ignores_optimization_but_not_quantity(self):
        job = {'illustrator': {'id':'a'*32}, 'parts':[{'id':'piece','quantity':1}],
               'settings': {'width':1000, 'seed':42, 'seconds':5}, 'media':{'name':'Regular'}}
        ident = bridge.tracking_id(job, 'run1')
        job['settings'].update(seed=999, seconds=10)
        self.assertEqual(ident, bridge.tracking_id(job, 'run2'))
        job['parts'][0]['quantity'] = 2
        self.assertNotEqual(ident, bridge.tracking_id(job, 'run3'))

    def test_pdf_handoff_browser_nest_send_and_local_tracking(self):
        from playwright.sync_api import sync_playwright
        fixture = test_web_mvp.WebMvpTests()
        fixture.setUp()
        try:
            hot = server.WORK/'pilot-hot'
            hot.mkdir()
            unauthorized = Request(fixture.url()+'/api/illustrator/intake',
                                   data=json.dumps(handoff()).encode(),
                                   headers={'Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as denied:
                urlopen(unauthorized)
            self.assertEqual(denied.exception.code, 403)
            request = Request(fixture.url()+'/api/illustrator/intake',
                              data=json.dumps(handoff()).encode(),
                              headers={'Content-Type':'application/json', 'X-EZ-Token':server.TOKEN})
            result = json.load(urlopen(request))
            self.assertTrue(result['ok'])
            with patch.object(server, 'OUTPUT', OutputFolder(server.WORK/'output-folder.json')):
                with sync_playwright() as playwright:
                    browser = test_web_mvp.launch_browser(playwright)
                    try:
                        page = browser.new_page(viewport={'width':1440, 'height':1000})
                        page.goto(fixture.url()+'/web?illustrator='+result['id'])
                        fixture.wait_ready(page)
                        page.fill('#setup-hot', str(hot))
                        page.fill('#setup-printer', 'Pilot')
                        page.click('#setup-save')
                        page.wait_for_function("() => document.querySelector('#setup').hidden")
                        for run in range(2):
                            if run:
                                page.click('#start-over')
                                page.click('#illustrator-load')
                            try:
                                page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate').textContent)", timeout=30000)
                            except Exception:
                                self.fail(page.locator('#illustrator-note').inner_text() + ' / ' + page.locator('#gate').inner_text() + ' / ' + page.locator('#status').inner_text())
                            self.assertEqual(page.input_value('#auto-bleed'), '0')
                            self.assertIn('Regular', page.locator('#materials').inner_text())
                            if run == 0:
                                shots = Path(__file__).resolve().parents[1]/'.local'/'screenshots'
                                shots.mkdir(parents=True, exist_ok=True)
                                page.screenshot(path=str(shots/'illustrator-pilot.png'), full_page=True)
                            state = json.load(urlopen(fixture.url()+'/api/state'))
                            self.assertAlmostEqual(state['job']['settings']['width'], 51.5 * 25.4)
                            self.assertEqual(len(state['result']['placements']), 2)
                            page.click('#export')
                            page.click('#confirm-send')
                            page.wait_for_function("async () => (await (await fetch('/api/state')).json()).deliveryCompleted === true", timeout=30000)
                            state = json.load(urlopen(fixture.url()+'/api/state'))
                            self.assertEqual(state['job']['illustrator']['id'], result['id'])
                            # Refreshing the one-click URL must preserve the sent pack.
                            pack_id = state['id']
                            page.reload()
                            fixture.wait_ready(page)
                            self.assertIn('already open', page.locator('#illustrator-note').inner_text())
                            restored = json.load(urlopen(fixture.url()+'/api/state'))
                            self.assertEqual(restored['id'], pack_id)
                            self.assertTrue(restored['deliveryCompleted'])
                            with ZipFile(server.WORK/'batches'/(state['id']+'.zip')) as pack:
                                reader = PdfReader(io.BytesIO(pack.read('artwork.pdf')))
                                names = [o.get_object()['/Name'] for o in reader.root_object['/OCProperties']['/OCGs']]
                                self.assertEqual(set(names), {'print','thru-cut','kiss cut'})
                        summary = json.load(urlopen(fixture.url()+'/api/workload'))
                        self.assertEqual(summary['events']['sent_to_folder']['packs'], 1)
                        self.assertFalse(page.locator('#output-network').is_checked())
                    finally:
                        browser.close()
        finally:
            fixture.tearDown()

