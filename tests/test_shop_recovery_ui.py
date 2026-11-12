import json
import unittest
from unittest.mock import patch

import server
import shop_members
import material_inventory
import test_web_mvp
from test_material_inventory import values
from test_mixed_cuts import mixed_fixture


class RecoveryBrowserTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_web_mvp.WebMvpTests()
        self.lan = patch.object(server, 'LAN', True); self.lan.start()
        self.fixture.setUp()
        self.fixture.stop()
        class TestPeers(server.Handler):
            # Both test browsers run on this runner. These two URLs select
            # simulated TCP peers; production never trusts a header as identity.
            def client_ip(self):
                return '192.0.2.50' if self.headers.get('Host', '').startswith('localhost:') else '127.0.0.1'
        self.fixture.handler_type = TestPeers; self.fixture.start()

    def tearDown(self):
        self.fixture.tearDown(); self.lan.stop()

    def test_browser_that_does_not_keep_cookies_gets_actionable_message(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            try:
                page = browser.new_page()
                def drop_sign_in(route):
                    response = route.fetch()
                    # Playwright's request context shares the browser cookie jar.
                    # Remove the cookie accepted by route.fetch as well as the
                    # response header, to simulate a browser rejecting storage.
                    page.context.clear_cookies()
                    route.fulfill(response=response, headers={k:v for k,v in response.headers.items() if k.lower() != 'set-cookie'})
                page.route('**/api/shop-members/*', drop_sign_in)
                page.goto(self.fixture.url().replace('127.0.0.1', 'localhost'))
                page.fill('#team-member-name', 'Alex')
                page.fill('#team-code', shop_members.invite(server.WORK)['code']); page.click('#team-join')
                expect(page.locator('#shop-team-dialog [role=status]')).to_contain_text('invite was accepted, but this browser did not keep your sign-in')
                page.click('#team-recover'); page.fill('#team-recovery-name', 'Alex'); page.click('#team-recovery-request')
                expect(page.locator('#shop-team-dialog [role=status]')).to_contain_text('Allow cookies for this shop')
                self.assertEqual(len(shop_members.status(server.WORK, admin=True)['members']), 1)
            finally: browser.close()

    def test_missing_cookie_recovers_same_draft_after_host_approval_and_survives_refresh(self):
        from playwright.sync_api import sync_playwright, expect
        material_inventory.save(server.WORK, 'roll', values(), 0)
        stock_before = material_inventory.read(server.WORK)
        host_url = self.fixture.url()
        guest_url = host_url.replace('127.0.0.1', 'localhost')
        with sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            try:
                original = browser.new_context(); page = original.new_page(); page.goto(guest_url)
                page.fill('#team-member-name', 'Alex')
                page.fill('#team-code', shop_members.invite(server.WORK)['code']); page.click('#team-join')
                self.fixture.wait_ready(page)
                member_id = shop_members.status(server.WORK, admin=True)['members'][0]['id']
                page.set_input_files('#file', {'name':'Saved designer job.pdf','mimeType':'application/pdf','buffer':mixed_fixture(generic=False,registration=False)})
                page.wait_for_function('() => kits.length===1 && !importing && !draftPending && !draftDirty')
                draft_path = server.WORK / 'designers' / ('member-' + member_id) / 'draft.json'
                before = draft_path.read_bytes()
                original.close()
                # A completely new browser context has no original sign-in.
                context = browser.new_context(); guest = context.new_page(); guest.goto(guest_url)
                guest.click('#team-recover'); guest.fill('#team-recovery-name', 'Alex'); guest.click('#team-recovery-request')
                expect(guest.get_by_role('heading', name='Waiting for the shop PC')).to_be_visible()
                guest.reload()
                expect(guest.get_by_role('heading', name='Waiting for the shop PC')).to_be_visible()
                self.assertFalse(guest.evaluate("fetch('/api/session').then(r=>r.json()).then(s=>s.authenticated)"))
                host = browser.new_page(); host.goto(host_url); self.fixture.wait_ready(host)
                host.click('#shop-team-open')
                row = host.locator('.team-recovery')
                expect(row).to_contain_text('Alex · Computer 192.0.2.50')
                row.get_by_role('button', name='Restore access', exact=True).click()
                expect(host.locator('#shop-team-dialog [role=status]')).to_contain_text('Choose their existing name')
                row.get_by_label('Existing shop member').select_option(member_id)
                host.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'restore-access-host.png'))
                row.get_by_role('button', name='Restore access', exact=True).click()
                # Approval navigates the guest into their authenticated workspace.
                # A locator survives that navigation, unlike a page JS predicate.
                expect(guest.locator('body')).to_have_attribute('data-ready', '1', timeout=15000)
                self.assertEqual(guest.evaluate('kits[0].name'), 'Saved designer job.pdf')
                expect(guest.locator('#shop-team-dialog')).not_to_be_visible()
                guest.reload(); self.fixture.wait_ready(guest)
                self.assertEqual(guest.evaluate('kits[0].name'), 'Saved designer job.pdf')
                self.assertEqual(len(shop_members.status(server.WORK, admin=True)['members']), 1)
                self.assertEqual(draft_path.read_bytes(), before)
                self.assertEqual(material_inventory.read(server.WORK), stock_before)
                guest.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'restore-access-designer.png'))
                host.set_viewport_size({'width':390,'height':844})
                self.assertLessEqual(host.evaluate('document.documentElement.scrollWidth'), 390)
            finally:
                browser.close()


if __name__ == '__main__': unittest.main()
