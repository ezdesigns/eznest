"""The shipped artwork can still be nested through an old Pro bookmark."""
import opt_out
import unittest
from pathlib import Path
import server
import test_web_mvp


class ExampleTests(unittest.TestCase):
    def test_legacy_bookmark_nests_shipped_artwork_with_requested_copies(self):
        from playwright.sync_api import sync_playwright, expect
        fixture = test_web_mvp.WebMvpTests()
        fixture.setUp()
        try:
            with sync_playwright() as playwright:
                browser, page = fixture.open_page(playwright)
                try:
                    page.goto(fixture.url() + '/?view=full')
                    fixture.wait_ready(page)
                    expect(page.locator('#mode-switch')).to_have_count(0)
                    page.set_input_files('#file', str(Path(__file__).parents[1] / 'sample-artwork.svg'))
                    page.wait_for_function("() => !importing && kits.length === 1")
                    original = page.evaluate("kits[0].data.parts.reduce((n,p)=>n+(p.quantity||1),0)")
                    page.locator('#files input').fill('3')
                    fixture.start_nesting(page)
                    page.wait_for_function("() => /cuts ok/i.test(document.querySelector('#gate')?.textContent || '')", timeout=90000)
                    self.assertEqual(server.STATE['status'], 'ready')
                    self.assertTrue(server.STATE['result']['validated'])
                    self.assertEqual(len(server.STATE['result']['placements']), original * 3)
                    expect(page.get_by_role('button', name='Review and save', exact=True)).to_be_enabled()
                finally:
                    browser.close()
        finally:
            fixture.tearDown()
