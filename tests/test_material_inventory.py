import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import material_inventory as inventory
import server
import test_web_mvp
from test_web_mvp import launch_browser, SCREENSHOTS


def values(stock='1000'):
    return {'preset-name': 'Test roll', 'unit': 'mm', 'width': '500', 'roll': '510',
            'available-length': stock, 'roll-length': '5000', 'gap': '2', 'margin': '5',
            'mark-margin': '0', 'sheet': '1000', 'rotations': '0,90,180,270', 'auto-bleed': '0',
            'bleed': '0', 'cost': '', 'roll-cost': '', 'low-stock': '200', 'print-layout': 'sections'}


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        inventory.save(self.root, 'roll', values(), 0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reserve_use_retry_and_cancel_are_distinct(self):
        state = inventory.reserve(self.root, 'roll', 'job1', 200, 500, 'hash1')
        self.assertEqual(state['materials'][0]['onHandMm'], 1000)
        self.assertEqual(state['materials'][0]['availableMm'], 800)
        inventory.reserve(self.root, 'roll', 'job1', 200, 500, 'hash1')
        inventory.transition(self.root, 'job1', 'use')
        inventory.transition(self.root, 'job1', 'use')
        state = inventory.read(self.root)
        self.assertEqual(state['materials'][0]['onHandMm'], 800)
        self.assertEqual(state['materials'][0]['reservedMm'], 0)
        with self.assertRaises(ValueError): inventory.transition(self.root, 'job1', 'cancel')
        inventory.reserve(self.root, 'roll', 'job2', 300, 500, 'hash2')
        inventory.transition(self.root, 'job2', 'cancel')
        inventory.transition(self.root, 'job2', 'cancel')
        self.assertEqual(inventory.read(self.root)['materials'][0]['availableMm'], 800)

    def test_concurrent_requests_cannot_overbook(self):
        def reserve(i):
            try:
                inventory.reserve(self.root, 'roll', 'job'+str(i), 600, 500, str(i))
                return True
            except ValueError: return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(reserve, [1, 2])), 1)
        self.assertEqual(inventory.read(self.root)['materials'][0]['availableMm'], 400)

    def test_stale_edits_unknown_stock_and_changed_layout_fail(self):
        inventory.reserve(self.root, 'roll', 'job1', 600, 500, 'a')
        with self.assertRaises(ValueError): inventory.save(self.root, 'roll', values(), 1)
        with self.assertRaises(ValueError): inventory.save(self.root, 'roll', values('500'), 2)
        with self.assertRaises(ValueError): inventory.reserve(self.root, 'roll', 'job1', 600, 500, 'b')
        with self.assertRaises(ValueError): inventory.reserve(self.root, 'roll', 'wide', 10, 501, 'w')
        inventory.transition(self.root, 'job1', 'cancel')
        inventory.save(self.root, 'roll', values(''), 3)
        with self.assertRaises(ValueError): inventory.reserve(self.root, 'roll', 'unknown', 10, 500, 'u')
        with self.assertRaises(ValueError): inventory.save(self.root, 'bad', values('NaN'), 0)


class SharedInventoryBrowserTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_web_mvp.WebMvpTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def post(self, path, payload, token=True):
        req = Request(self.fixture.url()+path, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'X-EZ-Token': server.TOKEN if token else 'wrong'})
        with urlopen(req) as response: return json.load(response)

    def test_server_validates_session_and_current_layout(self):
        with self.assertRaises(HTTPError) as error:
            self.post('/api/materials/save', {'id':'roll','profile':values(),'revision':0}, False)
        self.assertEqual(error.exception.code, 403)
        self.post('/api/materials/save', {'id':'roll','profile':values(),'revision':0})
        with self.assertRaises(HTTPError): self.post('/api/materials/reserve', {'id':'old','length':1})
        self.assertEqual(inventory.read(server.WORK)['materials'][0]['reservedMm'], 0)

    def test_two_browsers_share_stock_and_confirm_once(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = launch_browser(pw)
            a = browser.new_context(viewport={'width':1280,'height':900}).new_page()
            b = browser.new_context(viewport={'width':390,'height':844}).new_page()
            try:
                for page in (a,b):
                    page.goto(self.fixture.url()+'/web')
                    self.fixture.wait_ready(page)
                    if page.locator('#feedback-welcome').is_visible(): page.click('#feedback-dismiss')
                a.click('#edit-material')
                a.fill('#available-length','1000')
                a.click('#save-material')
                expect(a.locator('#material-dialog')).not_to_be_visible()
                b.click('#inventory-open')
                expect(b.locator('#inventory-materials')).to_contain_text('83.33 ft')
                b.click('#inventory-close')
                # Open an edit, then let another screen change stock.
                b.click('#edit-material')
                row = inventory.read(server.WORK)['materials'][0]
                changed = dict(row['profile']); changed['available-length']='900'
                self.post('/api/materials/save', {'id':row['id'],'revision':row['revision'],'profile':changed})
                b.click('#save-material')
                expect(b.locator('#preset-error')).to_contain_text('changed on another screen')
                b.click('#cancel-material')
                a.select_option('#nesting-effort','5')
                a.set_input_files('#file',str(Path(__file__).resolve().parents[1]/'sample-artwork.svg'))
                self.fixture.start_nesting(a)
                a.wait_for_function("() => document.body.dataset.step === 'check'",timeout=90000)
                before=inventory.read(server.WORK)['materials'][0]['onHandMm']
                state=json.load(urlopen(self.fixture.url()+'/api/state'))
                a.click('#inventory-open'); a.click('#inventory-reserve')
                expect(a.locator('#inventory-status')).to_contain_text('Material reserved')
                self.assertEqual(inventory.read(server.WORK)['materials'][0]['onHandMm'],before)
                b.click('#inventory-open'); b.click('#inventory-refresh')
                expect(b.locator('#inventory-reservations')).to_contain_text('Reserved')
                b.get_by_role('button',name='Confirm material used',exact=True).click()
                expect(b.locator('#inventory-status')).to_contain_text('Material use recorded')
                self.post('/api/materials/transition',{'id':state['id'],'action':'use'})
                self.assertAlmostEqual(inventory.read(server.WORK)['materials'][0]['onHandMm'],before-state['result']['usedLength'])
                a.click('#inventory-refresh')
                expect(a.locator('#inventory-reservations')).to_contain_text('Used')
                a.locator('#inventory-dialog').screenshot(path=str(SCREENSHOTS/'shared-stock-desktop.png'))
                b.locator('#inventory-dialog').screenshot(path=str(SCREENSHOTS/'shared-stock-mobile.png'))
                self.assertTrue(b.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                b.reload(); self.fixture.wait_ready(b); b.click('#inventory-open')
                expect(b.locator('#inventory-reservations')).to_contain_text('Used')
            finally: browser.close()
