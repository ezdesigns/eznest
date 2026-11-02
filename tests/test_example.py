"""The shipped example loads complete mixed kits and resets only its own jobs."""
import opt_out
import unittest
from pathlib import Path

import server
import test_web_mvp


class ExampleTests(unittest.TestCase):
    def test_mixed_example_reload_nest_and_artwork_roundtrip(self):
        from playwright.sync_api import sync_playwright
        fixture = test_web_mvp.WebMvpTests()
        fixture.setUp()
        try:
            with sync_playwright() as playwright:
                browser = test_web_mvp.launch_browser(playwright)
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.goto(fixture.url())
                    page.wait_for_function("() => token.length > 0")
                    page.set_input_files('#files', str(Path(__file__).parents[1] / 'sample-artwork.svg'))
                    page.wait_for_function("() => queue.length === 1 && queue[0].status === 'ready'")
                    original = page.evaluate("() => { queue[0].sets=3; return JSON.parse(JSON.stringify(queue[0])); }")
                    for iteration in range(2):
                        page.click('#settings-open')
                        page.click('#demo')
                        page.wait_for_function("() => queue.length === 4 && queue.every(j => j.status === 'ready') && queue.filter(j => j.selected).length === 3 && queue.find(j => j.id === 'demo-trail').sets === 4 && queue.find(j => j.id === 'demo-helmet').sets === 2 && queue.find(j => j.id === 'demo-sticker').sets === 100")
                        self.assertEqual(page.evaluate("() => queue.filter(j => j.selected).map(j => [j.data.parts.length,j.sets,j.role])"),
                                         [[4, 4, 'required'], [6, 2, 'required'], [1, 100, 'fill']])
                        retained = page.evaluate("() => JSON.parse(JSON.stringify(queue[0]))")
                        self.assertFalse(retained.pop('selected'))
                        original.pop('selected', None)
                        self.assertEqual(retained, original)
                        if iteration == 0:
                            page.evaluate("() => { for(const e of queue.slice(1)){e.sets=7;e.role='fill';} }")
                    page.click('#nest')
                    page.wait_for_function("() => !busy && current?.result?.validated === true", timeout=90000)
                    self.assertEqual(server.STATE['status'], 'ready')
                    self.assertTrue(server.STATE['manifest']['complete'])
                    required = [j for j in server.STATE['manifest']['jobs'] if j['role'] != 'fill']
                    self.assertEqual([j['expected'] for j in required], [16, 12])
                    self.assertEqual([j['placed'] for j in required], [16, 12])
                    count = len(server.STATE['result']['placements'])
                    self.assertGreaterEqual(count, 28)
                    self.assertEqual(page.evaluate("() => { const text=EZNSVG.serialize(artworkSVG(current)); EZNSVG.sanitize(text); return EZNSVG.importSVG(text,'Example round trip').parts.length; }"), count)
                finally:
                    browser.close()
        finally:
            fixture.tearDown()
