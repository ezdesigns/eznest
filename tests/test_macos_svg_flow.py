"""Actual fresh-browser acceptance helper against a scratch source server, never installed proof."""
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import test_web_mvp as web_fixture
import output_pairing
import output_gate
import macos_svg_acceptance as svg
from test_published_macos import NoRedirect


class SourceAPI:
    def __init__(self, origin):
        self.origin = origin
        self.http = build_opener(ProxyHandler({}), NoRedirect())
        _, session = self.request('/api/session')
        self.token = session['token']

    def exchange(self, path, body=None, headers=None):
        request = Request(self.origin + path, data=body, headers={
            'Origin': self.origin, 'X-EZ-Token': getattr(self, 'token', ''), **(headers or {})})
        try:
            response = self.http.open(request, timeout=90)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read(10_000_001)

    def request(self, path, body=None):
        status, raw = self.exchange(path, None if body is None else json.dumps(body).encode(),
                                    {'Content-Type':'application/json'})
        return status, json.loads(raw)


@unittest.skipUnless(sys.platform == 'darwin', 'Mac browser environment regression; no native installation')
class FreshMacSvgFlowTests(unittest.TestCase):
    setUp = web_fixture.WebMvpTests.setUp
    tearDown = web_fixture.WebMvpTests.tearDown
    start = web_fixture.WebMvpTests.start
    stop = web_fixture.WebMvpTests.stop
    url = web_fixture.WebMvpTests.url

    def test_authorized_fresh_material_svg_flow_uses_real_controls(self):
        original_get = web_fixture.server.Handler.do_GET
        def delayed_session(handler):
            # A slow bootstrap exercises the shared account entry before loading work.
            if handler.path == '/api/session':
                time.sleep(0.35)
            return original_get(handler)
        with patch.dict(os.environ, {'EZ_NEST_DEV':'0', 'EZ_NEST_OUTPUT_GATE_OPEN':'0', 'EZ_NEST_DEV_NO_OUTPUT':'0'}), \
                patch.object(svg, 'ORIGIN', self.url()), \
                patch.object(web_fixture.server.Handler, 'do_GET', delayed_session):
            api = SourceAPI(self.url())
            self.assertEqual(api.request('/api/materials')[1]['materials'], [])
            self.assertEqual(api.request('/api/solve', {})[0], 403)
            response = (200, json.dumps({'outcome': 'created', 'result': {'token': 'osa_' + 'C' * 43}}).encode())
            with patch.object(output_pairing, '_post', return_value=response), patch.object(output_gate, 'check_in'):
                self.assertEqual(api.request('/api/telemetry/output/pair', {'code': 'ABCDE-FGHJK'})[0], 200)
            self.assertTrue(api.request('/api/session')[1]['account']['ready'])
            self.assertEqual(api.request('/api/setup', {'printer': 'Synthetic', 'units': 'mm', 'thru': 'CutContour_Thru-cut', 'kiss': 'CutContour_Kiss-cut', 'hotFolder': ''})[0], 200)
            exported = svg.svg_file_flow(api, Path(self.tmp.name))
            stock = api.request('/api/materials')[1]['materials']
            self.assertEqual(len(stock), 1)
            self.assertEqual(stock[0]['profile']['preset-name'], 'CI synthetic SVG stock')
            self.assertEqual(stock[0]['profile']['unit'], 'mm')
            self.assertEqual(float(stock[0]['profile']['width']), 100)
        self.assertEqual(exported['format'], 'svg')
        self.assertTrue(exported['bytes'])
        status, sharing = api.request('/api/telemetry/output')
        self.assertEqual(status, 200)
        self.assertTrue(sharing['configured'])
        self.assertFalse(sharing['enabled'])
