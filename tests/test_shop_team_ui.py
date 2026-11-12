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

    def test_join_accepts_the_address_shown_in_host_settings(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            try:
                for path in ('/web', '/web/', '/'):
                    page = browser.new_page()
                    page.route('http://shop-pc:8765/**', lambda route: route.fulfill(body='Shop host'))
                    page.goto(self.fixture.url())
                    page.click('#tour-next')
                    page.get_by_role('button', name='Join a shop', exact=True).click()
                    page.fill('#team-address', 'http://SHOP-PC:8765' + path)
                    page.get_by_role('button', name='Open shop', exact=True).click()
                    expect(page).to_have_url('http://shop-pc:8765/?view=simple', timeout=2000)
                    page.close()
            finally:
                browser.close()

    def test_join_still_rejects_unrelated_paths_public_sites_and_secrets_in_urls(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            page = browser.new_page()
            try:
                page.goto(self.fixture.url())
                page.click('#tour-next')
                page.get_by_role('button', name='Join a shop', exact=True).click()
                for address in ('https://example.com/', 'http://localhost:8765/',
                                'http://SHOP-PC:8765/api/session', 'http://SHOP-PC:8765/web?code=secret',
                                'http://user:secret@SHOP-PC:8765/web', 'http://SHOP-PC:8765/web#secret'):
                    page.fill('#team-address', address)
                    page.get_by_role('button', name='Open shop', exact=True).click()
                    expect(page.locator('#shop-team-dialog [role=status]')).to_contain_text('Enter a shop PC name')
                    self.assertTrue(page.url.startswith(self.fixture.url()))
            finally:
                browser.close()

    def test_open_inventory_refreshes_other_members_changes_without_overwriting_edits(self):
        from playwright.sync_api import sync_playwright, expect
        import material_inventory
        from test_material_inventory import values
        shop_members.create(server.WORK, 'Shared shop')
        material_inventory.save(server.WORK, 'shared-roll', values(), 0)
        class RemoteHandler(server.Handler):
            def loopback_client(self): return False
        self.fixture.stop()
        self.fixture.handler_type = RemoteHandler
        self.fixture.start()
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            try:
                pages = [browser.new_page(), browser.new_page()]
                first_code = shop_members.invite(server.WORK)['code']
                for page, name in zip(pages, ('Alex', 'Sam')):
                    page.goto(self.fixture.url())
                    page.fill('#team-member-name', name)
                    page.fill('#team-code', first_code)
                    if name == 'Sam':
                        page.click('#team-join')
                        expect(page.locator('#shop-team-dialog [role=status]')).to_contain_text('already used')
                        page.fill('#team-code', shop_members.invite(server.WORK)['code'])
                    page.click('#team-join')
                    self.fixture.wait_ready(page)
                    page.click('#stock-open')
                    expect(page.locator('#stock-list')).to_contain_text('3.28 ft')
                reader, writer = pages
                writer.locator('#stock-list [role=option]').click()
                writer.get_by_role('button', name='Edit', exact=True).click()
                writer.fill('#roll-f-left', '2')
                writer.get_by_role('button', name='Save', exact=True).click()
                expect(writer.locator('#stock-status')).to_contain_text('2 ft left')
                reader.bring_to_front()
                # Let the real ten-second poll complete. Advancing a fake
                # clock can fire fetch's abort timer before real HTTP finishes.
                expect(reader.locator('#stock-list')).to_contain_text('2 ft', timeout=20000)
                reader.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'local-sharing-stock-desktop.png'))
                reader.set_viewport_size({'width': 390, 'height': 844})
                self.assertLessEqual(reader.evaluate('document.documentElement.scrollWidth'), 390)
                reader.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'local-sharing-stock-mobile.png'))
                reader.set_viewport_size({'width': 1280, 'height': 900})
                reader.locator('#stock-list [role=option]').click()
                reader.get_by_role('button', name='Edit', exact=True).click()
                reader.fill('#roll-f-name', 'Unsaved roll name')
                writer.get_by_role('button', name='Edit', exact=True).click()
                writer.fill('#roll-f-left', '1')
                writer.get_by_role('button', name='Save', exact=True).click()
                expect(writer.locator('#stock-status')).to_contain_text('1 ft left')
                reader.bring_to_front()
                # Observe a full poll interval while the unsaved form is open.
                reader.wait_for_timeout(11000)
                expect(reader.locator('#roll-f-name')).to_have_value('Unsaved roll name')
                reader.get_by_role('button', name='Save', exact=True).click()
                expect(reader.locator('#stock-panel')).to_contain_text('changed', timeout=2000)
                self.assertEqual(material_inventory.read(server.WORK)['materials'][0]['onHandMm'], 304.8)
                reader.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'local-sharing-stale-edit.png'))
                writer.click('#stock-close')
                writer.click('#shop-team-open')
                expect(writer.locator('.team-person span')).to_have_text(['Alex', 'Sam'])
                expect(writer.get_by_role('button', name='Remove access', exact=True)).to_have_count(0)
                writer.set_viewport_size({'width': 390, 'height': 844})
                expect(writer.locator('.team-person').first).to_be_in_viewport()
                expect(writer.locator('.team-person').last).to_be_in_viewport()
                writer.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'shop-people-mobile.png'))
            finally:
                browser.close()

    def test_member_can_add_stock_on_plain_http_without_secure_context_apis(self):
        from playwright.sync_api import sync_playwright, expect
        shop_members.create(server.WORK, 'HTTP shop')
        class RemoteHandler(server.Handler):
            def loopback_client(self): return False
        self.fixture.stop()
        self.fixture.handler_type = RemoteHandler
        self.fixture.start()
        with patch.object(server, 'LAN', True), patch('shop_deploy.host_name', return_value='test-shop'), sync_playwright() as pw:
            # Resolve a shop hostname directly to the isolated test listener. This
            # is genuine insecure HTTP, without relying on a physical adapter/VPN.
            browser = test_web_mvp.launch_browser(pw, args=['--host-resolver-rules=MAP test-shop 127.0.0.1', '--no-proxy-server'])
            page = browser.new_page()
            try:
                page.goto(f'http://test-shop:{server.PORT}/')
                self.assertFalse(page.evaluate('isSecureContext'))
                self.assertEqual(page.evaluate('typeof crypto.randomUUID'), 'undefined')
                page.fill('#team-member-name', 'Designer')
                page.fill('#team-code', shop_members.invite(server.WORK)['code'])
                page.click('#team-join')
                self.fixture.wait_ready(page)
                page.click('#stock-open')
                page.get_by_role('button', name='Add roll', exact=True).click()
                for field, value in [('name', 'Shared gloss'), ('roll', '54'), ('width', '51.5'), ('left', '100')]:
                    page.fill('#roll-f-' + field, value)
                page.get_by_role('button', name='Save roll', exact=True).click()
                expect(page.locator('#stock-status')).to_contain_text('Added Shared gloss', timeout=2000)
                expect(page.locator('#stock-list')).to_contain_text('Shared gloss', timeout=2000)
                expect(page.locator('#stock-list')).to_contain_text('100 ft')
                self.assertEqual(page.evaluate("sha256(new TextEncoder().encode('abc'))"), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
                session = page.evaluate("fetch('/api/session').then(r => r.json())")
                self.assertNotIn('token', session)
            finally:
                browser.close()

    def test_walkthrough_navigation_remembered_and_replay_without_connecting(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser=test_web_mvp.launch_browser(pw)
            try:
                for width,height in [(1280,720),(390,600)]:
                    page=browser.new_page(viewport={'width':width,'height':height})
                    posts=[];page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
                    page.goto(self.fixture.url()+'/web')
                    expect(page.locator('#shop-team-title')).to_have_text('Thanks for downloading Ez Nest')
                    expect(page.locator('#shop-team-title .tour-brand')).to_have_text('Ez Nest')
                    self.assertEqual(page.locator('.tour-brand').evaluate('n => getComputedStyle(n).display'), 'block')
                    expect(page.locator('#tour-progress')).to_have_count(0)
                    expect(page.locator('#tour-back')).to_have_count(0)
                    expect(page.locator('.tour-steps li')).to_have_count(3)
                    page.wait_for_function("() => [...document.querySelectorAll('.tour-steps img')].length === 3 && [...document.querySelectorAll('.tour-steps img')].every(n => n.complete && n.naturalWidth > 0)")
                    expect(page.locator('#tour-output-link')).to_have_attribute('href','https://output.jeezlabs.io/')
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/f'single-welcome-{width}.png'))
                    page.click('#tour-next')
                    expect(page.get_by_role('button', name='Create a shop', exact=True)).to_be_visible()
                    page.get_by_role('button', name='Use this PC for now', exact=True).click()
                    self.fixture.wait_ready(page)
                    expect(page.locator('#shop-team-dialog')).to_be_hidden()
                    self.assertFalse(shop_members.configured(server.WORK))
                    page.reload();self.fixture.wait_ready(page)
                    expect(page.locator('#shop-team-dialog')).to_be_hidden()
                    page.click('#settings-support > summary');page.click('#replay-walkthrough')
                    expect(page.locator('#shop-team-title')).to_have_text('Thanks for downloading Ez Nest')
                    page.keyboard.press('Escape');expect(page.locator('#shop-team-dialog')).to_be_hidden()
                    page.goto(self.fixture.url()+'/?tour=1')
                    expect(page.locator('#shop-team-title')).to_have_text('Thanks for downloading Ez Nest')
                    self.assertNotIn('tour=',page.url)
                    page.get_by_role('button',name='Close welcome').click()
                    page.reload();self.fixture.wait_ready(page)
                    expect(page.locator('#shop-team-dialog')).to_be_hidden()
                    self.assertFalse(any('/output/link' in url or '/shop-members/create' in url or '/telemetry/output/pair' in url for url in posts))
                    page.close()
            finally:browser.close()

    def test_first_run_create_shop_and_return_to_materials(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            try:
                page.goto(self.fixture.url() + '/?view=simple')
                page.click('#tour-next')
                expect(page.get_by_role('heading', name='Welcome to Ez Nest')).to_be_visible()
                page.get_by_role('button', name='Create a shop', exact=True).click()
                page.locator('#team-shop-name').fill('Test Print Shop')
                page.locator('#team-create').click()
                self.fixture.wait_ready(page)
                expect(page.locator('#shop-team-dialog')).not_to_be_visible()
                page.locator('#shop-team-open').click()
                expect(page.get_by_role('heading', name='Test Print Shop')).to_be_visible()
                expect(page.locator('#shop-team-dialog')).to_contain_text('shop network')
                expect(page.get_by_role('button', name='Invite someone')).to_have_count(0)
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'shop-team-local.png'))
                page.get_by_role('button', name='Close shop', exact=True).click()
                page.reload()
                expect(page.locator('#shop-team-dialog')).not_to_be_visible()
                expect(page.locator('#shop-team-open')).to_have_text('Test Print Shop')
                expect(page.locator('#shop-team-open')).to_have_attribute('title', 'Test Print Shop')
                expect(page.locator('#shop-invite-open')).to_have_count(0)
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
                expect(page.get_by_role('heading', name='Thanks for downloading Ez Nest')).to_be_visible()
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'shop-team-welcome.png'))
                expect(page.get_by_role('button', name='Skip tour')).to_have_count(0)
                page.get_by_role('button', name='Close welcome').click()
                expect(page.get_by_role('button', name='Join a shop', exact=True)).to_be_visible()
                page.get_by_role('button', name='Use this PC for now', exact=True).click()
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
                self.assertGreater(code_box['height'], 0)
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
                    with context.expect_page() as opened:
                        page.click('#output-dot')
                    opened.value.wait_for_url('https://output.jeezlabs.io/outpost/ez-nest')
                    self.assertIsNone(opened.value.evaluate('window.opener'))
                    opened.value.close()
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
                # Joining writes membership and refreshes the session. Allow the
                # ten-second SQLite busy timeout plus HTTP overhead on Windows,
                # while still requiring a successful join and the completed UI.
                with page.expect_response('**/api/shop-members/join', timeout=15000) as joined:
                    page.locator('#team-join').click()
                self.assertEqual(joined.value.status, 200)
                self.fixture.wait_ready(page)
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
                expect(page.get_by_text('This browser’s saved sign-in is no longer valid. You can ask the shop PC to restore access.')).to_be_visible()
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
        class RemoteHandler(server.Handler):
            # The browser still runs on this runner, so connecting to its LAN
            # address now correctly redirects to host access. Simulate the TCP
            # peer of another PC while keeping real insecure HTTP transport.
            # Separate membership tests cover peer-based host detection.
            def client_ip(self): return '192.0.2.44'
        service = server.ThreadingHTTPServer(('0.0.0.0', 0), RemoteHandler)
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
                        self.fixture.wait_ready(page)
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
