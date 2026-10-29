"""Consent UI uses the real local API; synthetic credentials never reach a network."""
import opt_out
import os
import unittest
from unittest.mock import patch
import test_web_mvp
import server
import telemetry
import telemetry_sender
from test_telemetry import JOB, RESULT
from playwright.sync_api import sync_playwright


class ConsentScreenTests(unittest.TestCase):
    def test_explicit_future_only_consent_and_stop(self):
        helper=test_web_mvp.WebMvpTests(methodName='runTest')
        helper.setUp()
        try:
            with patch.dict(os.environ,{'EZ_NEST_OUTPUT_UPLOADS':'1','EZ_NEST_OUTPUT_TOKEN':'osa_'+'A'*43}), patch.object(telemetry_sender,'emit',return_value=True) as emit, sync_playwright() as p:
                telemetry.observe(server.WORK,'a'*32,JOB,RESULT)
                browser=test_web_mvp.launch_browser(p)
                try:
                    page=browser.new_page(viewport={'width':1280,'height':900})
                    page.goto(helper.url()+'/web');helper.wait_ready(page)
                    page.click('#connect-chip')
                    page.wait_for_function("() => !document.querySelector('#telemetry-agree').disabled")
                    self.assertTrue(page.locator('#output-pair-form').is_hidden())
                    self.assertIn('launch settings', page.locator('#output-connect-status').inner_text())
                    self.assertTrue(page.locator('#telemetry-enable').is_disabled())
                    self.assertIn('What is shared', page.locator('#connect-popover').inner_text())
                    self.assertIn('lengthMmBand',page.locator('#telemetry-preview').text_content())
                    self.assertEqual(telemetry_sender.tick(server.WORK),0);emit.assert_not_called()
                    page.check('#telemetry-agree');page.click('#output-pair')
                    page.wait_for_function("() => document.querySelector('#telemetry-status').textContent.startsWith('Sharing new activity.')")
                    self.assertEqual(telemetry_sender.tick(server.WORK),0);emit.assert_not_called()
                    telemetry.observe(server.WORK,'b'*32,JOB,RESULT)
                    self.assertEqual(telemetry_sender.tick(server.WORK),2)
                    self.assertEqual({c.args[0]['nestId'] for c in emit.call_args_list},{'b'*32})
                    with patch.object(server,'telemetry_paused',return_value=True):
                        page.wait_for_function("() => document.querySelector('#telemetry-status').textContent.startsWith('Sharing paused')")
                        self.assertTrue(page.locator('#telemetry-stop').is_disabled())
                        self.assertTrue(page.locator('#telemetry-agree').is_disabled())
                        page.screenshot(path=str(test_web_mvp.SCREENSHOTS/'telemetry-paused-desktop.png'),full_page=True)
                        page.set_viewport_size({'width':390,'height':844})
                        page.locator('#telemetry-status').scroll_into_view_if_needed()
                        self.assertTrue(page.locator('#telemetry-status').is_visible())
                        page.screenshot(path=str(test_web_mvp.SCREENSHOTS/'telemetry-paused-mobile.png'),full_page=True)
                        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
                        page.set_viewport_size({'width':1280,'height':900})
                    page.wait_for_function("() => document.querySelector('#telemetry-status').textContent.startsWith('Sharing new activity.')")
                    page.click('#output-pair')
                    page.wait_for_function("() => document.querySelector('#telemetry-status').textContent.startsWith('Off.')")
                    telemetry.observe(server.WORK,'c'*32,JOB,RESULT)
                    self.assertEqual(telemetry_sender.tick(server.WORK),0)
                    self.assertEqual(emit.call_count,2)
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/'telemetry-consent-desktop.png'),full_page=True)
                    page.set_viewport_size({'width':390,'height':844})
                    page.screenshot(path=str(test_web_mvp.SCREENSHOTS/'telemetry-consent-mobile.png'),full_page=True)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
                finally:browser.close()
        finally:helper.tearDown()
