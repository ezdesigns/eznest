"""Actual fresh-browser acceptance helper against a scratch source server, never installed proof."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import test_web_mvp as web_fixture
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

    def test_unpaired_fresh_material_svg_flow_uses_real_controls(self):
        api = SourceAPI(self.url())
        with patch.dict(os.environ, {'EZ_NEST_DEV':'0', 'EZ_NEST_OUTPUT_GATE_OPEN':'0', 'EZ_NEST_DEV_NO_OUTPUT':'0'}), \
                patch.object(svg, 'ORIGIN', self.url()):
            exported = svg.svg_file_flow(api, Path(self.tmp.name))
        self.assertEqual(exported['format'], 'svg')
        self.assertTrue(exported['bytes'])
        status, sharing = api.request('/api/telemetry/output')
        self.assertEqual(status, 200)
        self.assertFalse(sharing['configured'])
        self.assertFalse(sharing['enabled'])
