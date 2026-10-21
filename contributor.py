"""Small, opt-in source setup for Windows contributors; never installs a service."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def locations(root=ROOT, local_app_data=None):
    root = Path(root).resolve()
    local = local_app_data or os.environ.get('LOCALAPPDATA')
    if not local:
        raise ValueError('LOCALAPPDATA is missing; use this setup on Windows.')
    requirements = hashlib.sha256((root / 'requirements.txt').read_bytes()).hexdigest()
    checkout = hashlib.sha256(str(root).casefold().encode()).hexdigest()[:20]
    environment = root / '.local' / 'contributor-venvs' / requirements[:16]
    return {'root':root, 'requirementsHash':requirements, 'environment':environment,
            'python':environment / 'Scripts' / 'python.exe',
            'data':Path(local).resolve() / 'eznest-contributors' / checkout / 'Data'}


def require_runtime():
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8:
        raise ValueError('Run with 64-bit Python 3.12 on Windows. No files were changed.')


def ready(paths):
    marker = paths['environment'] / 'contributor-ready.json'
    try:
        return paths['python'].is_file() and json.loads(marker.read_text()) == {
            'requirementsHash':paths['requirementsHash'], 'python':'3.12-x64'}
    except (OSError, ValueError):
        return False


def setup(paths, test_tools=False):
    environment = paths['environment']
    if not ready(paths):
        owner = environment / 'contributor-environment.json'
        expected = {'requirementsHash':paths['requirementsHash'], 'python':'3.12-x64'}
        try:
            owned = json.loads(owner.read_text()) == expected
        except (OSError, ValueError):
            owned = False
        if environment.exists() and any(environment.iterdir()) and not owned:
            raise ValueError('An incomplete or unrecognized environment exists at ' + str(environment) + '. Inspect it; do not overwrite or delete it automatically.')
        environment.mkdir(parents=True, exist_ok=True)
        owner.write_text(json.dumps(expected))
        venv.EnvBuilder(with_pip=True).create(environment)
        subprocess.run([str(paths['python']), '-m', 'pip', 'install', '-r', str(paths['root'] / 'requirements.txt')], check=True)
        (environment / 'contributor-ready.json').write_text(json.dumps(expected))
    if test_tools:
        subprocess.run([str(paths['python']), '-m', 'pip', 'install', 'playwright'], check=True)
    print('Source environment ready. Use contributor.py start to open the isolated test app.')


def start_command(paths, port=8765, no_browser=False):
    command = [str(paths['python']), str(paths['root'] / 'launcher.py'), '--shop-test',
               '--data-dir', str(paths['data']), '--port', str(port)]
    if no_browser:
        command.append('--no-browser')
    return command


def check(paths):
    node, pwsh = shutil.which('node'), shutil.which('pwsh')
    if not node or not pwsh:
        raise ValueError('Checks require Node 24 and PowerShell 7 on PATH. The app itself only needs Python.')
    if not subprocess.check_output([node, '--version'], text=True).strip().startswith('v24.'):
        raise ValueError('Checks require Node 24.')
    version = subprocess.check_output([pwsh, '-NoProfile', '-Command', '$PSVersionTable.PSVersion.Major'], text=True).strip()
    if version != '7':
        raise ValueError('Checks require PowerShell 7.')
    commands = [[str(paths['python']), '-c', 'import playwright'],
                [str(paths['python']), '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py']]
    commands += [[node, '--check', script] for script in ['queue-app.js', 'production-features.js', 'cut-mapping.js', 'web.js', 'tester/feedback.js']]
    commands += [[node, 'tests/' + name + '.cjs'] for name in ['test_queue', 'test_shop_profiles', 'test_cut_mapping', 'test_production_features', 'test_boundaries', 'test_illustrator_bridge']]
    commands += [[pwsh, '-NoProfile', '-File', 'tests/' + name + '.ps1'] for name in ['test_shop_scripts', 'test_update_helper']]
    for command in commands:
        subprocess.run(command, cwd=paths['root'], check=True)
    print('Contributor checks passed. Physical Illustrator/print/cut checks remain separate.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'start', 'check', 'info'])
    parser.add_argument('--test-tools', action='store_true', help='Install Playwright for browser regression tests during setup')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=8765, help='8765 is required by the Illustrator bridge')
    args = parser.parse_args()
    paths = locations()
    if args.action == 'info':
        print(json.dumps({key:str(value) for key,value in paths.items()}, indent=2))
        return 0
    require_runtime()
    if args.action == 'setup':
        setup(paths, args.test_tools)
    else:
        if not ready(paths):
            raise ValueError('Run contributor.py setup first for this revision of requirements.txt.')
        if args.action == 'check':
            check(paths)
        else:
            if not 1024 <= args.port <= 65535:
                raise ValueError('Choose a local port from 1024 to 65535.')
            return subprocess.call(start_command(paths, args.port, args.no_browser), cwd=paths['root'])
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
