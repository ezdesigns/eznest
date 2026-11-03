"""Explicit frozen Windows update/rollback rehearsal, using only a new test folder."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import sys
import subprocess
import time
from urllib.request import Request, urlopen
from urllib.error import URLError
from zipfile import ZipFile, ZIP_DEFLATED

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import installer_update


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    if work.exists():
        raise ValueError('Use a new dedicated rehearsal directory.')
    work.mkdir(parents=True)
    app, data = work/'app', work/'data'
    app.mkdir(); data.mkdir()
    with ZipFile(args.zip) as archive:
        archive.extractall(app)
    baseline = json.loads((app/'version.json').read_text())['version']
    inventory = b'synthetic stock that must survive both operations'
    (data/'stock-rehearsal.bin').write_bytes(inventory)
    (data/'shop.json').write_text('{"updates":true,"channel":"test","outputNetwork":false}')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    env = dict(os.environ, EZ_NEST_UPDATES='1', EZ_NEST_OUTPUT_UPLOADS='0')
    # The source test opt-out must not influence packaged acceptance.
    for name in ('EZ_NEST_DEV', 'EZ_NEST_DEV_NO_OUTPUT', 'EZ_NEST_OUTPUT_GATE_OPEN', 'EZ_NEST_INSTALL_ROOT'):
        env.pop(name, None)
    child = subprocess.Popen([str(app/'eznest.exe'), '--no-browser', '--port', str(port), '--data-dir', str(data)],
                             env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    owned_pids = {child.pid}
    token = None

    def request(path, body=None):
        headers = {'Content-Type': 'application/json'}
        if token: headers['X-EZ-Token'] = token
        with urlopen(Request(f'http://127.0.0.1:{port}'+path, headers=headers,
                             data=json.dumps(body).encode() if body is not None else None), timeout=20) as response:
            return json.load(response)

    def wait_version(version, timeout=120):
        nonlocal token
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            try:
                session = request('/api/session')
                if session['version'] == version:
                    token = session['token']
                    status = request('/api/update')
                    owned_pids.add(status['serverPid'])
                    return status
            except (URLError, OSError, ValueError):
                pass
            time.sleep(.25)
        raise TimeoutError('The updated host did not return on its original port.')

    def stage(version, broken=False):
        target = work/(version+'.zip')
        with ZipFile(args.zip) as source, ZipFile(target, 'w', ZIP_DEFLATED) as candidate:
            for item in source.infolist():
                payload = source.read(item)
                if item.filename in ('version.json', '_internal/version.json'):
                    info = json.loads(payload); info['version'] = version; payload = json.dumps(info).encode()
                if broken and item.filename == 'eznest.exe': payload = b'not an executable'
                candidate.writestr(item, payload)
        payload = target.read_bytes()
        pending = installer_update.stage_file(data, version, hashlib.sha256(payload).hexdigest(), payload, 'eznest-shop-windows.zip')
        pending['applyOnRestart'] = False
        installer_update.write_json(data/'updates'/'pending.json', pending)

    try:
        first = wait_version(baseline)
        assert first['portableSupported'] and first['localPC']
        stage('99.0.0-rc.1')
        assert request('/api/update/install', {})['restarting']
        updated = wait_version('99.0.0-rc.1')
        assert updated['serverPid'] != first['serverPid']
        assert (data/'stock-rehearsal.bin').read_bytes() == inventory
        # Let the success helper finish before staging the next rehearsal.
        deadline = time.monotonic()+30
        while (data/'updates'/'backup').exists() and time.monotonic() < deadline: time.sleep(.25)
        stage('99.0.0-rc.2', broken=True)
        assert request('/api/update/install', {})['restarting']
        # Wait for the old process to leave; then accept only a different process.
        deadline = time.monotonic()+120
        while time.monotonic() < deadline:
            restored = wait_version('99.0.0-rc.1', timeout=120)
            if restored['serverPid'] != updated['serverPid']: break
            time.sleep(.25)
        else: raise TimeoutError('Rollback did not restart the prior host.')
        assert (data/'stock-rehearsal.bin').read_bytes() == inventory
        assert json.loads((data/'shop.json').read_text())['outputNetwork'] is False
        result = {'ok': True, 'baseVersion': baseline, 'update': True, 'rollback': True,
                  'samePort': True, 'inventoryPreserved': True, 'outputOff': True}
        (work/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result))
    finally:
        # Only processes returned by this unique-port, newly-created test host.
        for pid in owned_pids:
            try: os.kill(pid, signal.SIGTERM)
            except OSError: pass
        try: child.wait(timeout=10)
        except subprocess.TimeoutExpired: pass


if __name__ == '__main__':
    main()
