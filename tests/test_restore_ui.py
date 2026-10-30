import re
"""Header OUTPUT link, Inventory dialog, and the Step 3 look. Fake OUTPUT only."""
import opt_out
import json
import os
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import material_inventory
import output_gate
import output_pairing
import server
import test_web_mvp
from test_web_mvp import launch_browser
from test_mixed_cuts import mixed_fixture

SHOTS = Path(os.environ.get('EZ_NEST_SHOTS') or Path(__file__).resolve().parents[1] / '.local' / 'screenshots')
SHOTS.mkdir(parents=True, exist_ok=True)
GATE_ENV = ('EZ_NEST_DEV', 'EZ_NEST_OUTPUT_GATE_OPEN', 'EZ_NEST_OUTPUT_UPLOADS')
CODE = 'ABCDE-FGHJK'


class FakeOutput:
    """Stands in for OUTPUT. Pairing mints a token; check-in accepts live tokens."""
    def __init__(self):
        self.live, self.checkins, self.offline = set(), 0, False

    def pair(self, raw):
        token = 'osa_' + secrets.token_urlsafe(40)[:43].ljust(43, 'A')
        self.live.add(token)
        return 200, json.dumps({'outcome': 'ok', 'result': {'token': token, 'outpostId': 'test-outpost'}}).encode()

    def check_in(self, raw, token):
        self.checkins += 1
        if self.offline:
            raise output_gate.Offline
        if token not in self.live:
            return 401, b'{"error":{"code":"unpaired"}}'
        return 200, b'{"outcome":"ok","result":{"paired":true}}'


def without_gate_env():
    return patch.dict(os.environ, {k: v for k, v in os.environ.items() if k not in GATE_ENV}, clear=True)


def roll(name, width='51.5', roll_width='54', left='', **extra):
    values = {key: '' for key in material_inventory.FIELDS}
    values.update({'preset-name': name, 'unit': 'in', 'width': width, 'roll': roll_width, 'gap': '0.125', 'margin': '0',
                   'mark-margin': '0.4', 'rotations': '0,90,180,270', 'print-layout': 'sections', 'auto-bleed': '0',
                   'sheet': '60', 'available-length': left})
    values.update(extra)
    return values


class LinkStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.fake = FakeOutput()

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self):
        with without_gate_env():
            return output_pairing.connect(self.dir, CODE, transport=self.fake.pair, host='Shop PC',
                                          check_in_transport=self.fake.check_in)

    def test_fresh_install_is_unpaired_and_points_at_outpost(self):
        with without_gate_env():
            view = output_gate.link_status(self.dir, True)
            self.assertFalse(output_gate.link_status(self.dir, False)['canPair'])
        self.assertEqual(view['state'], 'unpaired')
        self.assertTrue(view['canPair'])
        self.assertTrue(view['connectUrl'].endswith('/outpost/ez-nest'))

    def test_pairing_checks_in_at_once_so_output_sees_this_computer(self):
        # OUTPUT marks a computer as seen on check-in, not on pairing.
        self.connect()
        self.assertEqual(self.fake.checkins, 1)
        with without_gate_env():
            view = output_gate.link_status(self.dir, True)
        self.assertEqual(view['state'], 'connected')
        self.assertLess(view['secondsSinceCheckIn'], 60)

    def test_pairing_survives_an_offline_check_in(self):
        self.fake.offline = True
        self.connect()
        with without_gate_env():
            view = output_gate.link_status(self.dir, True)
        self.assertIn(view['state'], ('connected', 'stale'))
        self.assertEqual(self.fake.checkins, 1)

    def test_disconnect_then_new_code_pairs_again(self):
        self.connect()
        with without_gate_env():
            output_pairing.disconnect(self.dir)
            self.assertEqual(output_gate.link_status(self.dir, True)['state'], 'unpaired')
        self.connect()
        self.assertEqual(self.fake.checkins, 2)
        with without_gate_env():
            self.assertEqual(output_gate.link_status(self.dir, True)['state'], 'connected')

    def test_reconnect_while_paired_replaces_the_credential(self):
        self.connect()
        self.connect()
        with without_gate_env():
            self.assertEqual(output_gate.link_status(self.dir, True)['state'], 'connected')

    def test_a_day_without_check_in_is_stale(self):
        self.connect()
        later = output_gate._stamp(None) + output_gate.SEEN_RECENTLY + 60
        with without_gate_env():
            self.assertEqual(output_gate.link_status(self.dir, True, now=later)['state'], 'stale')

    def test_injected_pairing_transport_never_checks_in_on_its_own(self):
        with without_gate_env(), patch.object(output_gate, '_post', side_effect=AssertionError('no request expected')):
            output_pairing.connect(self.dir, CODE, transport=self.fake.pair, host='Shop PC')


class MaterialRemoveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_inventory_is_empty_and_remove_deletes_one_roll(self):
        self.assertEqual(material_inventory.read(self.dir)['materials'], [])
        material_inventory.save(self.dir, 'gloss', roll('Gloss vinyl', left='600'), 0)
        material_inventory.save(self.dir, 'matte', roll('Matte vinyl'), 0)
        with self.assertRaises(ValueError):
            material_inventory.remove(self.dir, 'gloss', 0)
        left = material_inventory.remove(self.dir, 'gloss', 1)['materials']
        self.assertEqual([item['id'] for item in left], ['matte'])


class RestoreUiTests(unittest.TestCase):
    setUp = test_web_mvp.WebMvpTests.setUp
    start = test_web_mvp.WebMvpTests.start
    stop = test_web_mvp.WebMvpTests.stop
    tearDown = test_web_mvp.WebMvpTests.tearDown
    url = test_web_mvp.WebMvpTests.url
    wait_ready = test_web_mvp.WebMvpTests.wait_ready
    start_nesting = test_web_mvp.WebMvpTests.start_nesting

    def page(self, playwright, width=1280):
        browser = launch_browser(playwright)
        context = browser.new_context(viewport={'width': width, 'height': 900 if width > 600 else 844})
        # Nothing leaves the box: outside requests get a local stub page.
        local = self.url()
        context.route(lambda url: not url.startswith(local),
                      lambda route: route.fulfill(status=200, content_type='text/html', body='<p>stub</p>'))
        page = context.new_page()
        page.goto(local + '/web', wait_until='domcontentloaded')
        self.wait_ready(page)
        return browser, context, page

    def final(self, page, name, width):
        target = os.environ.get('EZ_NEST_FINAL_SHOTS')
        if target:
            Path(target).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(target) / f'{name}-{width}-final.png'), full_page=True)

    def shot(self, page, name):
        page.screenshot(path=str(SHOTS / name))

    def fresh(self):
        self.stop()
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        server.WORK = Path(self.tmp.name)
        server.OUTPUT = server.OutputFolder(server.WORK / 'output-folder.json')
        server.STATE.clear()
        server.STATE.update(status='idle')
        self.start()

    def test_step_three_colors_and_badge_are_locked(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser, _context, page = self.page(playwright)
            try:
                page.set_input_files('#file', {'name': 'order.pdf', 'mimeType': 'application/pdf', 'buffer': mixed_fixture()})
                page.wait_for_function('() => !importing && kits.length === 1', timeout=15000)
                page.locator('#max-output').scroll_into_view_if_needed()
                look = page.evaluate('''() => {
                  const s = id => getComputedStyle(document.getElementById(id));
                  const badge = document.querySelector('#max-output .paid-badge');
                  return {inHouse: s('in-house').backgroundColor, maxOutput: s('max-output').backgroundColor,
                          badge: badge.textContent.trim(), badgeColor: getComputedStyle(badge).backgroundColor,
                          rotated: getComputedStyle(badge).transform !== 'none',
                          check: getComputedStyle(document.getElementById('in-house'), '::before').content,
                          effortBelow: document.getElementById('nesting-effort').getBoundingClientRect().top
                                       >= document.getElementById('max-output').getBoundingClientRect().bottom - 1};
                }''')
                self.assertEqual(look['maxOutput'], 'rgb(243, 251, 246)')
                self.assertEqual(look['badge'], 'Still get paid 🤑')
                self.assertTrue(look['rotated'])
                self.assertTrue(look['effortBelow'])
                rgb = [int(v) for v in look['inHouse'].split('(')[1].split(')')[0].split(',')[:3]]
                self.assertEqual(look['inHouse'], 'rgb(239, 245, 255)')
                green = [int(v) for v in look['badgeColor'].split('(')[1].split(')')[0].split(',')[:3]]
                self.assertEqual(look['badgeColor'], 'rgb(21, 128, 61)')
                self.shot(page, 'after-step3-1280.png')
                self.assertEqual(page.locator('#max-output').get_attribute('aria-label'), "Don't print. Still get paid. Learn about OUTPUT")
                self.assertNotIn('sandbox', page.locator('.job-panel').inner_text().lower())
                page.click('#max-output')
                dialog = page.locator('#max-output-dialog')
                self.assertEqual(page.locator('#max-output-title').inner_text(), "Don't print")
                text = dialog.inner_text()
                self.assertIn('OUTPUT routes the job to the best-fit print shop near you', text)
                self.assertIn('You still get paid.', text)
                self.assertNotIn('sandbox', text.lower())
                self.shot(page, 'after-step3-dialog-1280.png')
            finally:
                browser.close()

    def test_shop_owner_walkthrough_inventory_and_output_link(self):
        from playwright.sync_api import sync_playwright, expect
        fake = FakeOutput()
        rolls = [['gloss-54', roll('Gloss vinyl 54"', left='1200', **{'roll-length': '1800', 'roll-cost': '180', 'low-stock': '120'})],
                 ['matte-30', roll('Matte vinyl 30"', width='29', roll_width='30', left='60', **{'roll-length': '600', 'low-stock': '120'})],
                 ['clear-54', roll('Clear laminate 54"')]]
        with without_gate_env(), patch.object(output_pairing, '_post', fake.pair), \
                patch.object(output_gate, '_post', lambda directory, raw, token: fake.check_in(raw, token)), \
                sync_playwright() as playwright:
            for width in (1280, 390):
                if width == 390:
                    self.fresh()
                browser, context, page = self.page(playwright, width)
                try:
                    self.walk(page, context, width, rolls, fake, expect)
                finally:
                    browser.close()

    def walk(self, page, context, width, rolls, fake, expect):
        expect(page.locator('#output-link-connect')).to_have_text('Connect to OUTPUT')
        expect(page.locator('#stock-open')).to_be_visible()
        box = page.locator('#stock-open').bounding_box()
        gear = page.locator('#settings-open').bounding_box()
        self.assertLess(abs(box['y'] - gear['y']), 4)
        self.assertLess(box['x'], gear['x'])
        self.assertEqual((round(box['height']), round(box['y'])), (round(gear['height']), round(gear['y'])))
        if width < 600:
            self.assertEqual(round(box['width']), round(gear['width']))
        expect(page.locator('#setup')).to_be_hidden()
        expect(page.locator('#cut-line-note')).to_be_hidden()
        expect(page.locator('#cut-line-names')).to_have_text('Thru-cut, Kiss-cut')
        self.assertEqual((round(box['height']), round(gear['height'])), (36, 36))
        expect(page.locator('#start-nesting')).to_be_visible()
        expect(page.locator('#start-over-idle')).to_be_visible()
        expect(page.locator('#start-over-idle')).to_be_disabled()
        self.assertEqual(round(page.locator('#start-over-idle').bounding_box()['height']), round(page.locator('#start-nesting').bounding_box()['height']))
        self.assertEqual(round(page.locator('#output-dot').bounding_box()['height']), 36)
        expect(page.locator('#output-dot')).to_have_attribute('title', 'Connect to OUTPUT')
        # Unpaired: one plain message, nesting waits until OUTPUT is connected.
        expect(page.locator('#output-required')).to_be_visible()
        expect(page.locator('#output-required-title')).to_have_text('Connect to OUTPUT to start nesting')
        self.final(page, 'not-connected', width)
        with context.expect_page() as tab:
            page.click('#output-required-connect')
        self.assertTrue(tab.value.url.endswith('/outpost/ez-nest'), tab.value.url)
        tab.value.close()
        expect(page.locator('#output-link-code')).to_be_visible()
        self.shot(page, f'after-connect-code-{width}.png')
        page.fill('#output-link-code', CODE)
        with page.expect_navigation():
            page.click('#output-link-submit')
        self.wait_ready(page)
        expect(page.locator('#output-required')).to_be_hidden()
        expect(page.locator('#output-dot')).to_have_class(re.compile('connected'))
        expect(page.locator('#output-link-label')).to_contain_text('Connected')
        self.assertGreaterEqual(fake.checkins, 1, (page.locator('#output-link').inner_text(), len(fake.live), output_gate.link_status(server.WORK, True), os.environ.get('EZ_NEST_DEV'), output_gate._token(server.WORK)[1]))
        self.shot(page, f'after-connected-{width}.png')
        self.final(page, 'connected', width)
        page.wait_for_function("() => fetch('/api/shop').then(r => r.json()).then(s => s.setupComplete === true)")
        self.shot(page, f'after-main-{width}.png')
        self.final(page, 'main-empty', width)
        page.click('#settings-open')
        page.locator('summary', has_text='Cutter setup').click()
        self.final(page, 'settings-cutter', width)
        page.keyboard.press('Escape')
        page.reload()
        page.wait_for_function("() => fetch('/api/shop').then(r => r.json()).then(s => s.setupComplete === true)")
        page.click('#stock-open')
        expect(page.locator('#stock-empty')).to_have_text('No materials yet. Add your first roll.')
        self.shot(page, f'after-inventory-empty-{width}.png')
        self.final(page, 'inventory-empty', width)
        page.click('#stock-close')
        page.evaluate('''async rolls => { for (const [id, p] of rolls) await api('/api/materials/save', {id, profile: p, revision: 0}); await refreshInventory(); }''', rolls)
        page.set_input_files('#file', {'name': 'order.pdf', 'mimeType': 'application/pdf', 'buffer': mixed_fixture()})
        page.wait_for_function('() => !importing && kits.length === 1', timeout=15000)
        page.locator('#files input').first.fill('200')
        self.final(page, 'main-with-file', width)
        self.assertEqual(page.locator('button:visible', has_text='Start over').count(), 1)
        self.start_nesting(page)
        page.wait_for_function("() => ['check','blocked'].includes(document.body.dataset.step)", timeout=90000)
        page.click('#stock-open')
        expect(page.locator('.stock-row')).to_have_count(3)
        expect(page.locator('#stock-job')).to_be_visible()
        gloss = page.locator('.stock-row[data-id="gloss-54"]')
        expect(gloss).to_contain_text('Enough for this job')
        expect(gloss).to_contain_text('per sq ft')
        matte = page.locator('.stock-row[data-id="matte-30"]')
        expect(matte.locator('.stock-low')).to_be_visible()
        expect(matte).to_contain_text('Too narrow')
        clear = page.locator('.stock-row[data-id="clear-54"]')
        expect(clear).to_contain_text('Length left unknown')
        expect(clear).not_to_contain_text('per sq ft')
        expect(page.locator('#stock')).not_to_contain_text('Reserved')
        self.shot(page, f'after-inventory-crosscheck-{width}.png')
        self.final(page, 'inventory-job-check', width)
        clear.locator('button', has_text='Update count').click()
        clear.locator('.stock-count input').fill('900')
        clear.locator('.stock-count button[type=submit]').click()
        expect(clear).to_contain_text('75')
        page.once('dialog', lambda d: d.accept())
        matte.locator('button', has_text='Remove').click()
        expect(page.locator('.stock-row')).to_have_count(2)
        self.assertEqual(page.locator('#material option[value="matte-30"]').count(), 0)
        page.click('#stock-close')
        page.click('#output-dot')
        expect(page.locator('#output-link-menu')).to_be_visible()
        self.shot(page, f'after-connected-menu-{width}.png')
        self.final(page, 'connected-menu', width)
        page.keyboard.press('Escape')
        token, _ = output_gate._token(server.WORK)
        state = output_gate._read_state(server.WORK)
        output_gate._write_signed(server.WORK, token, last_ok=state['lastOkAt'] - 2 * 86400, attempt=state['lastAttemptAt'], reason='')
        page.evaluate('refreshOutputLink()')
        expect(page.locator('#output-link-label')).to_contain_text('Last seen 2 days ago')
        self.shot(page, f'after-stale-{width}.png')
        page.click('#output-dot')
        page.click('#output-link-check')
        expect(page.locator('#output-dot')).to_have_class(re.compile('connected'))
        expect(page.locator('#output-link-label')).to_contain_text('Connected')
        expect(page.locator('#output-link-detail')).to_contain_text('Last check-in just now')
        page.once('dialog', lambda d: d.accept())
        page.click('#output-link-disconnect')
        expect(page.locator('#output-dot')).not_to_have_class(re.compile('connected'))
        with context.expect_page() as tab:
            page.click('#output-dot')
        tab.value.close()
        page.fill('#output-link-code', CODE)
        page.click('#output-link-submit')
        expect(page.locator('#output-dot')).to_have_class(re.compile('connected'))
        expect(page.locator('#output-link-label')).to_contain_text('Connected')


if __name__ == '__main__':
    unittest.main()
