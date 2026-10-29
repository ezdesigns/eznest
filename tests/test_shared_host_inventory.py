"""Independent HTTP clients share one authoritative host; no offline stock writes."""
import opt_out
import concurrent.futures
import json
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import server
import material_inventory
import test_material_inventory
import test_web_mvp


class SharedHostInventoryTests(unittest.TestCase):
    def setUp(self):
        self.host = test_web_mvp.WebMvpTests()
        self.host.setUp()
        self.addCleanup(self.host.tearDown)

    def post(self, path, data):
        request = Request(self.host.url() + path, data=json.dumps(data).encode(),
                          headers={'Content-Type': 'application/json', 'X-EZ-Token': server.TOKEN,
                                   'Origin': self.host.url()})
        with urlopen(request, timeout=2) as response:
            return json.load(response)

    def test_clients_retry_without_double_consumption_and_reconnect_to_same_stock(self):
        self.post('/api/materials/save', {'id': 'shared-roll', 'profile': test_material_inventory.values(), 'revision': 0})
        # A validated host-owned layout. Clients cannot supply its length or roll.
        with server.LOCK:
            server.STATE.update(status='ready', id='job-one', job={'inventoryMaterialId': 'shared-roll'},
                                result={'usedLength': 600, 'width': 500}, manifest={'productionReady': True})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as clients:
            replies = list(clients.map(lambda _: self.post('/api/materials/reserve', {'id': 'job-one', 'length': 1}), range(2)))
        for reply in replies:
            self.assertEqual(reply['materials'][0]['reservedMm'], 600)
            self.assertEqual(reply['materials'][0]['onHandMm'], 1000)
        with server.LOCK:
            server.STATE['id'] = 'job-two'
        with self.assertRaises(HTTPError):
            self.post('/api/materials/reserve', {'id': 'job-two'})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as clients:
            list(clients.map(lambda _: self.post('/api/materials/transition', {'id': 'job-one', 'action': 'use'}), range(2)))
        state = material_inventory.read(server.WORK)
        self.assertEqual(state['materials'][0]['onHandMm'], 400)
        self.assertEqual(state['materials'][0]['reservedMm'], 0)
        with self.assertRaises(HTTPError):
            self.post('/api/materials/save', {'id': 'shared-roll', 'profile': test_material_inventory.values(), 'revision': 1})
        old_url = self.host.url()
        self.host.stop()
        request = Request(old_url + '/api/materials/transition', data=b'{"id":"job-one","action":"use"}',
                          headers={'Content-Type': 'application/json', 'X-EZ-Token': server.TOKEN})
        with self.assertRaises((URLError, OSError)):
            urlopen(request, timeout=.2)
        self.assertEqual(material_inventory.read(server.WORK), state)
        self.host.start()
        recovered = self.post('/api/materials/transition', {'id': 'job-one', 'action': 'use'})
        self.assertEqual(recovered['materials'][0]['onHandMm'], 400)
        self.assertEqual(recovered['reservations'][0]['status'], 'used')
