"""Visible SVG import/export regression against the installed runner service only.

No account browser, saved context, source application, or JavaScript state bypass.
Playwright is installed only by the guarded disposable acceptance workflows.
"""
import hashlib
import os
import re
from urllib.parse import urlsplit

from test_published_macos import completed_state, require, validate_export

ORIGIN = 'http://127.0.0.1:8765'
SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" width="80mm" height="40mm" viewBox="0 0 80 40">
<g id="cyan"><rect id="CutContour_Thru-cut" data-ezn-boundary="true" x="5" y="5" width="20" height="20" fill="#00bcd4" stroke="#ff00ff" stroke-width="0.1"/></g>
<g id="yellow"><rect id="CutContourThruCut" data-ezn-boundary="true" x="45" y="5" width="20" height="20" fill="#ffdf00" stroke="#ff00ff" stroke-width="0.1"/></g>
</svg>'''


def local_browser_url(url):
    parsed = urlsplit(url)
    target = urlsplit(ORIGIN)
    return (parsed.scheme == target.scheme == 'http' and parsed.netloc == target.netloc
            and parsed.hostname == '127.0.0.1' and parsed.username is None and parsed.password is None)


def svg_file_flow(api, root):
    from playwright.sync_api import expect, sync_playwright

    source = root / 'eznest-synthetic.svg'
    target = root / 'eznest-synthetic-svg.zip'
    source.write_bytes(SVG)
    # The Playwright driver and browser inherit no Actions or OUTPUT credentials.
    previous = dict(os.environ)
    browser_env = {key: previous[key] for key in ('HOME', 'PATH', 'TMPDIR') if key in previous}
    os.environ.clear(); os.environ.update(browser_env)
    try:
        with sync_playwright() as playwright:
            print('SVG_STAGE: browser-start', flush=True)
            browser = playwright.chromium.launch(channel='chrome', headless=True, env=browser_env)
            try:
                context = browser.new_context(viewport={'width':1280,'height':900},
                                              accept_downloads=True, service_workers='block')
                context.route('**/*', lambda route: route.continue_()
                              if local_browser_url(route.request.url) else route.abort())
                # Deny WebSocket egress as well; this application uses ordinary HTTP.
                context.route_web_socket('**/*', lambda websocket: websocket.close())
                page = context.new_page()
                print('SVG_STAGE: page-load', flush=True)
                page.goto(ORIGIN + '/?view=simple', wait_until='domcontentloaded')
                expect(page.locator('body')).to_have_attribute('data-ready', '1', timeout=60000)
                print('SVG_STAGE: optional-output', flush=True)
                if page.locator('#output-required').is_visible():
                    page.click('#output-required-skip')
                    expect(page.locator('#output-required')).to_be_hidden()
                if page.locator('#feedback-welcome').is_visible():
                    page.click('#feedback-dismiss')
                if page.locator('#setup').is_visible():
                    page.select_option('#setup-units', 'mm')
                    page.click('#setup-save')
                    expect(page.locator('#setup')).to_be_hidden()
                print('SVG_STAGE: material-open', flush=True)
                page.click('#edit-material')
                print('SVG_STAGE: material-fields', flush=True)
                page.select_option('#unit', 'mm')
                page.fill('#width', '100')
                print('SVG_STAGE: material-save', flush=True)
                page.click('#save-material')
                expect(page.locator('#material-dialog')).not_to_be_visible()
                page.select_option('#nesting-effort', '5')
                print('SVG_STAGE: file-import', flush=True)
                page.set_input_files('#file', str(source))
                expect(page.locator('#start-nesting')).to_be_enabled(timeout=30000)
                print('SVG_STAGE: nest', flush=True)
                page.click('#start-nesting')
                expect(page.locator('#gate')).to_contain_text(re.compile('cuts ok', re.I), timeout=90000)
                state = completed_state(api)
                # Source SVG markup and its revision must come from the actual file importer.
                require(len(state['job']['parts']) == 2
                        and all(part.get('svg', {}).get('markup') for part in state['job']['parts'])
                        and any(job.get('revision') == hashlib.sha256(SVG).hexdigest()
                                for job in state['job'].get('productionJobs', [])),
                        'SVG file import identity or artwork is missing.')
                print('SVG_STAGE: export', flush=True)
                page.click('#export')
                page.select_option('#save-destination', 'download')
                page.select_option('#save-format', 'pack')
                with page.expect_download(timeout=60000) as pending:
                    page.click('#confirm-send')
                pending.value.save_as(str(target))
                require(target.stat().st_size <= 10_000_000, 'SVG print pack exceeds its bound.')
                content = target.read_bytes()
                digest = validate_export(content, 'svg', state['id'])
                status, released = api.request('/api/state')
                status_bytes, server_content = api.exchange('/api/batch/' + state['id'])
                require(status == 200 and released.get('id') == state['id']
                        and released.get('released') is True and released.get('sha256') == digest
                        and status_bytes == 200 and server_content == content,
                        'Browser SVG download differs from the frozen installed batch.')
                return {'format':'svg','id':state['id'],'sha256':digest,'bytes':content}
            finally:
                browser.close()
    finally:
        os.environ.clear(); os.environ.update(previous)
