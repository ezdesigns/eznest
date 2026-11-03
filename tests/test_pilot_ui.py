"""Pilot navigation, real scrolling, safe discovery and update notices."""
import opt_out
import unittest
import os
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
import test_web_mvp
import shop_deploy
import server


class PilotUiTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_web_mvp.WebMvpTests()
        self.fixture.seed_shop = False
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        env = patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS':'0', 'EZ_NEST_DEV':'0', 'EZ_NEST_OUTPUT_GATE_OPEN':'0', 'EZ_NEST_DEV_NO_OUTPUT':'0'})
        env.start(); self.addCleanup(env.stop)

    def test_skip_goes_directly_to_job_and_is_remembered(self):
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            try:
                page = browser.new_page()
                page.goto(self.fixture.url() + '/web')
                page.get_by_role('button', name='Not now', exact=True).click()
                self.fixture.wait_ready(page)
                expect(page.locator('#setup')).to_be_hidden()
                expect(page.locator('#drop')).to_be_visible()
                page.reload(); self.fixture.wait_ready(page)
                expect(page.locator('#shop-team-dialog')).to_be_hidden()
                page.click('#shop-team-open')
                page.fill('#team-shop-name', 'Test Print Shop')
                page.click('#team-create')
                expect(page.locator('#shop-team-open')).to_have_text('Test Print Shop')
                expect(page.locator('#setup')).to_be_hidden()
                ids=page.locator('.top-actions > *').evaluate_all('(nodes)=>nodes.map(n=>n.id)')
                self.assertLess(ids.index('shop-team-open'), ids.index('stock-open'))
                self.assertLess(ids.index('stock-open'), ids.index('settings-open'))
            finally: browser.close()

    def test_scroll_forms_discovery_help_and_notice(self):
        import shop_members
        shop_members.create(server.WORK, 'Test Print Shop')
        with sync_playwright() as pw:
            browser=test_web_mvp.launch_browser(pw)
            try:
                for width,height in [(1280,720),(390,600)]:
                    page=browser.new_page(viewport={'width':width,'height':height})
                    errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(self.fixture.url()+'/web'); self.fixture.wait_ready(page)
                    page.click('#stock-open'); page.click('#stock-add')
                    page.locator('#roll-f-cost').scroll_into_view_if_needed()
                    page.fill('#roll-f-cost','125')
                    self.assert_inside(page,'#roll-f-cost','#stock')
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'pilot-inventory-{width}.png'))
                    page.click('#stock-close')
                    page.click('#settings-open')
                    for selector in ['#settings-cuts','#settings-delivery','#settings-updates']:
                        page.locator(selector+' > summary').click()
                    page.locator('#test-channel').scroll_into_view_if_needed()
                    self.assert_inside(page,'#test-channel','#settings')
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'pilot-settings-{width}.png'))
                    page.click('#save-settings'); page.keyboard.press('Escape')
                    page.click('#output-required-code')
                    expect(page.locator('#output-connect-details')).to_be_hidden()
                    expect(page.locator('#output-browser-start')).to_be_hidden()
                    expect(page.locator('#output-explore')).to_have_attribute('href','https://output.jeezlabs.io/')
                    self.assertNotIn('Pilot preview',page.locator('#setup-shop').inner_text())
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'pilot-output-{width}.png'))
                    page.click('#output-link-cancel')
                    page.click('#max-output')
                    expect(page.locator('#max-output-dialog')).to_have_class('output-brand')
                    expect(page.locator('#max-output-waitlist')).to_have_attribute('href','https://output.jeezlabs.io/waitlist')
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'pilot-waitlist-{width}.png'))
                    page.keyboard.press('Escape')
                    page.click('#settings-support > summary')
                    expect(page.locator('.help-steps')).to_be_visible()
                    page.click('#help-close'); expect(page.locator('.help-card')).to_be_hidden()
                    page.evaluate("showUpdate({current:'test',latest:'2.0',updateAvailable:true,localPC:true,portableSupported:true})")
                    notice=page.locator('#shop-update-notice'); expect(notice).to_be_visible()
                    self.assertLess(notice.bounding_box()['x'],30)
                    self.assertGreater(notice.bounding_box()['y'],height/2)
                    page.click('#shop-update-action')
                    expect(page.locator('#settings-updates')).to_have_attribute('open','')
                    expect(page.locator('#update')).to_have_text('Update shop')
                    self.assertFalse(errors,errors)
                    page.close()
            finally: browser.close()

    def assert_inside(self,page,field,dialog):
        box=page.locator(field).bounding_box(); outer=page.locator(dialog).bounding_box()
        self.assertGreaterEqual(box['y'],outer['y'])
        self.assertLessEqual(box['y']+box['height'],outer['y']+outer['height'])
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),page.viewport_size['width'])
