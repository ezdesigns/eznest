import opt_out
import os
import time
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
                expect(page.locator('#shop-team-dialog')).to_contain_text('shop network')
                expect(page.get_by_role('button', name='Invite someone')).to_have_count(0)
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'shop-team-local.png'))
                page.get_by_role('button', name='Done', exact=True).click()
                page.reload()
                expect(page.locator('#shop-team-dialog')).not_to_be_visible()
                expect(page.locator('#shop-team-open')).to_have_text('Test Print Shop')
                expect(page.locator('#shop-team-open')).to_have_attribute('title', 'Test Print Shop')
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
                page.get_by_role('button', name='Invite someone', exact=True).click()
                expect(page.locator('#team-invitation')).to_contain_text('Expires in 15 minutes')
                code_box = page.locator('#team-invitation').bounding_box()
                done_box = page.get_by_role('button', name='Done', exact=True).bounding_box()
                self.assertLessEqual(code_box['y'], done_box['y'])
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'shop-team-host.png'))
                page.get_by_role('button', name='Cancel unused invites').click()
                expect(page.locator('#team-invitation')).to_be_hidden()
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
                    expect(page.locator('#output-required')).to_be_hidden()
                    expect(page.locator('#shop-team-open')).to_have_text(name)
                    expect(page.locator('#shop-team-open')).to_have_attribute('title', name)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS / f'output-invitation-{width}.png'), full_page=True)
                    page.click('#output-dot')
                    expect(page.locator('#output-explore')).to_be_focused()
                    expect(page.locator('#output-link-code')).to_be_hidden()
                    self.assertEqual(len(context.pages), 1)
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS / f'output-discovery-{width}.png'), full_page=True)
                    with context.expect_page() as opened:
                        page.click('#output-explore')
                    self.assertEqual(opened.value.url, 'https://output.jeezlabs.io/')
                    opened.value.close()
                    page.locator('#output-connect-details summary').click()
                    expect(page.locator('#output-connect-help')).to_contain_text('turned off')
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
                expect(page.locator('#shop-team-dialog')).to_contain_text('Ask the shop computer')
                expect(page.locator('#logout')).to_have_text('Log out')
                logout = page.locator('#logout').bounding_box()
                self.assertGreaterEqual(logout['width'], 48)
                self.assertLessEqual(logout['x'] + logout['width'], 390)
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'shop-team-joined-mobile.png'))
                member = shop_members.status(server.WORK, admin=True)['members'][0]
                shop_members.revoke(server.WORK, member['id'])
                removed = page.evaluate("fetch('/api/materials').then(async r => ({status: r.status, body: await r.json()}))")
                self.assertEqual(removed['status'], 403)
                self.assertEqual(removed['body']['error'], 'Your access was removed.')
                page.reload()
                expect(page.get_by_text('Your access was removed. Ask for a new invite.')).to_be_visible()
            finally:
                browser.close()

    def test_plain_http_from_another_address_opens_join(self):
        """A second computer on plain HTTP, not this machine's loopback."""
        import socket
        import threading
        from urllib.request import urlopen
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(('192.0.2.1', 9))
            host_ip = probe.getsockname()[0]
        except OSError:
            self.skipTest('no second address')
        finally:
            probe.close()
        if host_ip.startswith('127.'):
            self.skipTest('only loopback')
        shop_members.create(server.WORK, 'Lan Shop')
        code = shop_members.invite(server.WORK)['code']
        self.fixture.stop()
        service = server.ThreadingHTTPServer(('0.0.0.0', 0), server.Handler)
        service.daemon_threads = False
        port = service.server_port
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        old_lan = server.LAN
        server.LAN = True
        server.PORT = port
        thread.start()
        try:
            address = f'http://{host_ip}:{port}'
            with patch('shop_deploy.lan_addresses', return_value=[host_ip]):
                import shop_deploy
                shop_deploy.clear_name_cache()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        with urlopen(address + '/api/session', timeout=0.2) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.02)
                else:
                    self.fail('second address did not accept the session request')
                from playwright.sync_api import sync_playwright, expect
                with sync_playwright() as pw:
                    browser = test_web_mvp.launch_browser(pw)
                    page = browser.new_page(viewport={'width': 1280, 'height': 900})
                    try:
                        page.goto(address + '/?view=simple')
                        expect(page.get_by_role('heading', name='Join Lan Shop')).to_be_visible()
                        expect(page.locator('#output-required')).to_be_hidden()
                        page.locator('#team-member-name').fill('Other PC')
                        page.locator('#team-code').fill(code)
                        page.locator('#team-join').click()
                        expect(page.locator('#shop-team-dialog')).not_to_be_visible()
                        session = page.evaluate("fetch('/api/session').then(r => r.json())")
                        self.assertTrue(session['authenticated'])
                        self.assertFalse(session['localPC'])
                        self.assertNotIn('token', session)
                    finally:
                        browser.close()
        finally:
            server.LAN = old_lan
            service.shutdown()
            service.server_close()
            thread.join(timeout=5)
