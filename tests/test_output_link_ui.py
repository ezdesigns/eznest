"""UI approval flow, including popup blocking; all OUTPUT traffic is simulated."""
import json
import os
import unittest
from unittest.mock import patch

import opt_out
import server
import output_link
import test_web_mvp
from playwright.sync_api import sync_playwright, expect

ATTEMPT = {'attemptId':'synthetic', 'state':'pending', 'userCode':'ABCD-2345',
           'approvalUrl':'https://output.jeezlabs.io/outpost/ez-nest/approve?link=12345678-1234-4234-8234-123456789abc',
           'expiresIn':600, 'pollAfter':3}

class LinkBrowserTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_web_mvp.WebMvpTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        env = patch.dict(os.environ, {'EZ_NEST_OUTPUT_UPLOADS':'', 'EZ_NEST_DEV':'0', 'EZ_NEST_OUTPUT_GATE_OPEN':'0', 'EZ_NEST_DEV_NO_OUTPUT':'0'})
        env.start()
        self.addCleanup(env.stop)

    def test_popup_and_approved_wait_then_connected(self):
        with patch.object(output_link, 'start', return_value=ATTEMPT), patch.object(output_link, 'status', side_effect=[
            {**ATTEMPT, 'state':'connecting'}, {**ATTEMPT, 'state':'connected'}
        ]), sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            try:
                context = browser.new_context()
                context.route('https://output.jeezlabs.io/**', lambda route: route.fulfill(body='Simulated OUTPUT approval'))
                page = context.new_page()
                page.goto(self.fixture.url() + '/web')
                page.click('#settings-open')
                page.locator('#settings-telemetry').evaluate('n => n.open = true')
                page.click('#output-pair')
                with context.expect_page() as popup:
                    page.click('#output-browser-start')
                popup.value.wait_for_url(ATTEMPT['approvalUrl'])
                self.assertIsNone(popup.value.evaluate('window.opener'))
                expect(page.locator('#output-browser-match')).to_have_text('ABCD-2345')
                expect(page.locator('#output-browser-status')).to_contain_text('Finishing', timeout=8000)
                expect(page.locator('#setup-shop')).to_be_visible()
                expect(page.locator('#setup-shop')).not_to_be_visible(timeout=8000)
                self.assertFalse(server.load_shop(server.WORK)['outputNetwork'])
            finally:
                browser.close()

    def test_blocked_popup_has_explicit_link_and_cancel_removes_attempt(self):
        with patch.object(output_link, 'start', return_value=ATTEMPT), patch.object(output_link, 'cancel', return_value={'state':'cancelled'}) as cancel, sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            try:
                page = browser.new_page(viewport={'width':390, 'height':844})
                page.add_init_script('window.open = () => null')
                page.goto(self.fixture.url() + '/web')
                page.click('#settings-open')
                page.locator('#settings-telemetry').evaluate('n => n.open = true')
                page.click('#output-pair')
                page.click('#output-browser-start')
                expect(page.locator('#output-browser-status')).to_contain_text('blocked')
                expect(page.locator('#output-browser-open')).to_have_attribute('href', ATTEMPT['approvalUrl'])
                page.screenshot(path=str(test_web_mvp.SCREENSHOTS / 'output-browser-approval-mobile.png'), full_page=True)
                page.click('#output-browser-cancel')
                expect(page.locator('#output-browser-waiting')).to_be_hidden()
                page.wait_for_timeout(150)
                cancel.assert_called_once_with(server.WORK, 'synthetic')
                expect(page.locator('#output-browser-start')).to_be_enabled()
            finally:
                browser.close()

    def test_unavailable_service_explains_fallback(self):
        with patch.object(output_link, 'start', side_effect=output_link.output_pairing.PairingError('unavailable', 'Browser connection is not available yet. Use a pairing code instead.')), sync_playwright() as pw:
            browser = test_web_mvp.launch_browser(pw)
            try:
                page = browser.new_page()
                page.add_init_script('window.open = () => null')
                page.goto(self.fixture.url() + '/web')
                page.click('#settings-open')
                page.locator('#settings-telemetry').evaluate('n => n.open = true')
                page.click('#output-pair')
                page.click('#output-browser-start')
                expect(page.locator('#output-browser-error')).to_contain_text('pairing code')
                page.locator('#output-connect-details').evaluate('n => n.open = true')
                expect(page.locator('#output-link-code')).to_be_visible()
                expect(page.locator('#output-link-submit')).to_be_enabled()
            finally:
                browser.close()

