import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from playwright.sync_api import sync_playwright, expect
import material_inventory as inventory
import server
from test_material_inventory import values
import test_web_mvp as web_fixture
from test_web_mvp import launch_browser, SCREENSHOTS


class MaterialRecencyTests(unittest.TestCase):
    def test_choices_persist_without_changing_stock_or_revisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for key,name in [('a','Alpha'),('b','Bravo')]:
                inventory.save(root,key,dict(values(),**{'preset-name':name}),0)
            inventory.reserve(root,'b','pending',100,500,'fixture')
            before=inventory.read(root)
            state=inventory.touch(root,'b')
            self.assertEqual([m['id'] for m in state['materials']],['b','a'])
            self.assertEqual(state['reservations'],before['reservations'])
            for material in state['materials']:
                old=next(m for m in before['materials'] if m['id']==material['id'])
                self.assertEqual({k:v for k,v in material.items() if k!='lastUsedAt'}, {k:v for k,v in old.items() if k!='lastUsedAt'})
            self.assertEqual(inventory.read(root),state)
            self.assertEqual(inventory.touch(root,'a')['materials'][0]['id'],'a')
            with self.assertRaises(ValueError):inventory.touch(root,'missing')
            inventory.remove(root,'a',1)
            self.assertEqual(len(inventory.read(root)['materials']),1)


class MaterialRecencyBrowserTests(unittest.TestCase):
    def setUp(self):
        self.fixture=web_fixture.WebMvpTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        for key,name,roll,width in [('a','Alpha Vinyl','54','51.5'),('b','Jersey Print','20','17'),('c','Reflective Film','30','28')]:
            inventory.save(server.WORK,key,dict(values(),**{'preset-name':name,'unit':'in','roll':roll,'width':width}),0)

    def test_touch_requires_session(self):
        request=Request(self.fixture.url()+'/api/materials/touch', data=b'{"id":"b"}',
                        headers={'Content-Type':'application/json','X-EZ-Token':'invalid'})
        with self.assertRaises(HTTPError) as error:urlopen(request)
        self.assertEqual(error.exception.code,403)
        self.assertTrue(all(m['lastUsedAt'] is None for m in inventory.read(server.WORK)['materials']))

    def test_two_browsers_share_order_and_show_sizes_and_remote_removal(self):
        with sync_playwright() as p:
            browser=launch_browser(p)
            try:
                a=browser.new_page(viewport={'width':1280,'height':900});b=browser.new_page()
                cached = dict(values(), **{'preset-name': 'Old browser-only roll'})
                b.add_init_script("localStorage.setItem('eznest-placeholders', " + json.dumps(json.dumps({'materialProfiles': {'old-browser-roll': cached}})) + ")")
                for page in [a,b]:
                    page.add_init_script("localStorage.setItem('eznest-tour-seen','1')")
                    page.goto(self.fixture.url()+'/web');self.fixture.wait_ready(page)
                expect(b.locator('#material option[value="old-browser-roll"]')).to_have_count(0)
                self.assertEqual(b.evaluate("JSON.parse(localStorage.getItem('eznest-placeholders')).materialProfiles['old-browser-roll']['preset-name']"), 'Old browser-only roll')
                self.assertEqual(a.locator('#material option[data-name]').count(), 3)
                self.assertEqual(b.locator('#material option[data-name]').count(), 3)
                a.select_option('#material','b')
                expect(a.locator('#material option[data-name]').first).to_have_attribute('value','b')
                expect(b.locator('#material option[data-name]').first).to_have_attribute('value','b',timeout=15000)
                self.assertEqual(a.input_value('#material'),'b')
                self.assertEqual(b.input_value('#material'),'')
                expect(a.locator('#material option[value="b"]')).to_contain_text('20 in roll / 17 in print')
                b.click('#stock-open')
                expect(b.locator('#stock-list .stock-slot').first).to_have_attribute('data-id','b')
                expect(b.locator('#stock-list .stock-slot').first.locator('.stock-size').first).to_have_text('20 in roll')
                expect(b.locator('#stock-list .stock-slot').first.locator('.stock-print-size')).to_have_text('17 in print')
                b.screenshot(path=str(SCREENSHOTS/'inventory-recency-desktop.png'))
                b.set_viewport_size({'width':390,'height':844})
                b.screenshot(path=str(SCREENSHOTS/'inventory-recency-mobile.png'))
                for label in b.locator('.stock-size').all():
                    self.assertLessEqual(label.evaluate('(e) => e.scrollWidth'),label.evaluate('(e) => e.clientWidth'))
                b.click('#stock-close')
                inventory.remove(server.WORK,'b',1)
                expect(a.locator('#material option[value="b"]')).to_have_count(0,timeout=15000)
                self.assertEqual(a.input_value('#material'),'')
            finally:browser.close()
