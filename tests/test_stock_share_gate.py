import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class StockShareGateTest(unittest.TestCase):
    """EZ39-9: the share toggle stays off until OUTPUT can receive stock summaries."""

    def test_toggle_disabled_in_markup(self):
        html = (ROOT / 'web.html').read_text(encoding='utf-8')
        self.assertRegex(html, r'<input id="share-stock-summary" type="checkbox" disabled>')

    def test_client_flag_off_and_gates_toggle(self):
        js = (ROOT / 'web.js').read_text(encoding='utf-8')
        self.assertIn('const STOCK_SHARE_ENDPOINT_READY = false;', js)
        self.assertIn('shareStock.disabled = !hostComputer || !STOCK_SHARE_ENDPOINT_READY;', js)
        self.assertRegex(js, r'shareStockSummary: STOCK_SHARE_ENDPOINT_READY &&')


if __name__ == '__main__':
    unittest.main()
