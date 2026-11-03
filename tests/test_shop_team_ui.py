import opt_out
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

    def test_first_run_create_shop_and_return_to_materials(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            try:
                page.goto(self.fixture.url() + '/?view=simple')
                expect(page.get_by_role('heading', name='Welcome to Ez Nest')).to_be_visible()
                page.get_by_role('button', name='Create a shop', exact=True).click()
                page.locator('#team-shop-name').fill('Test Print Shop')
                page.locator('#team-create').click()
                expect(page.locator('#shop-team-dialog')).not_to_be_visible()
                page.locator('#shop-team-open').click()
                expect(page.get_by_role('heading', name='Test Print Shop')).to_be_visible()
                expect(page.locator('#shop-team-dialog')).to_contain_text('This PC is local only')
                expect(page.get_by_role('button', name='Create invitation')).to_have_count(0)
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'shop-team-local.png'))
                page.get_by_role('button', name='Done', exact=True).click()
                page.reload()
                expect(page.locator('#shop-team-dialog')).not_to_be_visible()
                expect(page.locator('#shop-team-open')).to_have_text('Test Print Shop')
            finally:
                browser.close()

    def test_full_mode_first_run_can_continue_local(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            try:
                page.goto(self.fixture.url() + '/')
                expect(page.get_by_role('heading', name='Welcome to Ez Nest')).to_be_visible()
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'shop-team-welcome.png'))
                page.get_by_role('button', name='Use this PC for now').click()
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
