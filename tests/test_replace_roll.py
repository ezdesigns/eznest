"""Replacing a roll shares stock without losing reservations or used history."""
import unittest
from playwright.sync_api import sync_playwright, expect
import material_inventory as inventory
import server
from test_material_inventory import values
import test_web_mvp as web_fixture
from test_web_mvp import launch_browser, SCREENSHOTS


class ReplaceRollTests(unittest.TestCase):
    def setUp(self):
        self.fixture = web_fixture.WebMvpTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        inventory.save(server.WORK, 'replace-test', values(), 0)

    def open_inventory(self, browser):
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        page.add_init_script("localStorage.setItem('eznest-tour-seen','1')")
        page.goto(self.fixture.url() + '/web')
        self.fixture.wait_ready(page)
        page.click('#stock-open')
        page.locator('#stock-list [data-id="replace-test"]').click()
        return page

    def test_confirm_cancel_and_shared_stock_preserve_reservations_and_history(self):
        inventory.reserve(server.WORK, 'replace-test', 'used-job', 100, 500, 'used')
        inventory.transition(server.WORK, 'used-job', 'use')
        inventory.reserve(server.WORK, 'replace-test', 'pending-job', 200, 500, 'pending')
        before = inventory.read(server.WORK)
        with sync_playwright() as p:
            browser = launch_browser(p)
            try:
                a = self.open_inventory(browser)
                b = self.open_inventory(browser)
                a.once('dialog', lambda dialog: dialog.dismiss())
                a.get_by_role('button', name='Replace roll', exact=True).click()
                self.assertEqual(inventory.read(server.WORK), before)
                a.once('dialog', lambda dialog: dialog.accept())
                a.get_by_role('button', name='Replace roll', exact=True).click()
                expect(a.locator('#stock-status')).to_contain_text('New roll loaded')
                after = inventory.read(server.WORK)
                roll = after['materials'][0]
                self.assertEqual(roll['onHandMm'], 5000)
                self.assertEqual(roll['reservedMm'], 200)
                self.assertEqual(roll['availableMm'], 4800)
                self.assertEqual(after['reservations'], before['reservations'])
                self.assertEqual(roll['revision'], before['materials'][0]['revision'] + 1)
                b.click('#stock-close')
                b.click('#stock-open')
                b.locator('#stock-list [data-id="replace-test"]').click()
                expect(b.locator('.stock-len')).to_contain_text('16.4 ft')
                a.screenshot(path=str(SCREENSHOTS/'replace-roll-desktop.png'))
                a.set_viewport_size({'width':390,'height':844})
                expect(a.get_by_role('button', name='Replace roll', exact=True)).to_be_in_viewport()
                a.screenshot(path=str(SCREENSHOTS/'replace-roll-mobile.png'))
            finally:
                browser.close()

    def test_stale_replacement_is_rejected_and_missing_full_length_opens_edit(self):
        with sync_playwright() as p:
            browser = launch_browser(p)
            try:
                page = self.open_inventory(browser)
                current = inventory.read(server.WORK)['materials'][0]
                changed = dict(current['profile'], **{'available-length':'700'})
                inventory.save(server.WORK, current['id'], changed, current['revision'])
                page.once('dialog', lambda dialog: dialog.accept())
                page.get_by_role('button', name='Replace roll', exact=True).click()
                expect(page.locator('#stock-status')).to_contain_text('changed on another screen')
                self.assertEqual(inventory.read(server.WORK)['materials'][0]['onHandMm'], 700)
                current = inventory.read(server.WORK)['materials'][0]
                inventory.save(server.WORK, current['id'], dict(current['profile'], **{'roll-length':''}), current['revision'])
                page.click('#stock-close')
                page.click('#stock-open')
                page.locator('#stock-list [data-id="replace-test"]').click()
                page.get_by_role('button', name='Replace roll', exact=True).click()
                expect(page.locator('#roll-f-full')).to_be_focused()
                expect(page.locator('#stock-status')).to_contain_text('Enter the length of a new roll')
                self.assertEqual(inventory.read(server.WORK)['materials'][0]['onHandMm'], 700)
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
