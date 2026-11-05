"""Real launch animation: readiness, first use, failures and reduced motion."""
import opt_out
from pathlib import Path
import unittest
import threading

from startup import browser_page


class StartupPathTests(unittest.TestCase):
    def test_launch_keeps_workspace_and_handoff_and_never_adds_an_origin(self):
        self.assertEqual(browser_page('/'), '/?startup=1')
        self.assertEqual(browser_page('/?view=full&illustrator=abc#job'), '/?view=full&illustrator=abc&startup=1#job')
        self.assertEqual(browser_page('/?startup=1&view=simple'), '/?view=simple&startup=1')
        for value in ['https://example.com/', '//example.com/', 'relative']:
            with self.assertRaises(ValueError):
                browser_page(value)


class StartupScreenTests(unittest.TestCase):
    def setUp(self):
        from test_web_mvp import WebMvpTests
        import server
        owner = self
        self.state_release = threading.Event(); self.state_release.set()
        self.state_requested = threading.Event()
        self.state_failure = False
        class StartupHandler(server.Handler):
            def handle(self):
                try:
                    return super().handle()
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    pass

            def do_GET(self):
                if self.path == '/api/state':
                    owner.state_requested.set()
                    if not owner.state_release.wait(15):
                        raise TimeoutError('The startup test did not release the workspace read.')
                    if owner.state_failure:
                        return self.send(503, {'error': 'unavailable'})
                try:
                    return super().do_GET()
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    pass  # The app may abort the first held read and retry it.
        self.fixture = WebMvpTests()
        self.fixture.handler_type = StartupHandler
        self.fixture.seed_shop = self._testMethodName != 'test_first_use_opens_welcome_then_create_or_join'
        self.fixture.setUp()
        self.shots = Path(__file__).resolve().parents[1] / '.local' / 'startup-screenshots'
        self.shots.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.state_release.set()
        self.fixture.tearDown()

    def test_launch_waits_then_reveals_single_workspace_from_legacy_links(self):
        from playwright.sync_api import sync_playwright, expect
        from test_web_mvp import launch_browser
        with sync_playwright() as pw:
            browser = launch_browser(pw)
            try:
                for mode in ['simple', 'full']:
                    page = browser.new_page(viewport={'width': 1280, 'height': 900})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    self.state_requested.clear(); self.state_release.clear()
                    page.goto(self.fixture.url() + '/?view=' + mode + '&startup=1')
                    expect(page.locator('#app-startup')).to_be_visible()
                    self.assertNotIn('startup=', page.url)
                    self.assertIn('view=' + mode, page.url)
                    start = page.locator('.startup-rider').bounding_box()['x']
                    page.screenshot(path=str(self.shots / f'{mode}-left.png'))
                    page.wait_for_timeout(4700)
                    expect(page.locator('#app-startup')).to_be_visible()
                    self.assertGreater(page.locator('.startup-rider').bounding_box()['x'], start + 100)
                    # A busy runner may still be loading the workspace after the
                    # animation interval. Synchronize on the held server request.
                    self.assertTrue(self.state_requested.wait(10), 'Workspace request must be waiting before reveal')
                    self.assertEqual(page.locator('header').evaluate('n => getComputedStyle(n).visibility'), 'hidden')
                    if mode == 'simple':
                        page.evaluate("() => { window.startupExport = exportFile; window.startupExportCalls = 0; exportFile = () => window.startupExportCalls++; document.body.dataset.step = 'confirm'; }")
                        page.keyboard.press('Enter')
                        self.assertEqual(page.evaluate('startupExportCalls'), 0, 'Loading must not accept export shortcuts')
                        page.evaluate("() => { exportFile = window.startupExport; document.body.dataset.step = 'drop'; }")
                    page.screenshot(path=str(self.shots / f'{mode}-waiting.png'))
                    page.set_viewport_size({'width': 390, 'height': 844})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    page.screenshot(path=str(self.shots / f'{mode}-mobile.png'))
                    self.state_release.set()
                    expect(page.locator('#app-startup')).to_have_count(0, timeout=15000)
                    expect(page.locator('header')).to_be_visible()
                    expect(page.locator('#mode-switch')).to_have_count(0)
                    page.reload()
                    self.fixture.wait_ready(page)
                    expect(page.locator('#app-startup')).to_have_count(0)
                    self.assertNotIn('startup=', page.url)
                    self.assertFalse(errors, errors)
                    page.close()
            finally:
                browser.close()

    def test_first_use_opens_welcome_then_create_or_join(self):
        from playwright.sync_api import sync_playwright, expect
        from test_web_mvp import launch_browser
        with sync_playwright() as pw:
            browser = launch_browser(pw)
            try:
                page = browser.new_page()
                page.goto(self.fixture.url() + '/?startup=1')
                expect(page.locator('#app-startup')).to_be_visible()
                expect(page.locator('#shop-team-dialog[open]')).to_have_count(0)
                expect(page.locator('#shop-team-title')).to_have_text('Thanks for downloading Ez Nest', timeout=10000)
                expect(page.locator('#app-startup')).to_have_count(0)
                page.click('#tour-next')
                expect(page.get_by_role('button', name='Create a shop', exact=True)).to_be_visible()
                page.get_by_role('button', name='Use this PC for now', exact=True).click()
                self.fixture.wait_ready(page)
            finally:
                browser.close()

    def test_reduced_motion_still_waits_and_boot_failure_is_visible(self):
        from playwright.sync_api import sync_playwright, expect
        from test_web_mvp import launch_browser
        with sync_playwright() as pw:
            browser = launch_browser(pw)
            try:
                page = browser.new_page(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
                self.state_release.clear()
                page.goto(self.fixture.url() + '/?startup=1')
                page.wait_for_function("() => document.querySelector('.startup-scene img')?.src.startsWith('data:image/png')")
                before = page.locator('.startup-rider').get_attribute('style')
                page.wait_for_timeout(300)
                self.assertEqual(page.locator('.startup-rider').get_attribute('style'), before)
                page.screenshot(path=str(self.shots / 'reduced-motion.png'))
                page.wait_for_function('() => typeof token === "string" && !!token')
                page.wait_for_timeout(200)
                self.state_release.set()
                self.fixture.wait_ready(page)
                expect(page.locator('#app-startup')).to_have_count(0)
                self.state_failure = True
                page.goto(self.fixture.url() + '/?startup=1')
                expect(page.locator('#status')).to_contain_text('Request failed.', timeout=15000)
                expect(page.locator('#app-startup')).to_have_count(0)
                self.assertNotEqual(page.locator('body').get_attribute('data-ready'), '1')
            finally:
                browser.close()
