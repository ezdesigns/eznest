"""Inventory names and numbers: same-looking names are one name, numbers follow the browser's rule."""
import json
import tempfile
import unittest
from pathlib import Path

import material_inventory as inventory


def values(stock='1000', name='Test roll'):
    return {'preset-name': name, 'unit': 'mm', 'width': '500', 'roll': '510',
            'available-length': stock, 'roll-length': '5000', 'gap': '2', 'margin': '5',
            'mark-margin': '0', 'sheet': '1000', 'rotations': '0,90,180,270', 'auto-bleed': '0',
            'bleed': '0', 'cost': '', 'roll-cost': '', 'low-stock': '200', 'print-layout': 'sections'}


class NameAndNumberTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        inventory.save(self.root, 'roll', values(), 0)

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, state):
        return {m['id']: m['profile']['preset-name'] for m in state['materials']}

    def test_names_that_only_look_different_are_the_same_name(self):
        for twin in ('test  roll', 'TEST ROLL', 'Test\u200b roll', 'Test roll\u202e', '\uff34est roll', ' Test\troll ', '\u00a0Test roll'):
            with self.assertRaisesRegex(ValueError, 'already exists', msg=repr(twin)):
                inventory.save(self.root, 'twin', values(name=twin), 0)
        state = inventory.save(self.root, 'other', values(name='  Gloss\u2066  vinyl\u200d '), 0)
        self.assertEqual(self.names(state)['other'], 'Gloss vinyl')

    def test_look_alike_letters_count_as_the_same_name(self):
        for twin in ('T\u0435st roll', '\u03a4est roll', 'Test r\u043ell'):
            with self.assertRaisesRegex(ValueError, 'already exists', msg=repr(twin)):
                inventory.save(self.root, 'twin', values(name=twin), 0)
        inventory.save(self.root, 'ink', values(name='\u0131nk'), 0)
        for twin in ('ink', '\u0130NK', 'INK'):
            with self.assertRaisesRegex(ValueError, 'already exists', msg=repr(twin)):
                inventory.save(self.root, 'ink2', values(name=twin), 0)
        inventory.save(self.root, 'street', values(name='Stra\u00dfe'), 0)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            inventory.save(self.root, 'street2', values(name='STRASSE'), 0)
        # The name people see stays as typed.
        self.assertEqual(self.names(inventory.save(self.root, 'ink', values(name='\u0131nk'), 1))['ink'], '\u0131nk')

    def test_old_look_alike_duplicates_can_still_be_edited_and_renamed(self):
        # Two rolls saved before the check existed, written straight to the database.
        with inventory.database(self.root) as db:
            row = dict(db.execute('SELECT * FROM materials WHERE id=?', ('roll',)).fetchone())
            row.update(id='legacy', profile=json.dumps({**json.loads(row['profile']), 'preset-name': 'test  roll'}))
            db.execute(f"INSERT INTO materials ({','.join(row)}) VALUES ({','.join('?' * len(row))})", list(row.values()))
        revision = row['revision']
        edited = inventory.save(self.root, 'legacy', values('900', 'test  roll'), revision)
        legacy = next(m for m in edited['materials'] if m['id'] == 'legacy')
        self.assertEqual(legacy['onHandMm'], 900)
        renamed = inventory.save(self.root, 'legacy', values('900', 'Test roll B'), legacy['revision'])
        self.assertEqual(self.names(renamed)['legacy'], 'Test roll B')
        again = next(m for m in renamed['materials'] if m['id'] == 'legacy')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            inventory.save(self.root, 'legacy', values('900', 'TEST ROLL'), again['revision'])

    def test_server_numbers_match_the_browser(self):
        for bad in ('\u0661\u0665\u0660', '\uff11\uff15\uff10', '1_000', '1e5', 'inf', 'nan', '0x10', '-1', '', True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                inventory.number(bad, 'roll-cost')
        for good, expected in (('150', 150), ('8.50', 8.5), ('.5', .5), ('150.', 150), (' 12 ', 12), (3, 3), (2.5, 2.5)):
            self.assertEqual(inventory.number(good, 'roll-cost'), expected)

    def test_number_errors_use_plain_names(self):
        with self.assertRaisesRegex(ValueError, r'^Roll price looks wrong\. Enter a number like 8\.50\.$'):
            inventory.save(self.root, 'roll', {**values(), 'roll-cost': '1e309'}, 1)
        with self.assertRaisesRegex(ValueError, r'^Length left on roll looks wrong'):
            inventory.save(self.root, 'roll', {**values(), 'available-length': '-1'}, 1)


if __name__ == '__main__':
    unittest.main()
