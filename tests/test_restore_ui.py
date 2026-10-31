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
        expect(page.locator('#output-required-title')).to_have_text('Connect to OUTPUT (optional)')
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
        expect(page.locator('.stock-slot')).to_have_count(3)
        expect(page.locator('#stock-job')).to_be_visible()
        gloss = page.locator('.stock-slot[data-id="gloss-54"]')
        expect(gloss).to_have_attribute('aria-label', re.compile('Fits this job'))
        gloss.click()
        expect(page.locator('#stock-panel .stock-check')).to_have_text(re.compile(r'^Fits this job: needs about [\d.]+ ft, [\d.]+ ft left$'))
        expect(page.locator('#stock-panel button.primary', has_text='Use for this job')).to_be_visible()
        expect(page.locator('#stock-panel')).to_contain_text('per sq ft')
        matte = page.locator('.stock-slot[data-id="matte-30"]')
        expect(matte).to_have_class(re.compile('low'))
        matte.click()
        expect(page.locator('#stock-panel .stock-low')).to_be_visible()
        expect(page.locator('#stock-panel .stock-check')).to_have_text(re.compile(r'^Too narrow for this job \(needs [\d.]+ in, roll is [\d.]+ in\)$'))
        expect(page.locator('#stock-panel button', has_text='Use for this job')).to_have_count(0)
        clear = page.locator('.stock-slot[data-id="clear-54"]')
        clear.click()
        expect(page.locator('#stock-panel .stock-check')).to_have_text('Enter how much is left to check')
        expect(page.locator('#stock-panel button.link', has_text='Edit')).to_be_visible()
        expect(page.locator('#stock-panel')).not_to_contain_text('per sq ft')
        expect(page.locator('#stock')).not_to_contain_text('Reserved')
        self.shot(page, f'after-inventory-crosscheck-{width}.png')
        self.final(page, 'inventory-job-check', width)
        page.click('#stock-panel .stock-len')
        expect(page.locator('#roll-f-left')).to_be_focused()
        page.fill('#roll-f-left', '75')
        page.click('#stock-panel button[type=submit]')
        # The shelf draws 75 ft while the form is still open; wait until the save is done
        # and the form has closed before picking another roll.
        expect(page.locator('#roll-f-left')).to_have_count(0, timeout=15000)
        expect(clear).to_contain_text('75 ft')
        matte.click()
        expect(page.locator('#stock-panel')).to_have_attribute('aria-label', re.compile('Matte vinyl 30'))
        page.click('#stock-panel button:has-text("Edit")')
        page.once('dialog', lambda d: d.accept())
        page.click('#stock-panel .roll-remove')
        expect(page.locator('.stock-slot')).to_have_count(2)
        expect(page.locator('#material option[value="matte-30"]')).to_have_count(0, timeout=15000)
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


class InventoryShelfTests(unittest.TestCase):
    """Inventory shelf: rolls drawn upright, tap for details, add a roll with a live drawing."""
    setUp = test_web_mvp.WebMvpTests.setUp
    start = test_web_mvp.WebMvpTests.start
    stop = test_web_mvp.WebMvpTests.stop
    tearDown = test_web_mvp.WebMvpTests.tearDown
    url = test_web_mvp.WebMvpTests.url
    wait_ready = test_web_mvp.WebMvpTests.wait_ready
    page = RestoreUiTests.page

    def setUp(self):
        test_web_mvp.WebMvpTests.setUp(self)
        self.output = FakeOutput()
        sender = patch.object(output_gate, '_post', lambda directory, raw, token: self.output.check_in(raw, token))
        sender.start()
        self.addCleanup(sender.stop)
        self.pair_shop()

    def fresh(self):
        RestoreUiTests.fresh(self)
        self.pair_shop()

    def pair_shop(self):
        # The shelf needs a connected shop: unpaired shops are asked to connect first.
        with without_gate_env():
            output_pairing.connect(server.WORK, CODE, transport=self.output.pair, host='Shop PC',
                                   check_in_transport=self.output.check_in)

    def snap(self, page, name, width):
        target = os.environ.get('EZ_NEST_SHELF_SHOTS')
        if target:
            Path(target).mkdir(parents=True, exist_ok=True)
            page.locator('#stock').screenshot(path=str(Path(target) / f'after-{name}-{width}.png'))

    def assert_panel_hides_nothing(self, page):
        # The details card is docked below the shelf: no roll or label is under it, and the
        # tapped roll is fully visible in the shelf area.
        page.wait_for_function('''() => {
            const list = document.getElementById('stock-list').getBoundingClientRect();
            const panel = document.getElementById('stock-panel').getBoundingClientRect();
            const slot = document.querySelector('.stock-slot[aria-selected="true"]').getBoundingClientRect();
            const slots = [...document.querySelectorAll('.stock-slot')].map(n => n.getBoundingClientRect());
            const visible = slots.filter(r => r.bottom > list.top && r.top < list.bottom);
            return panel.top >= list.bottom - 0.5 && slot.top >= list.top - 0.5 && slot.bottom <= list.bottom + 0.5
                && visible.every(r => {
                    // The shelf clips its own rows; only the part inside the shelf area can show.
                    const top = Math.max(r.top, list.top), bottom = Math.min(r.bottom, list.bottom);
                    return bottom <= panel.top + 0.5 || top >= panel.bottom;
                });
        }''')

    def save_rolls(self, page, rolls):
        # Through the app's own change path, then wait for the state rather than a one-shot read.
        page.evaluate('''async rolls => { for (const [id, p] of rolls) await mutateInventory('/api/materials/save', {id, profile: p, revision: 0}); }''', rolls)
        page.wait_for_function('ids => ids.every(id => shopInventory.materials.some(m => m.id === id))', arg=[r[0] for r in rolls])

    def test_shelf_add_flow_detail_and_keyboard(self):
        from playwright.sync_api import sync_playwright, expect
        names = ['Gloss vinyl', 'Matte vinyl', 'Clear laminate', 'Window film', 'Magnet', 'Paper', 'Chrome', 'Holographic',
                 'Canvas', 'Banner', 'Reflective', 'Wall decal', 'Floor graphic', 'Static cling', 'Perforated', 'Backlit film',
                 'Satin vinyl', 'Carbon wrap', 'Brushed metal', 'Glitter', 'Kraft paper', 'Photo paper', 'Mesh banner',
                 'Blockout', 'Textile', 'Heat transfer', 'Metallic gold']
        many = [[f'roll-{i}', roll(f'{n} 54 in', left=str(1800 - i * 60) if i != 4 else '', **{'roll-length': '1800', 'roll-cost': '200' if i % 3 == 0 else ''})]
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
                    low = page.locator('.stock-slot', has=page.locator('.stock-name[title="Matte vinyl 30 in"]'))
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
                    expect(page.locator('.stock-slot')).to_have_count(30)
                    self.snap(page, '30-rolls', width)
                    first = page.locator('.stock-slot').first
                    first.focus()
                    page.keyboard.press('ArrowRight')
                    expect(page.locator('.stock-slot').nth(1)).to_be_focused()
                    page.keyboard.press('Enter')
                    expect(page.locator('#stock-panel')).to_be_visible()
                    expect(page.locator('#stock-panel .stock-sub').first).to_have_text(re.compile(r'^\d+(\.\d+)? in wide roll · prints \d+(\.\d+)? in$'))
                    self.snap(page, 'detail', width)
                    expect(page.locator('#stock-panel h3')).to_have_text(page.locator('.stock-slot').nth(1).locator('.stock-name').get_attribute('title'))
                    # The tapped roll stays visible above the details card.
                    tapped = page.locator('.stock-slot[aria-selected="true"]')
                    self.assert_panel_hides_nothing(page)
                    name = tapped.locator('.stock-name')
                    self.assertTrue(name.get_attribute('title').startswith(name.text_content()))
                    self.assertRegex(tapped.locator('.stock-size').text_content(), r'^\d+(\.\d+)? in$')
                    page.keyboard.press('Escape')
                    last = page.locator('.stock-slot').last
                    last_name = last.locator('.stock-name').get_attribute('title')
                    last.click()
                    self.assert_panel_hides_nothing(page)
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
                expect(page.locator('#stock-legend')).to_have_text('Tap a roll to see it. Taller roll = wider material. Fatter roll = more left.')
                expect(page.locator('#stock .dialog-heading .hint')).to_have_text('Rolls in stock in the shop')
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

    def test_an_older_refresh_never_replaces_a_newer_one(self):
        from playwright.sync_api import sync_playwright
        with without_gate_env(), sync_playwright() as playwright:
            browser, context, page = self.page(playwright, 1280)
            try:
                page.wait_for_function("() => fetch('/api/shop').then(r => r.json()).then(s => s.setupComplete === true)")
                shown = page.evaluate("""async () => {
                    const real = window.fetch; let release; const gate = new Promise(r => { release = r; });
                    let first = true;
                    window.fetch = async (...args) => { const answer = await real(...args);
                        if (String(args[0]).endsWith('/api/materials') && first) { first = false; await gate; } return answer; };
                    const slow = refreshInventory().catch(() => {});        // older request, held back
                    await new Promise(r => setTimeout(r, 150));
                    // Another screen adds a roll; this computer only sees it through a refresh.
                    await real('/api/materials/save', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-EZ-Token': (await (await real('/api/session')).json()).token},
                        body: JSON.stringify({id: 'material-other', profile: {...materialValues(), unit: 'in', 'preset-name': 'Other screen roll', roll: '54', width: '54', 'available-length': '600', 'low-stock': ''}, revision: 0})});
                    await refreshInventory();                                // newer request, lands first
                    release(); await slow;                                   // older answer lands last
                    window.fetch = real;
                    return shopInventory.materials.map(m => m.id);
                }""")
                self.assertIn('material-other', shown)
            finally:
                browser.close()

    def assert_labels_clear_of_rolls(self, page):
        # Amount left above every roll, name under it, nothing touching the drawing.
        bad = page.evaluate("""() => [...document.querySelectorAll('.stock-slot')].map(slot => {
            const qty = slot.querySelector('.stock-qty').getBoundingClientRect();
            const svg = slot.querySelector('svg.stock-roll');
            const shape = svg.querySelector('.roll-body') || svg.querySelector('path');
            const roll = shape.getBoundingClientRect(), box = svg.getBoundingClientRect();
            const name = slot.querySelector('.stock-label').getBoundingClientRect();
            return [slot.dataset.id, qty.bottom <= roll.top + 0.5, name.top >= box.bottom - 0.5];
        }).filter(([, above, below]) => !above || !below)""")
        self.assertEqual(bad, [])

    def test_shelf_labels_and_job_lines(self):
        from playwright.sync_api import sync_playwright, expect
        rolls = [
            ['fits', roll('Gloss vinyl 54 in', width='54', roll_width='54', left='1800', **{'roll-length': '1800'})],
            ['narrow', roll('Matte vinyl 30 in', width='30', roll_width='30', left='1200', **{'roll-length': '1800'})],
            ['short', roll('Clear laminate 54 in', width='54', roll_width='54', left='240', **{'roll-length': '1800'})],
            ['unmeasured', roll('Window film 60 in', width='60', roll_width='60')],
            ['low', roll('Backlit film 54 in with a very long name for the shelf', width='54', roll_width='54', left='60', **{'roll-length': '1800', 'low-stock': '120'})],
        ] + [[f'extra-{i}', roll(f'Banner {i} 64 in', width='64', roll_width='64', left=str(600 + i * 120), **{'roll-length': '1800'})] for i in range(7)]
        with without_gate_env(), sync_playwright() as playwright:
            for width in (1280, 390):
                if width == 390:
                    self.fresh()
                browser, context, page = self.page(playwright, width)
                try:
                    page.wait_for_function("() => fetch('/api/shop').then(r => r.json()).then(s => s.setupComplete === true)")
                    self.save_rolls(page, rolls[:3])
                    page.click('#stock-open')
                    expect(page.locator('.stock-slot')).to_have_count(3)
                    self.assert_labels_clear_of_rolls(page)
                    self.snap(page, '3-rolls', width)
                    # No job open: no job line and no fit wording.
                    page.locator('.stock-slot[data-id="fits"]').click()
                    expect(page.locator('#stock-panel .stock-check')).to_have_count(0)
                    expect(page.locator('#stock-panel button', has_text='Use for this job')).to_be_visible()
                    page.click('#stock-close')
                    self.save_rolls(page, rolls[3:])
                    # A job 50 in wide that needs 100 ft.
                    page.evaluate("() => { current = {...(current || {}), result: {width: 50 * 25.4, usedLength: 100 * 304.8}}; }")
                    page.click('#stock-open')
                    expect(page.locator('.stock-slot')).to_have_count(12)
                    per_row = page.evaluate("() => new Set([...document.querySelectorAll('.stock-slot')].map(n => Math.round(n.getBoundingClientRect().top))).size")
                    self.assertEqual(per_row, 2 if width == 1280 else 3)
                    self.assert_labels_clear_of_rolls(page)
                    qty = page.locator('.stock-slot[data-id="unmeasured"] .stock-qty b')
                    expect(qty).to_have_text('Not measured')
                    low = page.locator('.stock-slot[data-id="low"]')
                    expect(low.locator('.stock-qty b')).to_have_css('color', 'rgb(180, 35, 24)')
                    name = low.locator('.stock-name')
                    self.assertEqual(name.get_attribute('title'), 'Backlit film 54 in with a very long name for the shelf')
                    self.assertIn('Backlit film 54 in with a very long name for the shelf', low.get_attribute('aria-label'))
                    self.assertLessEqual(name.evaluate("n => Math.round(n.getBoundingClientRect().height / parseFloat(getComputedStyle(n).lineHeight))"), 2)
                    self.snap(page, '12-rolls', width)
                    cases = {
                        'fits': r'^Fits this job: needs about 100 ft, 150 ft left$',
                        'narrow': r'^Too narrow for this job \(needs 50 in, roll is 30 in\)$',
                        'short': r'^Not enough on this roll\. Need 80 more ft$',
                        'unmeasured': r'^Enter how much is left to check$',
                    }
                    for rid, text in cases.items():
                        page.locator(f'.stock-slot[data-id="{rid}"]').click()
                        expect(page.locator('#stock-panel .stock-check')).to_have_text(re.compile(text))
                        use = page.locator('#stock-panel button', has_text='Use for this job')
                        expect(use).to_have_count(0 if rid == 'narrow' else 1)
                        if rid == 'fits':
                            expect(use).to_have_class(re.compile('primary'))
                            expect(page.locator('#stock-panel .stock-check')).to_have_css('color', 'rgb(21, 128, 61)')
                        if rid == 'unmeasured':
                            page.locator('#stock-panel button.link', has_text='Edit').click()
                            expect(page.locator('#roll-f-left')).to_be_focused()
                            page.keyboard.press('Escape')
                            expect(page.locator('#roll-f-left')).to_have_count(0)
                            continue
                        self.assert_panel_hides_nothing(page)
                        self.snap(page, {'fits': 'detail-fits', 'narrow': 'detail-too-narrow', 'short': 'detail-not-enough'}[rid], width)
                        page.keyboard.press('Escape')
                    if not page.locator('#stock').is_visible():
                        page.click('#stock-open')
                    page.locator('.stock-slot[data-id="low"]').click()
                    expect(page.locator('#stock-panel .stock-low')).to_be_visible()
                    self.snap(page, 'low-stock', width)
                    # The roll this job already uses.
                    page.evaluate("() => { $('material').value = 'fits'; renderStock(); selectRoll('fits'); }")
                    expect(page.locator('#stock-panel .stock-selected')).to_have_text('This job uses this roll')
                    page.locator('#stock-panel button', has_text='Use a different roll').click()
                    expect(page.locator('#stock-panel')).to_be_hidden()
                finally:
                    browser.close()

    def assert_label_rows_line_up(self, page):
        # In every shelf row the names start at one height and the size lines sit at one height.
        rows = page.evaluate("""() => {
            const rows = {};
            for (const slot of document.querySelectorAll('.stock-slot')) {
                const top = Math.round(slot.getBoundingClientRect().top);
                const name = slot.querySelector('.stock-name'), size = slot.querySelector('.stock-size');
                const lines = Math.round(name.getBoundingClientRect().height / parseFloat(getComputedStyle(name).lineHeight));
                (rows[top] = rows[top] || []).push([Math.round(name.getBoundingClientRect().top), Math.round(size.getBoundingClientRect().bottom), lines]);
            }
            return Object.values(rows);
        }""")
        for row in rows:
            self.assertEqual(len({r[0] for r in row}), 1, row)
            self.assertEqual(len({r[1] for r in row}), 1, row)
            self.assertTrue(all(r[2] <= 2 for r in row), row)

    def test_shelf_names_and_widths(self):
        from playwright.sync_api import sync_playwright, expect
        long_name = 'Premium removable matte wall graphic film with low-tack adhesive 54 in'
        base = [
            ['gloss', roll('Gloss vinyl 54 in', width='51.5', roll_width='54', left='1800', **{'roll-length': '1800'})],
            ['banner', roll('Banner 64', width='63', roll_width='64', left='1200', **{'roll-length': '1800'})],
            ['plain', roll('Clear laminate', width='54', roll_width='54', left='240', **{'roll-length': '1800', 'low-stock': '600'})],
        ]
        more = [['long', roll(long_name, width='54', roll_width='54', left='900', **{'roll-length': '1800'})],
                ['long2', roll('Supercalifragilisticexpialidocious-reflective-sheeting', width='30', roll_width='30', left='600', **{'roll-length': '1800'})]]
        more += [[f'x{i}', roll(f'Material {i} 54 in', width='54', roll_width='54', left=str(300 + i * 60), **{'roll-length': '1800'})] for i in range(7)]
        many = [[f'y{i}', roll(f'Extra roll {i}', width='24', roll_width='24', left=str(400 + i * 30), **{'roll-length': '1800'})] for i in range(18)]
        with without_gate_env(), sync_playwright() as playwright:
            for width in (1280, 390):
                if width == 390:
                    self.fresh()
                browser, context, page = self.page(playwright, width)
                try:
                    page.wait_for_function("() => fetch('/api/shop').then(r => r.json()).then(s => s.setupComplete === true)")
                    cases = page.evaluate("""() => [shelfShortName('Gloss vinyl 54 in', 54), shelfShortName('Banner 64', 64), shelfShortName('Clear laminate', 54),
                        shelfShortName('Vinyl - 54"', 54), shelfShortName('Gloss vinyl 54 in', 30), shelfShortName('54 in', 54), shelfShortName('Film 51.5 in', 51.5)]""")
                    self.assertEqual(cases, ['Gloss vinyl', 'Banner', 'Clear laminate', 'Vinyl', 'Gloss vinyl 54 in', '54 in', 'Film'])
                    self.save_rolls(page, base)
                    page.click('#stock-open')
                    expect(page.locator('.stock-slot')).to_have_count(3)
                    gloss = page.locator('.stock-slot[data-id="gloss"]')
                    expect(gloss.locator('.stock-name')).to_have_text('Gloss vinyl')
                    expect(gloss.locator('.stock-name')).to_have_attribute('title', 'Gloss vinyl 54 in')
                    expect(gloss.locator('.stock-size')).to_have_text('54 in')
                    self.assertIn('54 inches wide', gloss.get_attribute('aria-label'))
                    self.assertIn('Gloss vinyl 54 in', gloss.get_attribute('aria-label'))
                    expect(page.locator('.stock-slot[data-id="banner"] .stock-name')).to_have_text('Banner')
                    expect(page.locator('.stock-slot[data-id="plain"] .stock-name')).to_have_text('Clear laminate')
                    self.assertNotIn('prints', page.locator('#stock-list').inner_text())
                    self.assert_label_rows_line_up(page)
                    self.assert_labels_clear_of_rolls(page)
                    self.snap(page, '3-rolls', width)
                    page.locator('.stock-slot[data-id="plain"]').click()
                    expect(page.locator('#stock-panel .stock-low')).to_be_visible()
                    self.snap(page, 'low-stock', width)
                    page.keyboard.press('Escape')
                    page.locator('.stock-slot[data-id="gloss"]').click()
                    expect(page.locator('#stock-panel h3')).to_have_text('Gloss vinyl 54 in')
                    expect(page.locator('#stock-panel .stock-sub').first).to_have_text('54 in wide roll · prints 51.5 in')
                    self.snap(page, 'detail', width)
                    page.keyboard.press('Escape')
                    page.click('#stock-close')
                    self.save_rolls(page, more)
                    page.click('#stock-open')
                    expect(page.locator('.stock-slot')).to_have_count(12)
                    per_row = page.evaluate("() => { const tops = [...document.querySelectorAll('.stock-slot')].map(n => Math.round(n.getBoundingClientRect().top)); return tops.filter(t => t === tops[0]).length; }")
                    self.assertEqual(per_row, 6 if width == 1280 else 4)
                    long = page.locator('.stock-slot[data-id="long"]')
                    expect(long.locator('.stock-name')).to_have_attribute('title', long_name)
                    self.assertIn(long_name, long.get_attribute('aria-label'))
                    clipped = long.locator('.stock-name').evaluate('n => n.scrollHeight > n.clientHeight + 1')
                    self.assertTrue(clipped)
                    self.assert_label_rows_line_up(page)
                    self.assert_labels_clear_of_rolls(page)
                    # Rows with only one-line names close up; a row with a long name keeps two lines.
                    expect(page.locator('.stock-slot[data-id="x6"]')).to_have_class(re.compile('one-line'))
                    expect(long).not_to_have_class(re.compile('one-line'))
                    gap = page.locator('.stock-slot[data-id="x6"]').evaluate("s => s.querySelector('.stock-size').getBoundingClientRect().top - s.querySelector('.stock-name').getBoundingClientRect().bottom")
                    self.assertLess(gap, 6)
                    self.snap(page, '12-rolls', width)
                    long.scroll_into_view_if_needed()
                    self.snap(page, 'long-names', width)
                    page.click('#stock-close')
                    self.save_rolls(page, many)
                    page.click('#stock-open')
                    expect(page.locator('.stock-slot')).to_have_count(30)
                    self.assert_label_rows_line_up(page)
                    self.snap(page, '30-rolls', width)
                finally:
                    browser.close()

    def test_a_refresh_during_a_slow_save_does_not_hide_the_saved_roll(self):
        from playwright.sync_api import sync_playwright
        with without_gate_env(), sync_playwright() as playwright:
            browser, context, page = self.page(playwright, 1280)
            try:
                page.wait_for_function("() => fetch('/api/shop').then(r => r.json()).then(s => s.setupComplete === true)")
                shown = page.evaluate("""async () => {
                    const real = window.fetch;
                    // The save takes 600 ms to reach the server; a refresh started after it answers first.
                    window.fetch = async (...args) => {
                        if (String(args[0]).endsWith('/api/materials/save')) await new Promise(r => setTimeout(r, 600));
                        return real(...args); };
                    const save = mutateInventory('/api/materials/save', {id: 'material-slow',
                        profile: {...materialValues(), unit: 'in', 'preset-name': 'Slow save roll', roll: '54', width: '54', 'available-length': '600', 'low-stock': ''}, revision: 0});
                    await new Promise(r => setTimeout(r, 50));
                    await refreshInventory().catch(() => {});
                    await save;
                    const right = shopInventory.materials.map(m => m.id);
                    await new Promise(r => setTimeout(r, 300));
                    window.fetch = real;
                    return [right, shopInventory.materials.map(m => m.id)];
                }""")
                self.assertIn('material-slow', shown[0])
                self.assertIn('material-slow', shown[1])
            finally:
                browser.close()

    def test_inventory_controls_are_44px_with_a_mouse(self):
        from playwright.sync_api import sync_playwright, expect
        with without_gate_env(), sync_playwright() as playwright:
            for width in (1280, 390):
                if width == 390:
                    self.fresh()
                browser, context, page = self.page(playwright, width)
                try:
                    page.wait_for_function("() => fetch('/api/shop').then(r => r.json()).then(s => s.setupComplete === true)")
                    self.save_rolls(page, [['material-a', roll('Gloss vinyl 54 in', left='600', **{'roll-length': '1800'})]])
                    page.click('#stock-open')
                    page.locator('.stock-slot').first.click()
                    expect(page.locator('#stock-panel')).to_be_visible()
                    small = page.evaluate("""() => [...document.querySelectorAll('#stock .dialog-close, #stock .stock-x, #stock .stock-len, #stock button.link, #stock .stock-row-actions button')]
                        .filter(n => n.offsetParent).map(n => { const r = n.getBoundingClientRect(); return [n.className || n.id, Math.round(r.width), Math.round(r.height)]; })
                        .filter(([, w, h]) => w < 44 || h < 44)""")
                    self.assertEqual(small, [])
                finally:
                    browser.close()
