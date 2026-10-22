import json
import tempfile
import unittest
from pathlib import Path
from shop_test import prepare


class ShopTrialTests(unittest.TestCase):
    def test_new_trial_uses_separate_output_and_preserves_later_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);data = root / 'Data'
            prepare(data)
            shop = json.loads((data / 'shop.json').read_text())
            self.assertEqual(Path(shop['hotFolder']), root / 'TEST Output')
            self.assertTrue(shop['setupComplete'])
            for key in ('onyxPc', 'updates', 'lan', 'outputNetwork'):
                self.assertFalse(shop[key])
            (data / 'shop.json').write_text('{"operatorChoice": true}')
            (data / 'saved-job.json').write_text('keep')
            prepare(data)
            self.assertEqual((data / 'shop.json').read_text(), '{"operatorChoice": true}')
            self.assertEqual((data / 'saved-job.json').read_text(), 'keep')

    def test_existing_unmarked_data_and_output_are_not_adopted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);data = root / 'Data';data.mkdir()
            (data / 'shop.json').write_text('protected')
            with self.assertRaisesRegex(ValueError, 'another setup'):prepare(data)
            self.assertEqual((data / 'shop.json').read_text(), 'protected')
            self.assertFalse((root / 'TEST Output').exists())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);(root / 'TEST Output').mkdir()
            with self.assertRaisesRegex(ValueError, 'already exists'):prepare(root / 'Data')
            self.assertFalse((root / 'Data').exists())
