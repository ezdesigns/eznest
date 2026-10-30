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
        page.wait_for_function("() => fetch('/api/shop').then(r => r.json()).then(s => s.setupComplete === true)")
        self.shot(page, f'after-main-{width}.png')
        self.final(page, 'main-empty', width)
        self.final(page, 'not-connected', width)
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
        expect(page.locator('.stock-slot')).to_have_count(3)
        expect(page.locator('#stock-job')).to_be_visible()
        gloss = page.locator('.stock-slot[data-id="gloss-54"]')
        expect(gloss).to_have_attribute('aria-label', re.compile('Enough for this job'))
        gloss.click()
        expect(page.locator('#stock-panel')).to_contain_text('Enough for this job')
        expect(page.locator('#stock-panel')).to_contain_text('per sq ft')
        matte = page.locator('.stock-slot[data-id="matte-30"]')
        expect(matte).to_have_class(re.compile('low'))
        matte.click()
        expect(page.locator('#stock-panel .stock-low')).to_be_visible()
        expect(page.locator('#stock-panel')).to_contain_text('Too narrow')
        clear = page.locator('.stock-slot[data-id="clear-54"]')
        clear.click()
        expect(page.locator('#stock-panel')).to_contain_text('Length left unknown')
        expect(page.locator('#stock-panel')).not_to_contain_text('per sq ft')
        expect(page.locator('#stock')).not_to_contain_text('Reserved')
        self.shot(page, f'after-inventory-crosscheck-{width}.png')
        self.final(page, 'inventory-job-check', width)
        page.click('#stock-panel .stock-len')
        expect(page.locator('#roll-f-left')).to_be_focused()
        page.fill('#roll-f-left', '75')
        page.click('#stock-panel button[type=submit]')
        expect(clear).to_contain_text('75 ft')
        matte.click()
        page.click('#stock-panel button:has-text("Edit")')
        page.once('dialog', lambda d: d.accept())
        page.click('#stock-panel .roll-remove')
        expect(page.locator('.stock-slot')).to_have_count(2)
        self.assertEqual(page.locator('#material option[value="matte-30"]').count(), 0)
        page.click('#stock-close')
        with context.expect_page() as tab:
            page.click('#output-dot')
        self.assertTrue(tab.value.url.endswith('/outpost/ez-nest'), tab.value.url)
        tab.value.close()
        expect(page.locator('#output-link-code')).to_be_visible()
        self.shot(page, f'after-connect-code-{width}.png')
        page.fill('#output-link-code', CODE)
        page.click('#output-link-submit')
        expect(page.locator('#output-dot')).to_have_class(re.compile('connected'))
        expect(page.locator('#output-link-label')).to_contain_text('Connected')
        self.assertGreaterEqual(fake.checkins, 1, (page.locator('#output-link').inner_text(), len(fake.live), output_gate.link_status(server.WORK, True), os.environ.get('EZ_NEST_DEV'), output_gate._token(server.WORK)[1]))
        self.shot(page, f'after-connected-{width}.png')
        self.final(page, 'connected', width)
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


class InventoryShelfTests(unittest.TestCase):
    """Inventory shelf: rolls drawn upright, tap for details, add a roll with a live drawing."""
    setUp = test_web_mvp.WebMvpTests.setUp
    start = test_web_mvp.WebMvpTests.start
    stop = test_web_mvp.WebMvpTests.stop
    tearDown = test_web_mvp.WebMvpTests.tearDown
    url = test_web_mvp.WebMvpTests.url
    wait_ready = test_web_mvp.WebMvpTests.wait_ready
    page = RestoreUiTests.page
    fresh = RestoreUiTests.fresh

    def snap(self, page, name, width):
        target = os.environ.get('EZ_NEST_SHELF_SHOTS')
        if target:
            Path(target).mkdir(parents=True, exist_ok=True)
            page.locator('#stock').screenshot(path=str(Path(target) / f'after-{name}-{width}.png'))

    def save_rolls(self, page, rolls):
        page.evaluate('''async rolls => { for (const [id, p] of rolls) await api('/api/materials/save', {id, profile: p, revision: 0}); await refreshInventory(); }''', rolls)

    def test_shelf_add_flow_detail_and_keyboard(self):
        from playwright.sync_api import sync_playwright, expect
        names = ['Gloss vinyl', 'Matte vinyl', 'Clear laminate', 'Window film', 'Magnet', 'Paper', 'Chrome', 'Holographic',
                 'Canvas', 'Banner', 'Reflective', 'Wall decal']
        many = [[f'roll-{i}', roll(f'{n} 54 in', left=str(1800 - i * 140) if i != 4 else '', **{'roll-length': '1800', 'roll-cost': '200' if i % 3 == 0 else ''})]
                for i, n in enumerate(names)]
        with without_gate_env(), sync_playwright() as playwright:
            for width in (1280, 390):
                if width == 390:
                    self.fresh()
                browser, context, page = self.page(playwright, width)
                violations = []
                page.on('console', lambda m: violations.append(m.text) if 'Content Security Policy' in m.text else None)
                try:
                    page.wait_for_function("() => fetch('/api/shop').then(r => r.json()).then(s => s.setupComplete === true)")
                    page.click('#stock-open')
                    expect(page.locator('#stock-empty')).to_be_visible()
                    self.snap(page, 'empty', width)
                    page.click('#stock-add')
                    expect(page.locator('#roll-f-name')).to_be_focused()
                    page.click('#stock-panel button[type=submit]')
                    expect(page.locator('#roll-f-name')).to_have_attribute('aria-invalid', 'true')
                    expect(page.locator('#roll-f-name')).to_be_focused()
                    expect(page.locator('#stock-panel')).to_contain_text('Enter a material name.')
                    page.locator('#roll-f-name').press_sequentially('Gloss vinyl')
                    page.locator('#roll-f-roll').press_sequentially('54')
                    expect(page.locator('#roll-f-width')).to_have_value('54')
                    page.fill('#roll-f-width', '51.5')
                    page.locator('#roll-f-left').press_sequentially('40')
                    thin = page.evaluate("() => document.querySelector('#roll-preview-svg .roll-body path').getBBox().width")
                    page.fill('#roll-f-left', '')
                    page.locator('#roll-f-left').press_sequentially('1800 in')
                    thick = page.evaluate("() => document.querySelector('#roll-preview-svg .roll-body path').getBBox().width")
                    self.assertGreater(thick, thin)
                    expect(page.locator('#roll-preview-cap')).to_contain_text('150 ft')
                    expect(page.locator('.stock-slot.draft')).to_contain_text('150 ft')
                    expect(page.locator('#roll-f-left + [data-len-unit]')).to_have_text('in')
                    expect(page.locator('#roll-f-full + [data-len-unit]')).to_have_text('in')
                    self.snap(page, 'add-typing', width)
                    page.click('.roll-units button[data-unit="in"]')
                    expect(page.locator('#roll-f-left')).to_have_value('1800')
                    page.click('.roll-units button[data-unit="ft"]')
                    expect(page.locator('#roll-f-left')).to_have_value('150')
                    page.fill('#roll-f-cost', '180')
                    expect(page.locator('#roll-f-cost-hint')).to_contain_text('per sq ft')
                    page.click('#stock-panel button:has-text("Save and add another")')
                    expect(page.locator('#roll-f-name')).to_be_focused()
                    page.fill('#roll-f-name', 'Gloss vinyl')
                    page.fill('#roll-f-roll', '30')
                    page.click('#stock-panel button[type=submit]')
                    expect(page.locator('#stock-panel')).to_contain_text('already exists')
                    page.fill('#roll-f-name', 'Matte vinyl 30 in')
                    page.fill('#roll-f-left', '6')
                    page.fill('#roll-f-full', '100')
                    page.keyboard.press('Enter')
                    expect(page.locator('.stock-slot')).to_have_count(2)
                    page.wait_for_function("() => shopInventory.materials.some(m => m.profile['preset-name'] === 'Gloss vinyl')")
                    saved = page.evaluate("() => shopInventory.materials.find(m => m.profile['preset-name'] === 'Gloss vinyl').profile")
                    self.assertEqual((saved['available-length'], saved['roll-length'], saved['unit']), ('1800', '1800', 'in'))
                    low = page.locator('.stock-slot', has_text='Matte vinyl 30 in')
                    expect(low).to_have_class(re.compile('low'))
                    page.locator('#stock-add').click()
                    page.fill('#roll-f-name', 'Clear laminate')
                    page.fill('#roll-f-roll', '54')
                    page.keyboard.press('Enter')
                    expect(page.locator('.stock-slot')).to_have_count(3)
                    page.click('#stock-panel .stock-x')
                    self.snap(page, 'three-rolls', width)
                    low.click()
                    expect(page.locator('#stock-panel .stock-low')).to_have_text('Low stock')
                    expect(page.locator('#stock-panel')).to_contain_text('6 ft')
                    self.snap(page, 'low-stock', width)
                    page.keyboard.press('Escape')
                    expect(page.locator('#stock-panel')).to_be_hidden()
                    expect(page.locator('#stock')).to_be_visible()
                    page.click('#stock-close')
                    self.save_rolls(page, many)
                    page.click('#stock-open')
                    expect(page.locator('.stock-slot')).to_have_count(15)
                    self.snap(page, 'many-rolls', width)
                    first = page.locator('.stock-slot').first
                    first.focus()
                    page.keyboard.press('ArrowRight')
                    expect(page.locator('.stock-slot').nth(1)).to_be_focused()
                    page.keyboard.press('Enter')
                    expect(page.locator('#stock-panel')).to_be_visible()
                    expect(page.locator('#stock-panel .stock-sub').first).to_have_text(re.compile(r'^\d+(\.\d+)? in wide roll · prints \d+(\.\d+)? in$'))
                    self.snap(page, 'detail', width)
                    expect(page.locator('#stock-panel h3')).to_have_text(page.locator('.stock-slot').nth(1).locator('.stock-label span').get_attribute('title'))
                    # The tapped roll stays visible above the details card.
                    tapped = page.locator('.stock-slot[aria-selected="true"]')
                    page.wait_for_function('''() => { const s = document.querySelector('.stock-slot[aria-selected="true"] svg').getBoundingClientRect();
                        const p = document.getElementById('stock-panel').getBoundingClientRect(); return s.bottom <= p.top + 1 && s.top >= 0; }''')
                    name = tapped.locator('.stock-label span')
                    self.assertEqual(name.get_attribute('title'), name.text_content())
                    page.keyboard.press('Escape')
                    last = page.locator('.stock-slot').last
                    last_name = last.locator('.stock-label span').get_attribute('title')
                    last.click()
                    page.wait_for_function('''() => { const s = document.querySelector('.stock-slot[aria-selected="true"] svg').getBoundingClientRect();
                        const p = document.getElementById('stock-panel').getBoundingClientRect(); return s.bottom <= p.top + 1; }''')
                    expect(page.locator('#stock-panel h3')).to_have_text(last_name)
                    self.assertEqual(violations, [])
                finally:
                    browser.close()

    def test_inventory_answers_numbers_and_touch_in_plain_terms(self):
        from playwright.sync_api import sync_playwright, expect
        with without_gate_env(), sync_playwright() as playwright:
            browser = launch_browser(playwright)
            try:
                context = browser.new_context(viewport={'width': 390, 'height': 844}, has_touch=True, is_mobile=True)
                local = self.url()
                context.route(lambda url: not url.startswith(local), lambda route: route.fulfill(status=200, content_type='text/html', body='<p>stub</p>'))
                page = context.new_page()
                page.goto(local + '/web', wait_until='domcontentloaded')
                self.wait_ready(page)
                page.wait_for_function("() => fetch('/api/shop').then(r => r.json()).then(s => s.setupComplete === true)")
                parsed = page.evaluate("""() => ({
                    huge: parseLength('99999999999999999999', 'ft').bad === true,
                    tiny: parseLength('0.0000001', 'ft').bad === true,
                    exp: parsePrice('1e308').bad === true,
                    feet: parseLength('150ft', 'in').ft,
                    inches: parseLength('1800 in', 'ft').ft,
                    zero: parseLength('0', 'ft').ft,
                    dollars: parsePrice('$8.50').value,
                    wide: parseInches('9999'),
                    names: rollNameKey('Gloss\u200b  vinyl\u202e') === rollNameKey('gloss vinyl'),
                })""")
                self.assertEqual(parsed, {'huge': True, 'tiny': True, 'exp': True, 'feet': 150, 'inches': 150, 'zero': 0, 'dollars': 8.5, 'wide': None, 'names': True})
                page.click('#stock-open')
                page.click('#stock-add')
                page.fill('#roll-f-name', 'Gloss vinyl')
                page.fill('#roll-f-roll', '54')
                page.fill('#roll-f-left', '150')
                page.fill('#roll-f-cost', '1e308')
                page.click('#stock-panel button[type=submit]')
                expect(page.locator('#stock-panel')).to_contain_text('Roll price looks wrong. Enter a number like 8.50.')
                self.assertNotIn('roll-cost', page.locator('#stock-panel').inner_text())
                for label in ('Roll width', 'Width you can print on', 'Length left on roll', 'Length of a new roll', 'Price you paid for a new roll'):
                    expect(page.locator('#stock-panel .roll-label', has_text=label)).to_have_count(1)
                page.fill('#roll-f-cost', '8.50')
                page.fill('#roll-f-full', '150')
                page.click('#stock-panel button[type=submit]')
                expect(page.locator('.stock-slot')).to_have_count(1)
                expect(page.locator('.stock-slot').first).to_have_attribute('aria-selected', 'true')
                expect(page.locator('#stock-panel .stock-selected, #stock-panel button:has-text("Use for this job")')).to_have_count(1)
                expect(page.locator('#stock-legend')).to_have_text('Tap a roll to see it. Wider roll = wider material. Fatter roll = more left.')
                small = page.evaluate("""() => [...document.querySelectorAll('#stock .dialog-close, #stock .stock-x, #stock .stock-len, #stock button.link, #stock .stock-row-actions button')]
                    .filter(n => n.offsetParent).map(n => { const r = n.getBoundingClientRect(); return [n.className || n.id, Math.round(r.width), Math.round(r.height)]; })
                    .filter(([, w, h]) => w < 44 || h < 44)""")
                self.assertEqual(small, [])
                # Server side: a name that only looks different is the same name.
                error = page.evaluate("""async () => { try { await api('/api/materials/save', {id: 'material-twin', profile: {...shopInventory.materials[0].profile, 'preset-name': 'GLOSS\u200b  vinyl'}, revision: 0}); return ''; } catch (e) { return e.message; } }""")
                self.assertIn('already exists', error)
            finally:
                browser.close()

    def test_an_older_poll_answer_never_undoes_a_save(self):
        from playwright.sync_api import sync_playwright, expect
        with without_gate_env(), sync_playwright() as playwright:
            browser, context, page = self.page(playwright, 1280)
            try:
                page.wait_for_function("() => fetch('/api/shop').then(r => r.json()).then(s => s.setupComplete === true)")
                page.evaluate("""async () => {
                    const real = window.fetch; let release; const gate = new Promise(r => { release = r; });
                    window.fetch = async (...args) => { const answer = await real(...args); if (String(args[0]).endsWith('/api/materials')) await gate; return answer; };
                    window.__slow = refreshInventory().catch(() => {});
                    await new Promise(r => setTimeout(r, 200));
                    window.fetch = real;
                    await mutateInventory('/api/materials/save', {id: 'material-race', profile: {...materialValues(), unit: 'in', 'preset-name': 'Race roll', roll: '54', width: '54', 'available-length': '1200', 'low-stock': ''}, revision: 0});
                    release();
                    await window.__slow;
                }""")
                page.wait_for_function("() => shopInventory.materials.some(m => m.id === 'material-race')")
                self.assertTrue(page.evaluate("() => shopInventory.materials.some(m => m.id === 'material-race')"))
                page.click('#stock-open')
                expect(page.locator('.stock-slot')).to_have_count(1)
            finally:
                browser.close()
