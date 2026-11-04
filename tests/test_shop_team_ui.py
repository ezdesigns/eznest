import opt_out
import os
import unittest
from unittest.mock import patch

import server
import shop_members
import test_web_mvp


class ShopTeamBrowserTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_web_mvp.WebMvpTests()
        self.fixture.seed_shop = False
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_walkthrough_navigation_remembered_and_replay_without_connecting(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser=test_web_mvp.launch_browser(pw)
            try:
                for width,height in [(1280,720),(390,600)]:
                    page=browser.new_page(viewport={'width':width,'height':height})
                    posts=[];page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
                    page.goto(self.fixture.url()+'/web')
                    for step in range(3):
                        expect(page.locator('#tour-progress')).to_have_text(f'Quick tour · {step+1} of 3')
                        if step == 0:
                            page.wait_for_function("() => {const video=document.querySelector('.tour-illustration'); return video && video.readyState>=2 && video.currentTime>0;}")
                            self.assertTrue(page.locator('.tour-illustration').get_attribute('src').startswith('/onboarding-'))
                            page.get_by_role('button', name='Pause animation').click()
                            self.assertTrue(page.locator('video').evaluate('v=>v.paused'))
                            page.get_by_role('button', name='Play animation').click()
                            page.wait_for_function("() => !document.querySelector('video').paused")
                        if step == 2:
                            page.wait_for_function("() => [...document.querySelectorAll('.tour-network img')].every(i=>i.complete && i.naturalWidth>0)")
                        page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'walkthrough-{step+1}-{width}.png'))
                        if step<2:page.click('#tour-next')
                    page.click('#tour-back');expect(page.locator('#tour-progress')).to_contain_text('2 of 3')
                    page.click('#tour-next');expect(page.locator('#tour-output-link')).to_have_attribute('href','https://output.jeezlabs.io/')
                    page.click('#tour-next');self.fixture.wait_ready(page)
                    expect(page.locator('#shop-team-dialog')).to_be_hidden()
                    self.assertFalse(shop_members.configured(server.WORK))
                    page.reload();self.fixture.wait_ready(page)
                    expect(page.locator('#shop-team-dialog')).to_be_hidden()
                    page.click('#settings-support > summary');page.click('#replay-walkthrough')
                    expect(page.locator('#tour-progress')).to_contain_text('1 of 3')
                    page.keyboard.press('Escape');expect(page.locator('#shop-team-dialog')).to_be_hidden()
                    page.goto(self.fixture.url()+'/?tour=1')
                    expect(page.locator('#tour-progress')).to_contain_text('1 of 3')
                    self.assertNotIn('tour=',page.url)
                    page.get_by_role('button',name='Close walkthrough').click()
                    page.reload();self.fixture.wait_ready(page)
                    expect(page.locator('#shop-team-dialog')).to_be_hidden()
                    self.assertFalse(any('/output/link' in url or '/shop-members/create' in url or '/telemetry/output/pair' in url for url in posts))
                    page.close()
            finally:browser.close()

    def test_reduced_motion_and_leaving_slide_stop_animation(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser=test_web_mvp.launch_browser(pw)
            try:
                page=browser.new_page(reduced_motion='reduce')
                external=[]
                page.on('request',lambda r:external.append(r.url) if not r.url.startswith(self.fixture.url()) else None)
                page.goto(self.fixture.url()+'/?tour=1')
                expect(page.get_by_role('button',name='Play animation')).to_be_visible()
                self.assertTrue(page.locator('video').evaluate('v=>v.paused'))
                page.evaluate('() => {window.tourVideo=document.querySelector("video");}')
                page.get_by_role('button',name='Play animation').click()
                page.wait_for_function('() => !window.tourVideo.paused')
                page.click('#tour-next')
                self.assertTrue(page.evaluate('() => window.tourVideo.paused'))
                page.click('#tour-next')
                expect(page.locator('.tour-network')).to_have_attribute('data-running','false')
                page.keyboard.press('Escape')
                self.assertFalse(external)
            finally:browser.close()

    def test_output_stories_cycle_pause_and_cleanup(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser=test_web_mvp.launch_browser(pw)
            try:
                page=browser.new_page(viewport={'width':390,'height':600})
                page.goto(self.fixture.url()+'/?tour=1')
                page.click('#tour-next');page.click('#tour-next')
                page.clock.install()
                page.get_by_role('button',name='Pause animation').click()
                page.get_by_role('button',name='Play animation').click()
                page.clock.run_for(10900)
                expect(page.locator('.tour-network')).to_have_attribute('data-example','1')
                page.get_by_role('button',name='Pause animation').click()
                page.clock.run_for(20000)
                expect(page.locator('.tour-network')).to_have_attribute('data-example','1')
                for index in [2,3,4,5,0]:
                    page.get_by_role('button',name='Next example').click()
                    expect(page.locator('.tour-network')).to_have_attribute('data-example',str(index))
                    page.wait_for_function("() => [...document.querySelectorAll('.tour-network img,.tour-story-brief img')].every(i=>i.complete && i.naturalWidth>0)")
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'output-story-{index}-390.png'))
                page.get_by_role('button',name='Previous example').click()
                expect(page.locator('#tour-story-job')).to_have_text('100 printed T-shirts')
                page.get_by_role('button',name='Play animation').click()
                page.evaluate("() => {window.oldStory=document.querySelector('.tour-network');}")
                page.keyboard.press('Escape')
                page.clock.run_for(30000)
                self.assertEqual(page.evaluate('() => window.oldStory.dataset.example'),'5')
                self.assertEqual(page.evaluate('() => window.oldStory.dataset.running'),'false')
            finally:browser.close()

    def test_first_run_create_shop_and_return_to_materials(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            try:
                page.goto(self.fixture.url() + '/?view=simple')
                expect(page.get_by_role('heading', name='Fit more. Waste less.')).to_be_visible()
                page.click('#tour-next'); page.click('#tour-next')
                expect(page.locator('#tour-output-link')).to_have_attribute('href','https://output.jeezlabs.io/')
                page.click('#tour-next'); self.fixture.wait_ready(page)
                page.click('#shop-team-open')
                expect(page.get_by_role('button', name='Create a shop', exact=True)).to_have_count(0)
                page.locator('#team-create').click()
                self.assertFalse(shop_members.configured(server.WORK))
                page.locator('#team-shop-name').fill('Test Print Shop')
                page.locator('#team-shop-name').press('Enter')
                expect(page.locator('#shop-team-dialog')).not_to_be_visible()
                page.locator('#shop-team-open').click()
                expect(page.get_by_role('heading', name='Test Print Shop')).to_be_visible()
                expect(page.locator('#shop-team-dialog')).to_contain_text('This PC is local only')
                expect(page.get_by_role('button', name='Create invitation')).to_have_count(0)
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'shop-team-local.png'))
                page.get_by_role('button', name='Close shop', exact=True).click()
                page.reload()
                expect(page.locator('#shop-team-dialog')).not_to_be_visible()
                expect(page.locator('#shop-team-open')).to_have_text('Test Print Shop')
                page.goto(self.fixture.url() + '/?view=full')
                expect(page.locator('#shop-team-open')).to_have_text('Test Print Shop')
                self.assertFalse(server.load_shop(server.WORK)['outputNetwork'])
            finally:
                browser.close()

    def test_full_mode_first_run_can_continue_local(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            try:
                page.goto(self.fixture.url() + '/?view=full')
                expect(page.get_by_role('heading', name='Fit more. Waste less.')).to_be_visible()
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'shop-team-welcome.png'))
                page.get_by_role('button', name='Skip tour').click()
                expect(page.locator('#shop-team-dialog')).not_to_be_visible()
                self.assertFalse(shop_members.configured(server.WORK))
            finally:
                browser.close()

    def test_host_can_invite_and_cancel_without_enabling_output(self):
        from playwright.sync_api import sync_playwright, expect
        shop_members.create(server.WORK, 'Team host')
        with patch.object(server, 'LAN', True), patch.object(server, 'host_name', return_value='TEST-SHOP'), sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            try:
                page.goto(self.fixture.url() + '/?view=simple')
                page.locator('#shop-team-open').click()
                expect(page.locator('#shop-team-dialog code')).to_contain_text('http://TEST-SHOP:')
                page.get_by_role('button', name='Create invitation', exact=True).click()
                expect(page.locator('#team-invitation')).to_contain_text('Expires in 15 minutes')
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'shop-team-host.png'))
                page.get_by_role('button', name='Cancel unused invitations').click()
                expect(page.locator('#team-invitation')).to_have_count(0)
                self.assertFalse(server.load_shop(server.WORK)['outputNetwork'])
            finally:
                browser.close()

    def test_output_discovery_works_with_connection_off_on_desktop_and_phone(self):
        from playwright.sync_api import sync_playwright, expect
        import output_credential
        name = 'Northside Print and Graphics Studio'
        shop_members.create(server.WORK, name)
        with patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS': '0', 'EZ_NEST_DEV': '0', 'EZ_NEST_OUTPUT_GATE_OPEN': '0', 'EZ_NEST_DEV_NO_OUTPUT': '0'}), sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            try:
                for width in (1280, 390):
                    context = browser.new_context(viewport={'width': width, 'height': 900})
                    context.route('https://output.jeezlabs.io/**', lambda route: route.fulfill(body='OUTPUT pilot'))
                    page = context.new_page()
                    page.goto(self.fixture.url() + '/?view=simple')
                    page.wait_for_function("() => document.body.dataset.ready === '1'")
                    expect(page.locator('#shop-team-open')).to_have_text(name)
                    expect(page.locator('#shop-team-open')).to_have_attribute('title', name)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS / f'output-invitation-{width}.png'), full_page=True)
                    page.click('#output-required-code')
                    expect(page.locator('#output-explore')).to_be_focused()
                    expect(page.locator('#output-link-code')).to_be_hidden()
                    self.assertEqual(len(context.pages), 1)
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS / f'output-discovery-{width}.png'), full_page=True)
                    with context.expect_page() as opened:
                        page.click('#output-explore')
                    self.assertEqual(opened.value.url, 'https://output.jeezlabs.io/')
                    opened.value.close()
                    expect(page.locator('#output-connect-details')).to_be_hidden()
                    expect(page.locator('#output-browser-start')).to_be_hidden()
                    expect(page.locator('#output-link-submit')).to_be_hidden()
                    page.click('#output-link-cancel')
                    expect(page.locator('#setup-shop')).not_to_be_visible()
                    self.assertFalse(output_credential.path(server.WORK).exists())
                    self.assertFalse(server.load_shop(server.WORK)['outputNetwork'])
                    context.close()
            finally:
                browser.close()

    def test_invited_browser_joins_without_host_token_and_sees_shared_stock(self):
        from playwright.sync_api import sync_playwright, expect
        import material_inventory
        from test_material_inventory import values
        shop_members.create(server.WORK, 'Shared shop')
        material_inventory.save(server.WORK, 'shared-roll', values(), 0)
        code = shop_members.invite(server.WORK)['code']
        class RemoteHandler(server.Handler):
            def loopback_client(self): return False
            def client_ip(self): return '192.168.1.51'
        self.fixture.stop()
        self.fixture.handler_type = RemoteHandler
        # start() probes /api/session without browser headers; replace only its
        # startup probe, not the handler's actual origin checks.
        class Probe:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch('test_web_mvp.urlopen', return_value=Probe()): self.fixture.start()
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            try:
                page.goto(self.fixture.url() + '/?view=simple')
                expect(page.get_by_role('heading', name='Join Shared shop')).to_be_visible()
                expect(page.locator('#shop-team-close')).to_be_hidden()
                page.keyboard.press('Escape'); page.mouse.click(5,5)
                expect(page.locator('#shop-team-dialog')).to_be_visible()
                page.locator('#team-member-name').fill('Designer A')
                page.locator('#team-code').fill(code)
                page.locator('#team-join').click()
                expect(page.locator('#shop-team-dialog')).not_to_be_visible()
                session = page.evaluate("fetch('/api/session').then(r=>r.json())")
                self.assertTrue(session['authenticated'])
                self.assertNotIn('token', session)
                stock = page.evaluate("fetch('/api/materials').then(r=>r.json())")
                self.assertEqual(stock['materials'][0]['onHandMm'], 1000)
                page.locator('#shop-team-open').click()
                expect(page.locator('#shop-team-dialog')).to_contain_text('Ask the host')
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'shop-team-joined-mobile.png'))
                member = shop_members.status(server.WORK, admin=True)['members'][0]
                shop_members.revoke(server.WORK, member['id'])
                self.assertEqual(page.evaluate("fetch('/api/materials').then(r=>r.status)"), 403)
            finally:
                browser.close()
