import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class StockShareGateTest(unittest.TestCase):
    """EZ39-9: the share toggle stays off until OUTPUT can receive stock summaries."""

    def test_toggle_disabled_in_markup(self):
        html = (ROOT / 'web.html').read_text(encoding='utf-8')
        self.assertRegex(html, r'<details id="settings-stock-share" class="settings-section" hidden>')
        self.assertRegex(html, r'<input id="share-stock-summary" type="checkbox" disabled>')
        self.assertNotRegex(html, r'<input id="show-roll-names" type="checkbox" checked>')

    def test_client_flag_off_and_gates_toggle(self):
        js = (ROOT / 'web.js').read_text(encoding='utf-8')
        self.assertIn('const STOCK_SHARE_ENDPOINT_READY = false;', js)
        self.assertIn('shareStock.disabled = !hostComputer || !STOCK_SHARE_ENDPOINT_READY;', js)
        self.assertIn('stockShare.hidden = !STOCK_SHARE_ENDPOINT_READY;', js)
        self.assertRegex(js, r'shareStockSummary: STOCK_SHARE_ENDPOINT_READY &&')
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn('import output_remote', server)
        self.assertIn("data.get('shareStockSummary') is True and not output_remote.READY", server)
        self.assertIn('READY = False', (ROOT / 'output_remote.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
