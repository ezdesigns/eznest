"""QA-only signed rc.6 -> rc.7 upgrade on an exclusively owned disposable VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import test_published_macos as a

BASELINE = '1.0.0-rc.6'
BASELINE_HASH = 'fa1541a5d08ab12dd43db62cc02c64b510d007db71a94ba16687a1d40c108cf6'
CANDIDATE = '1.0.0-rc.7'


def select(version):
    a.VERSION = version
    a.PACKAGE_NAME = f'eznest-shop-arm64-{version}.pkg'


class ReleaseRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        parsed = urlsplit(newurl)
        a.require(parsed.scheme == 'https' and parsed.netloc == 'release-assets.githubusercontent.com'
                  and not parsed.fragment, 'Unexpected public asset redirect.')
        return super().redirect_request(request, response, code, message, headers, newurl)


def download(root, version, expected):
    a.valid_hash(expected)
    package = root / f'eznest-shop-arm64-{version}.pkg'
    url = f'https://github.com/ezdesigns/eznest/releases/download/v{version}/{package.name}'
    digest = hashlib.sha256()
    with build_opener(ProxyHandler({}), ReleaseRedirect()).open(Request(url), timeout=30) as response, package.open('xb') as target:
        a.require(response.status == 200, 'Public package download failed.')
        size = 0; deadline = time.monotonic() + 120
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            a.require(size <= 300_000_000 and time.monotonic() < deadline, 'Public download exceeded its bound.')
            digest.update(chunk); target.write(chunk)
    a.require(size > 0 and digest.hexdigest() == expected, 'Public package checksum mismatch.')


def upgrade(root, expected):
    a.verify_package(root / a.PACKAGE_NAME, expected)
    marker = root / 'eznest-macos-owned.json'
    ownership = json.loads(marker.read_text())
    a.require(ownership == {'runId':os.environ['GITHUB_RUN_ID'], 'installerSettled':True},
              'Only this VM owned baseline may be upgraded.')
    ownership['installerSettled'] = False; a.write_json(marker, ownership)
    process = subprocess.Popen(['/usr/bin/sudo', '-n', '/usr/sbin/installer', '-pkg',
        str(root / a.PACKAGE_NAME), '-target', '/'], stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=a.SAFE_ENV, start_new_session=True)
    try:
        code = process.wait(timeout=240)
    except subprocess.TimeoutExpired:
        a.command(['/usr/bin/sudo', '-n', '/bin/kill', '-TERM', '--', '-' + str(process.pid)])
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            a.command(['/usr/bin/sudo', '-n', '/bin/kill', '-KILL', '--', '-' + str(process.pid)])
            process.wait(timeout=15)
        raise a.AcceptanceError('Upgrade Installer timed out; cleanup blocked until VM teardown.')
    ownership['installerSettled'] = True; a.write_json(marker, ownership)
    a.require(code == 0, 'Signed upgrade installation failed.')


def run(root):
    a.require(a.VERSION == CANDIDATE, 'QA source must target rc.7.')
    expected = a.valid_hash(os.environ.get('EZ_NEST_PACKAGE_SHA256'))
    a.preflight()
    print('UPGRADE_STAGE: public signed downloads', flush=True)
    download(root, BASELINE, BASELINE_HASH); download(root, CANDIDATE, expected)
    print('UPGRADE_STAGE: baseline install', flush=True)
    select(BASELINE); a.install(root, BASELINE_HASH)
    api = a.LocalAPI(); api.session(); a.preview_settings(api)
    profile = {'preset-name':'Synthetic upgrade roll', 'unit':'mm', 'width':'500', 'roll':'510',
        'available-length':'1000', 'roll-length':'5000', 'gap':'2', 'margin':'5',
        'mark-margin':'0', 'sheet':'1000', 'rotations':'0,90,180,270', 'auto-bleed':'0',
        'bleed':'0', 'cost':'', 'roll-cost':'', 'low-stock':'200', 'print-layout':'sections'}
    a.require(api.request('/api/materials/save', {'id':'upgrade-roll','profile':profile,'revision':0})[0] == 200,
              'Baseline inventory fixture could not be saved.')
    status, stock = api.request('/api/materials'); materials = stock.get('materials')
    a.require(status == 200 and len(materials) == 1 and materials[0]['onHandMm'] == 1000,
              'Baseline synthetic inventory is incorrect.')
    print('UPGRADE_STAGE: baseline inventory and frozen PDF', flush=True)
    exports = [a.pdf_file_flow(api)]
    print('UPGRADE_STAGE: candidate upgrade', flush=True)
    select(CANDIDATE); upgrade(root, expected)
    api = a.LocalAPI(); api.healthy(); a.verify_installed_identity(); a.preview_settings(api)
    a.require(api.request('/api/materials')[1].get('materials') == materials, 'Inventory changed during upgrade.')
    a.verify_persistence(api, exports)
    print('UPGRADE_STAGE: compile isolated Applications observer', flush=True)
    build = root / 'eznest-upgrade-observer'; build.mkdir(exist_ok=False)
    subprocess.run(['/usr/bin/xcrun', '--sdk', 'macosx', 'swiftc', '-swift-version', '5',
        '-target', 'arm64-apple-macos26.0', '-module-cache-path', str(build / 'module-cache'),
        '-framework', 'AppKit', '-framework', 'CoreGraphics',
        str(Path(__file__).with_name('verify_installed_desktop.swift')), '-o', str(build / 'observer')],
        check=True, timeout=180)
    pid = api.session()['pid']
    print('UPGRADE_STAGE: signed production desktop launch and Quit', flush=True)
    subprocess.run([str(build / 'observer')], check=True, timeout=90)
    a.require(api.session()['pid'] == pid, 'Desktop launch or Quit replaced the shared backend.')
    a.require(api.request('/api/materials')[1].get('materials') == materials, 'Desktop lifecycle changed Inventory.')
    a.verify_persistence(api, exports)
    a.write_json(root / 'eznest-rc7-upgrade.json', {'baseline':BASELINE, 'baselineSha256':BASELINE_HASH,
        'version':CANDIDATE, 'sha256':expected, 'source':os.environ['GITHUB_SHA'],
        'runId':os.environ['GITHUB_RUN_ID'], 'signedUpgrade':True, 'inventoryRetained':True,
        'frozenPdfRetained':True, 'applicationsNativeWindow':True, 'noBrowserStartup':True,
        'quitPreservesBackend':True})
    print('UPGRADE_PASS: signed rc.6 -> rc.7; Inventory/PDF retained; Applications desktop verified.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['Run', 'Cleanup']); args = parser.parse_args()
    try:
        root = a.runner_guard()
        if args.phase == 'Cleanup': a.cleanup(root)
        else: run(root)
    except a.AcceptanceError as error:
        print(str(error), file=sys.stderr); return 1
    except Exception:
        print('Upgrade acceptance failed; inspect sanitized stage logs.', file=sys.stderr); return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
