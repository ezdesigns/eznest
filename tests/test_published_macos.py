"""Disposable-runner acceptance of signed Mac package bytes, never source mode.

Only an explicitly dispatched job may install. Owner revocation is mandatory
outside this script, including on failure. Cleanup is CI containment, not a
product uninstaller. It refuses to race a timed-out Apple Installer transaction.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from xml.etree import ElementTree

VERSION = '1.0.0-rc.5'
TEAM = 'JC6858UYM9'
LABEL = 'io.jeezlabs.eznest'
PACKAGE_ID = LABEL + '.shop'
ACCOUNT = '_eznest'
APP = Path('/Applications/eznest.app')
EXE = APP / 'Contents/MacOS/eznest'
DATA = Path('/Library/Application Support/eznest')
DAEMON = Path('/Library/LaunchDaemons/io.jeezlabs.eznest.plist')
OWNED_PATHS = (APP, DATA, Path('/Library/Application Support/eznest-update-control'),
               Path('/Library/Application Support/eznest-update-recovery'), DAEMON,
               DAEMON.with_name(DAEMON.name + '.new'),
               Path('/Library/Application Support/eznest-install.lock'))
PACKAGE_NAME = f'eznest-shop-arm64-{VERSION}.pkg'
SAFE_ENV = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL': 'C'}


class AcceptanceError(Exception):
    """Only static, credential-free diagnostics may use this exception."""


def require(condition, message):
    if not condition:
        raise AcceptanceError(message)


def runner_guard():
    require(sys.platform == 'darwin' and platform.machine() == 'arm64'
            and int(platform.mac_ver()[0].split('.')[0]) >= 26
            and os.environ.get('CI') == 'true'
            and os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
            and os.environ.get('RUNNER_OS') == 'macOS'
            and os.environ.get('GITHUB_REPOSITORY') == 'ezdesigns/eznest'
            and re.fullmatch(r'[0-9]+', os.environ.get('GITHUB_RUN_ID', '')),
            'Only a disposable GitHub-hosted macOS 26 arm64 runner may install.')
    root = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    require(root.is_dir() and root != Path('/'), 'Invalid runner temporary directory.')
    return root


def command(args, *, accepted=(0,), timeout=30):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=timeout, env=SAFE_ENV)
    require(result.returncode in accepted, 'A required system verification failed.')
    require(len(result.stdout or '') + len(result.stderr or '') < 1_048_576,
            'Unexpected system verification output.')
    return result


def sudo_python(source):
    # These snippets contain fixed paths and emit only bounded public results.
    return command(['/usr/bin/sudo', '-n', sys.executable, '-I', '-c', source])


def write_json(path, value):
    temporary = path.with_suffix('.new')
    with temporary.open('x', encoding='utf-8') as handle:
        os.chmod(temporary, 0o600)
        json.dump(value, handle, indent=2)
        handle.write('\n')
    temporary.replace(path)


def valid_hash(value):
    require(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value),
            'Supply a lower-case SHA-256 for the reviewed signed package.')
    return value


def verify_package(package, expected):
    valid_hash(expected)
    st = package.lstat()
    require(stat.S_ISREG(st.st_mode) and 0 < st.st_size <= 300_000_000,
            'Package must be a bounded regular file.')
    with package.open('rb') as handle:
        require(hashlib.file_digest(handle, 'sha256').hexdigest() == expected,
                'Downloaded package checksum mismatch.')
    check = command(['/usr/sbin/pkgutil', '--check-signature', str(package)])
    output = check.stdout + '\n' + check.stderr
    identities = re.findall(r'^\s*1\.\s+Developer ID Installer: [^\n]+\(([A-Z0-9]{10})\)\s*$', output, re.M)
    statuses = re.findall(r'^\s*Status: (.+?)\s*$', output, re.M)
    require(identities == [TEAM] and len(statuses) == 1 and statuses[0] in (
        'signed by a certificate trusted by macOS',
        'signed by a developer certificate issued by Apple for distribution'),
        'The package lacks the approved Developer ID Installer publisher.')
    check = command(['/usr/sbin/spctl', '--assess', '--type', 'install', '--verbose=2', str(package)])
    require('source=Notarized Developer ID' in check.stdout + check.stderr,
            'The package did not pass notarized Gatekeeper assessment.')
    command(['/usr/bin/xcrun', 'stapler', 'validate', str(package)])
    with tempfile.TemporaryDirectory(prefix='eznest-acceptance-package-') as folder:
        expanded = Path(folder) / 'expanded'
        command(['/usr/sbin/pkgutil', '--expand', str(package), str(expanded)])
        info = expanded / 'PackageInfo'
        require(info.is_file() and not info.is_symlink() and info.stat().st_size <= 65536,
                'Package identity is missing or oversized.')
        raw = info.read_bytes()
        require(b'<!DOCTYPE' not in raw and b'<!ENTITY' not in raw, 'Unsafe package metadata.')
        value = ElementTree.fromstring(raw)
        require(value.tag == 'pkg-info' and value.get('identifier') == PACKAGE_ID
                and value.get('version') == VERSION.split('-', 1)[0], 'Unexpected package identity.')


def job_pid():
    result = command(['/usr/bin/sudo', '-n', '/bin/launchctl', 'print', 'system/' + LABEL], accepted=(0, 113))
    if result.returncode == 113:
        return None
    pids = re.findall(r'^\s*pid = ([1-9][0-9]*)$', result.stdout, re.M)
    return int(pids[0]) if len(pids) == 1 else 0


def preflight():
    require(not any(path.exists() or path.is_symlink() for path in OWNED_PATHS),
            'Existing shop files found; refusing ownership.')
    for record in ('/Users/' + ACCOUNT, '/Groups/' + ACCOUNT):
        result = command(['/usr/bin/dscl', '.', '-read', record], accepted=(0, 56))
        require(result.returncode == 56, 'Existing service identity found; refusing ownership.')
    require(job_pid() is None, 'Existing launchd job found; refusing ownership.')
    result = command(['/usr/sbin/pkgutil', '--pkg-info', PACKAGE_ID], accepted=(0, 1))
    require(result.returncode == 1, 'Existing installer receipt found; refusing ownership.')
    with socket.socket() as sock:
        require(sock.connect_ex(('127.0.0.1', 8765)) != 0,
                'Port 8765 is already in use; refusing ownership.')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise AcceptanceError('The installed local API must not redirect.')


def download(root):
    # A short-lived URL grants only this draft asset, not repository write access.
    # Never print its signed query or include it in an artifact.
    url = os.environ.pop('EZ_NEST_MACOS_CANDIDATE_URL', '')
    parsed = urlsplit(url)
    require(parsed.scheme == 'https' and parsed.netloc == 'release-assets.githubusercontent.com'
            and not parsed.fragment and bool(parsed.query), 'A scoped GitHub candidate download URL is required.')
    package = root / PACKAGE_NAME
    http = build_opener(ProxyHandler({}), NoRedirect())
    owned = False
    try:
        with http.open(Request(url), timeout=30) as response:
            require(response.status == 200, 'Candidate download did not succeed.')
            length = response.headers.get('Content-Length')
            require(length is not None and length.isdigit() and 0 < int(length) <= 300_000_000,
                    'Candidate download size is missing or exceeds the package bound.')
            expected = int(length)
            with package.open('xb') as target:
                owned = True
                count = 0
                deadline = time.monotonic() + 120
                while True:
                    require(time.monotonic() < deadline, 'Candidate download timed out.')
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    require(count <= expected, 'Candidate download exceeded its declared size.')
                    target.write(chunk)
                require(count == expected, 'Candidate download was incomplete.')
    except Exception:
        if owned:
            package.unlink(missing_ok=True)
        raise
    print('DOWNLOAD_PASS: private candidate fetched; signature and hash checks still required.')


class LocalAPI:
    def __init__(self):
        self.token = None
        self.http = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, body=None):
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['X-EZ-Token'] = self.token
        request = Request('http://127.0.0.1:8765' + path,
                          data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            response = self.http.open(request, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(2_000_001)
            require(len(raw) <= 2_000_000, 'Unexpected local API response size.')
            return response.status, json.loads(raw)

    def session(self):
        status, value = self.request('/api/session')
        require(status == 200 and value.get('app') == 'eznest' and value.get('version') == VERSION
                and value.get('shopService') is True and value.get('maintenance') is False
                and value.get('pid') == job_pid() and value['pid'] > 0,
                'Local session does not match the installed limited service.')
        token = value.get('token')
        require(isinstance(token, str) and re.fullmatch('[A-Za-z0-9_-]{43}', token),
                'Local session token is missing.')
        self.token = token
        return value

    def healthy(self):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                return self.session()
            except (OSError, ValueError, AcceptanceError):
                time.sleep(1)
        raise AcceptanceError('Installed service did not become healthy.')


def last_ok():
    result = sudo_python("import json; from pathlib import Path; "
                         "p=Path('/Library/Application Support/eznest/output-checkin.json'); "
                         "assert p.is_file() and not p.is_symlink() and p.stat().st_size < 16384; "
                         "v=json.loads(p.read_text())['lastOkAt']; "
                         "assert type(v) is int and v >= 0; print(v)")
    require(re.fullmatch(r'[0-9]+\s*', result.stdout), 'Invalid successful check-in time.')
    return int(result.stdout)


def fresh_checkin(api, previous):
    status, value = api.request('/api/telemetry/output/check-in', {})
    timestamp = last_ok()
    require(status == 200 and value.get('ok') is True and not value.get('devMode')
            and timestamp > previous, 'A fresh successful production check-in was not observed.')
    return timestamp


def verify_installed_identity():
    details = command(['/usr/bin/codesign', '--display', '--verbose=4', str(APP)])
    text = details.stdout + details.stderr
    flags = re.search(r'\bflags=0x([0-9a-fA-F]+)\b', text)
    require(re.findall(r'^TeamIdentifier=([A-Z0-9]{10})$', text, re.M) == [TEAM]
            and 'Authority=Developer ID Application:' in text and flags
            and int(flags[1], 16) & 0x10000, 'Installed app has an unexpected publisher/runtime.')
    command(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--all-architectures',
             f'-R=anchor apple generic and certificate leaf[subject.OU] = "{TEAM}"', str(APP)])
    assessment = command(['/usr/sbin/spctl', '--assess', '--type', 'execute', '--verbose=2', str(APP)])
    require('source=Notarized Developer ID' in assessment.stdout + assessment.stderr,
            'Installed app is not notarized.')
    with (APP / 'Contents/Info.plist').open('rb') as handle:
        info = plistlib.load(handle)
    require(info.get('CFBundleIdentifier') == LABEL and info.get('EzNestVersion') == VERSION
            and info.get('EzNestShopService') is True, 'Unexpected installed bundle metadata.')
    with EXE.open('rb') as handle:
        header = handle.read(8)
    require(header == b'\xcf\xfa\xed\xfe' + struct.pack('<I', 0x0100000C),
            'Installed executable is not native arm64.')
    result = sudo_python("import plistlib,pwd,grp,os; from pathlib import Path; "
        "p=Path('/Library/LaunchDaemons/io.jeezlabs.eznest.plist'); "
        "assert p.stat().st_uid == 0 and not p.stat().st_mode & 0o077; "
        "v=plistlib.loads(p.read_bytes()); "
        "assert v['UserName']==v['GroupName']=='_eznest' and v['InitGroups'] is False; "
        "assert v['ProgramArguments']==['/Applications/eznest.app/Contents/MacOS/eznest',"
        "'--no-browser','--web','--shop-service','--data-dir','/Library/Application Support/eznest','--port','8765']; "
        "assert not v.get('EnvironmentVariables'); "
        "u=pwd.getpwnam('_eznest');g=grp.getgrnam('_eznest'); "
        "assert 350 <= u.pw_uid < 500 and u.pw_uid==u.pw_gid==g.gr_gid; "
        "assert u.pw_shell=='/usr/bin/false' and u.pw_dir=='/var/empty' and not g.gr_mem; print(u.pw_uid)")
    uid = int(result.stdout.strip())
    memberships = command(['/usr/bin/id', '-G', ACCOUNT]).stdout.split()
    require(memberships and all(value.isdigit() for value in memberships)
            and not ({0, 80} & set(map(int, memberships))),
            'The service account unexpectedly belongs to wheel or admin.')
    actual = command(['/bin/ps', '-p', str(job_pid()), '-o', 'uid=']).stdout.strip()
    require(actual == str(uid), 'launchd is not running as the limited service account.')


def install(root, expected):
    package = root / PACKAGE_NAME
    verify_package(package, expected)
    preflight()
    marker = root / 'eznest-macos-owned.json'
    require(not marker.exists(), 'This job already owns an installation attempt.')
    ownership = {'runId': os.environ['GITHUB_RUN_ID'], 'installerSettled': False}
    write_json(marker, ownership)
    receipt = dict(version=VERSION, architecture='arm64', teamId=TEAM, sha256=expected,
                   runId=os.environ['GITHUB_RUN_ID'], hostLabel=socket.gethostname(),
                   installed=False, gated=False, paired=False, restarted=False,
                   nested=False, sharingOff=False, revoked=False, cleanup=False)
    write_json(root / 'eznest-macos-acceptance.json', receipt)
    # Installer can delegate to installd. Timeout cannot establish transaction
    # completion; refuse later cleanup rather than delete underneath that daemon.
    process = subprocess.Popen(['/usr/bin/sudo', '-n', '/usr/sbin/installer', '-pkg', str(package), '-target', '/'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, env=SAFE_ENV, start_new_session=True)
    try:
        code = process.wait(timeout=240)
    except subprocess.TimeoutExpired:
        command(['/usr/bin/sudo', '-n', '/bin/kill', '-TERM', '--', '-' + str(process.pid)])
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            command(['/usr/bin/sudo', '-n', '/bin/kill', '-KILL', '--', '-' + str(process.pid)])
            process.wait(timeout=15)
        raise AcceptanceError('Installer timed out; cleanup is blocked pending disposable VM teardown.')
    ownership['installerSettled'] = True
    write_json(marker, ownership)
    require(code == 0, 'Signed package installation failed.')
    api = LocalAPI()
    session = api.healthy()
    verify_installed_identity()
    require(session['outputConnection']['ok'] is False
            and session['outputConnection']['devMode'] is False
            and api.request('/api/state')[0] == 403,
            'Fresh installed workspace is not locked.')
    receipt.update(installed=True, gated=True)
    write_json(root / 'eznest-macos-acceptance.json', receipt)
    print('INSTALL_PASS: signed downloaded package installed as a limited, unpaired service.')


def connect(root):
    code = os.environ.pop('EZ_NEST_MACOS_ACCEPTANCE_CODE', '')
    require(re.fullmatch('[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5}', code),
            'An owner-approved one-time test-shop code is required.')
    receipt = json.loads((root / 'eznest-macos-acceptance.json').read_text())
    require(receipt['installed'] and receipt['gated'], 'Installed acceptance evidence is incomplete.')
    api = LocalAPI(); api.session()
    status, value = api.request('/api/telemetry/output/pair', {'code': code})
    require(status == 200 and value.get('configured') is True and value.get('enabled') is False,
            'The installed test host did not pair with sharing off.')
    receipt['paired'] = True
    receipt['pairedAt'] = int(time.time())
    write_json(root / 'eznest-macos-acceptance.json', receipt)
    status, value = api.request('/api/telemetry/output/pair', {'code': code})
    code = None
    require(status == 400 and value.get('reason') == 'consumed', 'Consumed pairing code was not rejected.')
    paired = last_ok(); time.sleep(2)
    receipt['checkedInAt'] = fresh_checkin(api, paired)
    before = api.session()['pid']; time.sleep(2)
    command(['/usr/bin/sudo', '-n', '/bin/launchctl', 'kickstart', '-k', 'system/' + LABEL])
    session = api.healthy()
    require(session['pid'] != before, 'The service process did not restart.')
    receipt['restartCheckedInAt'] = fresh_checkin(api, receipt['checkedInAt'])
    receipt['restarted'] = True
    status, sharing = api.request('/api/telemetry/output')
    require(status == 200 and sharing.get('configured') is True and sharing.get('enabled') is False,
            'Activity sharing unexpectedly enabled.')
    receipt['sharingOff'] = True
    job = {'parts': [{'id': 'synthetic-square', 'quantity': 2,
                     'points': [[0,0],[20,0],[20,20],[0,20]]}],
           'settings': {'width':100,'gap':2,'margin':2,'seconds':1,'rotations':[0],'seed':42}}
    require(api.request('/api/solve', job)[0] == 200, 'Synthetic nesting did not start.')
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        time.sleep(1)
        status, state = api.request('/api/state')
        if state.get('status') != 'running':
            break
    require(status == 200 and state.get('status') == 'ready'
            and len(state['result']['placements']) == 2, 'Synthetic two-piece nesting did not finish.')
    receipt['nested'] = True
    write_json(root / 'eznest-macos-acceptance.json', receipt)
    print('CONNECT_PASS: owner must now revoke the exact host in the sanitized receipt.')


def verify_revoked(root):
    receipt = json.loads((root / 'eznest-macos-acceptance.json').read_text())
    require(all(receipt[key] for key in ('paired', 'restarted', 'nested', 'sharingOff')),
            'Connection evidence is incomplete.')
    api = LocalAPI(); api.session()
    time.sleep(60)
    for attempt in range(4):
        status, value = api.request('/api/telemetry/output/check-in', {})
        if status == 200 and value.get('state') == 'revoked' and value.get('ok') is False:
            break
        if attempt < 3:
            time.sleep(120)
    require(status == 200 and value.get('state') == 'revoked' and value.get('ok') is False,
            'Owner revocation was not observed within the check-in budget.')
    require(api.request('/api/state')[0] == 403 and api.request('/api/solve', {})[0] == 403,
            'Revoked host still accepts work.')
    receipt['revoked'] = True
    write_json(root / 'eznest-macos-acceptance.json', receipt)
    print('REVOCATION_PASS: owner revocation closed the installed host gate.')


# Fixed paths only; preflight + run-specific marker establish exclusive VM ownership.
CLEANUP = '''import os, pathlib, pwd, shutil, signal, subprocess, time
paths = ['/Applications/eznest.app', '/Library/Application Support/eznest',
 '/Library/Application Support/eznest-update-control', '/Library/Application Support/eznest-update-recovery',
 '/Library/LaunchDaemons/io.jeezlabs.eznest.plist', '/Library/LaunchDaemons/io.jeezlabs.eznest.plist.new',
 '/Library/Application Support/eznest-install.lock']
env = {'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LC_ALL':'C'}
def run(args):
 return subprocess.run(args, capture_output=True, env=env, timeout=30)
job='system/io.jeezlabs.eznest'
if run(['/bin/launchctl','print',job]).returncode == 0:
 assert run(['/bin/launchctl','bootout',job]).returncode == 0
assert run(['/bin/launchctl','print',job]).returncode == 113
try: uid=pwd.getpwnam('_eznest').pw_uid
except KeyError: uid=None
if uid is not None:
 assert 350 <= uid < 500
 def owned_pids():
  rows=run(['/bin/ps','-axo','pid=,uid=']).stdout.decode().splitlines()
  return [int(row.split()[0]) for row in rows if len(row.split())==2 and int(row.split()[1])==uid]
 for sig in (signal.SIGTERM,signal.SIGKILL):
  for pid in owned_pids():
   try: os.kill(pid,sig)
   except ProcessLookupError: pass
  time.sleep(1)
 assert not owned_pids()
assert shutil.rmtree.avoids_symlink_attacks
for item in paths:
 path=pathlib.Path(item)
 if path.is_symlink() or path.is_file(): path.unlink()
 elif path.exists(): shutil.rmtree(path)
for record in ('/Users/_eznest','/Groups/_eznest'):
 if run(['/usr/bin/dscl','.', '-read',record]).returncode == 0:
  assert run(['/usr/bin/dscl','.', '-delete',record]).returncode == 0
 assert run(['/usr/bin/dscl','.', '-read',record]).returncode == 56
if run(['/usr/sbin/pkgutil','--pkg-info','io.jeezlabs.eznest.shop']).returncode == 0:
 assert run(['/usr/sbin/pkgutil','--forget','io.jeezlabs.eznest.shop']).returncode == 0
assert run(['/usr/sbin/pkgutil','--pkg-info','io.jeezlabs.eznest.shop']).returncode == 1
assert not any(pathlib.Path(p).exists() or pathlib.Path(p).is_symlink() for p in paths)
print('CI_CLEANUP_PASS')
'''


def cleanup(root):
    marker = root / 'eznest-macos-owned.json'
    if not marker.exists():
        return
    ownership = json.loads(marker.read_text())
    require(ownership.get('runId') == os.environ['GITHUB_RUN_ID']
            and ownership.get('installerSettled') is True,
            'Installer transaction is not known to have settled; refuse racing cleanup.')
    try:
        api = LocalAPI(); api.session(); api.request('/api/telemetry/output/disconnect', {})
    except Exception:
        pass  # Never substitutes for remote owner revocation.
    result = sudo_python(CLEANUP)
    require(result.stdout.strip() == 'CI_CLEANUP_PASS', 'Owned CI cleanup did not complete.')
    with socket.socket() as sock:
        require(sock.connect_ex(('127.0.0.1', 8765)) != 0, 'Service listener remains after cleanup.')
    receipt_path = root / 'eznest-macos-acceptance.json'
    receipt = json.loads(receipt_path.read_text())
    receipt['cleanup'] = True
    write_json(receipt_path, receipt)
    print('CLEANUP_PASS: owned CI service, files and account removed; no product uninstaller claim.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('Download', 'Install', 'Connect', 'VerifyRevoked', 'Cleanup'))
    args = parser.parse_args()
    try:
        root = runner_guard()
        if args.phase == 'Download':
            download(root)
        elif args.phase == 'Install':
            install(root, valid_hash(os.environ.get('EZ_NEST_PACKAGE_SHA256')))
        elif args.phase == 'Connect':
            connect(root)
        elif args.phase == 'VerifyRevoked':
            verify_revoked(root)
        else:
            cleanup(root)
    except AcceptanceError as error:
        print(f'Mac acceptance {args.phase} failed: {error}', file=sys.stderr)
        return 1
    except Exception:
        # HTTP/session/process exceptions may contain tokens: never print them.
        print(f'Mac acceptance {args.phase} failed. Inspect the sanitized receipt; '
              'owner must revoke any created test host.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
