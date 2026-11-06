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

    def test_welcome_then_local_trial_is_remembered(self):
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            try:
                page = browser.new_page()
                page.goto(self.fixture.url() + '/web')
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS/'welcome-output-intro.png'))
                page.get_by_role('button', name='Close welcome', exact=True).click()
                page.get_by_role('button', name='Use this PC for now', exact=True).click()
                self.fixture.wait_ready(page)
                expect(page.locator('#setup')).to_be_hidden()
                expect(page.locator('#drop')).to_be_visible()
                page.reload(); self.fixture.wait_ready(page)
                expect(page.locator('#shop-team-dialog')).to_be_hidden()
                page.click('#shop-team-open')
                page.get_by_role('button', name='Create a shop', exact=True).click()
                page.fill('#team-shop-name', 'Test Print Shop')
                page.click('#team-create')
                # Creation writes the shop, then refreshes the session before
                # dismissing the dialog. Wait for that action to finish.
                expect(page.locator('#shop-team-dialog')).to_be_hidden(timeout=15000)
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
                    expect(page.get_by_label('Default print folder',exact=True)).to_be_visible()
                    expect(page.locator('#settings-delivery')).to_be_hidden()
                    expect(page.locator('#settings-telemetry')).to_be_hidden()
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'settings-essential-{width}.png'))
                    page.locator('#settings-cuts > summary').click()
                    expect(page.locator('#custom-cut-names')).to_be_hidden()
                    before=page.input_value('#thru-name')
                    page.select_option('#cut-preset','custom')
                    expect(page.locator('#custom-cut-names')).to_be_visible()
                    self.assertEqual(page.input_value('#thru-name'),before)
                    page.select_option('#cut-preset','output')
                    expect(page.locator('#custom-cut-names')).to_be_hidden()
                    page.locator('#settings-cuts > summary').click()
                    page.locator('#settings-backup > summary').click()
                    checkbox=page.locator('#staging-on').bounding_box()
                    caption=page.locator('#staging-on + .setting-heading').bounding_box()
                    self.assertEqual(checkbox['height'],16)
                    self.assertLess(abs(checkbox['y']+8-caption['y']-caption['height']/2),3)
                    self.assertEqual(page.locator('#settings-cuts').evaluate('n=>getComputedStyle(n).borderTopWidth'),'1px')
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'pilot-settings-top-{width}.png'))
                    for selector in ['#settings-cuts','#settings-updates','#settings-preview']:
                        page.locator(selector+' > summary').click()
                    page.locator('#test-channel').scroll_into_view_if_needed()
                    self.assert_inside(page,'#test-channel','#settings')
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'pilot-settings-{width}.png'))
                    page.click('#save-settings'); page.keyboard.press('Escape')
                    page.click('#max-output')
                    expect(page.locator('#max-output-dialog')).to_have_class('output-brand')
                    expect(page.locator('#max-output-title')).to_contain_text('Let a partner print.')
                    self.assertNotIn('THANKS FOR USING',page.locator('#max-output-dialog').inner_text())
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

    def test_output_dialog_enter_never_runs_underlying_production_action(self):
        import shop_members
        shop_members.create(server.WORK, 'Keyboard test shop')
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            try:
                page = browser.new_page()
                page.goto(self.fixture.url() + '/web'); self.fixture.wait_ready(page)
                page.evaluate("() => { window.productionCalls = 0; exportFile = openConfirm = () => { window.productionCalls++; }; }")
                for step in ['check', 'confirm']:
                    page.click('#settings-open'); page.click('#output-settings-open')
                    page.evaluate('(step) => { document.body.dataset.step = step; current = {result: {}}; }', step)
                    page.locator('#output-settings-back').press('Enter')
                    expect(page.locator('#settings')).to_be_visible()
                    self.assertEqual(page.evaluate('window.productionCalls'), 0)
                    page.click('#settings-close')
            finally:
                browser.close()

    def test_welcome_and_local_trial_restore_saved_job_without_output(self):
        from pathlib import Path
        import material_inventory
        from test_material_inventory import values
        hot = server.WORK / 'synthetic-hot-folder'; hot.mkdir()
        server.OUTPUT.connect(str(hot))
        material_inventory.save(server.WORK, 'shared-roll', values(), 0)
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            try:
                context = browser.new_context()
                context.add_init_script("localStorage.setItem('eznest-shop-welcome-dismissed', '1')")
                page = context.new_page()
                page.goto(self.fixture.url() + '/web'); self.fixture.wait_ready(page)
                page.set_input_files('#file', str(Path(__file__).parents[1] / 'sample-artwork.svg'))
                page.click('#start-nesting')
                page.wait_for_function("() => document.body.dataset.step === 'check'", timeout=90000)
                context.close()
                fresh = browser.new_context()
                page = fresh.new_page()
                page.goto(self.fixture.url() + '/web')
                page.click('#tour-next')
                page.get_by_role('button', name='Use this PC for now', exact=True).click()
                self.fixture.wait_ready(page)
                self.assertEqual(page.get_attribute('body', 'data-step'), 'check')
                self.assertEqual(page.input_value('#hot-folder'), str(hot.resolve()))
                self.assertEqual(page.evaluate('kits.length'), 1)
                self.assertIn('shared-roll', page.evaluate('shopInventory.materials.map(item => item.id)'))
                expect(page.locator('#output-required')).to_be_hidden()
                self.assertEqual(list(hot.iterdir()), [])
            finally:
                browser.close()

    def assert_inside(self,page,field,dialog):
        box=page.locator(field).bounding_box(); outer=page.locator(dialog).bounding_box()
        self.assertGreaterEqual(box['y'],outer['y'])
        self.assertLessEqual(box['y']+box['height'],outer['y']+outer['height'])
        self.assertGreaterEqual(box['y'],0)
        self.assertLessEqual(box['y']+box['height'],page.viewport_size['height'])
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),page.viewport_size['width'])

    def test_home_has_no_output_banner_and_settings_labels(self):
        import shop_members
        shop_members.create(server.WORK, 'EZ Designs')
        with sync_playwright() as pw:
            browser=test_web_mvp.launch_browser(pw)
            try:
                page=browser.new_page(viewport={'width':1280,'height':800})
                page.goto(self.fixture.url()+'/web');self.fixture.wait_ready(page)
                expect(page.locator('#shop-team-open svg')).to_be_visible()
                self.assertEqual(page.locator('#shop-team-open').evaluate('n=>getComputedStyle(n).borderRightWidth'),'0px')
                expect(page.locator('#output-required')).to_be_hidden()
                expect(page.locator('#output-promo-dismissed')).to_be_hidden()
                page.click('#settings-open')
                expect(page.locator('#browse-output')).to_have_text('Choose folder')
                page.locator('#settings-backup > summary').click()
                expect(page.get_by_role('button',name='About Keep an extra copy',exact=True)).to_be_visible()
                page.locator('#settings-cuts > summary').click()
                page.select_option('#cut-preset','ln')
                expect(page.locator('#thru-name')).to_have_value('LNThru-cut')
                expect(page.locator('#kiss-name')).to_have_value('LNKiss-cut')
                expect(page.locator('#cut-line-names')).to_have_text('LNThru-cut, LNKiss-cut')
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS/'settings-simple-folder-cuts.png'))
                page.keyboard.press('Escape')
                page.reload();self.fixture.wait_ready(page)
                expect(page.locator('#output-required')).to_be_hidden()
                expect(page.locator('#output-promo-dismissed')).to_be_hidden()
            finally:browser.close()

    def test_shop_closes_with_x_escape_and_outside_but_not_inside_drag(self):
        import shop_members
        shop_members.create(server.WORK, 'Test shop')
        with sync_playwright() as pw:
            browser=test_web_mvp.launch_browser(pw)
            try:
                page=browser.new_page(viewport={'width':1280,'height':800})
                page.goto(self.fixture.url()+'/web');self.fixture.wait_ready(page)
                for action in ['close','escape','outside']:
                    page.click('#shop-team-open')
                    expect(page.locator('#shop-team-dialog')).to_be_visible()
                    expect(page.get_by_role('button',name='Done',exact=True)).to_have_count(0)
                    if action=='close':page.click('#shop-team-close')
                    elif action=='escape':page.keyboard.press('Escape')
                    else:page.mouse.click(5,5)
                    expect(page.locator('#shop-team-dialog')).to_be_hidden()
                page.click('#shop-team-open');page.locator('#shop-team-title').click()
                expect(page.locator('#shop-team-dialog')).to_be_visible()
                box=page.locator('#shop-team-title').bounding_box()
                page.mouse.move(box['x']+5,box['y']+5);page.mouse.down();page.mouse.move(5,5);page.mouse.up()
                expect(page.locator('#shop-team-dialog')).to_be_visible()
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS/'shop-close-control.png'))
            finally:browser.close()

    def test_settings_every_control_reachable_without_overlap(self):
        import shop_members
        shop_members.create(server.WORK, 'Test shop')
        with sync_playwright() as pw:
            browser=test_web_mvp.launch_browser(pw)
            try:
                for width,height in [(1280,720),(390,600),(320,480),(844,390)]:
                    page=browser.new_page(viewport={'width':width,'height':height})
                    page.goto(self.fixture.url()+'/web');self.fixture.wait_ready(page)
                    page.click('#settings-open')
                    page.locator('#settings .settings-section').evaluate_all('(nodes)=>nodes.forEach(n=>{if(n.tagName==="DETAILS"&&!n.hidden)n.open=true})')
                    page.locator('#settings-backup').evaluate('n=>n.open=true')
                    page.locator('#settings-preview').evaluate('n=>n.open=true')
                    page.select_option('#cut-preset','custom')
                    for selector in ['#hot-folder','#browse-output','#staging-on','#thru-name','#kiss-name','#updates','#test-channel','#save-settings']:
                        control=page.locator(selector);control.scroll_into_view_if_needed()
                        self.assert_inside(page,selector,'#settings')
                        self.assertTrue(control.evaluate('n=>{const r=n.getBoundingClientRect();const top=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return n===top||n.contains(top)}'),selector)
                        if selector in ['#thru-name','#kiss-name','#output-url']:
                            bounds=control.bounding_box();outer=page.locator('#settings').bounding_box()
                            self.assertGreaterEqual(bounds['x'],outer['x'])
                            self.assertLessEqual(bounds['x']+bounds['width'],outer['x']+outer['width'])
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'settings-accessible-{width}-{height}.png'))
                    page.click('#save-settings')
                    page.click('#output-settings-open')
                    expect(page.locator('#telemetry-enable')).to_be_hidden()
                    expect(page.locator('#telemetry-agree')).to_be_hidden()
                    expect(page.locator('#telemetry-stop')).to_be_hidden()
                    page.locator('.privacy-details').evaluate('n=>n.open=true')
                    page.locator('#output-url').scroll_into_view_if_needed()
                    self.assert_inside(page,'#output-url','#output-settings')
                    page.click('#output-settings-back')
                    expect(page.locator('#settings')).to_be_visible()
                    page.close()
            finally:browser.close()

    def test_real_wheel_and_keyboard_scroll_and_balanced_empty_inventory(self):
        import shop_members
        shop_members.create(server.WORK,'Scroll test shop')
        with sync_playwright() as pw:
            browser=test_web_mvp.launch_browser(pw)
            try:
                for width,height in [(1280,720),(800,600),(390,600)]:
                    page=browser.new_page(viewport={'width':width,'height':height})
                    page.goto(self.fixture.url()+'/web');self.fixture.wait_ready(page)
                    page.click('#stock-open')
                    measure=page.locator('#stock').evaluate('n=>{const c=n.querySelector(".panel"),r=n.getBoundingClientRect(),p=c.getBoundingClientRect();return {left:p.left-r.left,right:r.right-p.right,gutter:getComputedStyle(n).scrollbarGutter}}')
                    self.assertEqual(measure['gutter'],'auto')
                    self.assertLessEqual(abs(measure['left']-measure['right']),2)
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'inventory-balanced-{width}.png'))
                    page.click('#stock-close');page.click('#settings-open')
                    expect(page.locator('#settings-title')).to_be_focused()
                    page.locator('#settings-cuts > summary').click()
                    page.locator('#settings-backup > summary').click()
                    page.select_option('#cut-preset','custom')
                    page.check('#staging-on')
                    page.locator('#settings-preview').evaluate('n=>n.open=true')
                    page.locator('#settings-updates > summary').click()
                    page.locator('#settings-title').focus()
                    page.locator('#settings').evaluate('n=>n.scrollTop=0')
                    r=page.locator('#settings').bounding_box()
                    page.mouse.move(r['x']+r['width']/2,r['y']+r['height']/2)
                    page.mouse.wheel(0,500)
                    page.wait_for_function("() => document.querySelector('#settings').scrollTop>30")
                    page.locator('#settings-title').focus();page.locator('#settings').evaluate('n=>n.scrollTop=0')
                    page.keyboard.press('PageDown')
                    page.wait_for_function("() => document.querySelector('#settings').scrollTop>30")
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'settings-wheel-{width}.png'))
                    page.close()
            finally:browser.close()
