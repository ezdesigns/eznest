"""Build a macOS bundle; optional Developer ID signing, never publish."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys

from build_windows import STATIC

ROOT = Path(__file__).resolve().parent
PACKAGES = ('spyrrow', 'shapely', 'numpy', 'pypdf', 'pypdfium2', 'pillow',
            'charset-normalizer', 'defusedxml', 'pyinstaller', 'pyinstaller-hooks-contrib')
DOCUMENTS = ('LICENSE', 'NOTICE', 'THIRD_PARTY.md', 'version.json', 'CHANGELOG.md')
ENTRY = '''import os
import sys

# The Windows release selector/helper is not a macOS updater. Even saved update
# preferences must not cause this pilot to fetch or apply Windows packages.
from macos_service_runtime import service_edition
if not service_edition():
    os.environ['EZ_NEST_UPDATES'] = '0'
if any(flag in sys.argv for flag in ('--apply-update', '--request-shop-update', '--update-confirm')):
    raise SystemExit('This macOS pilot uses manual application replacement; automatic updates are unavailable.')
if sys.argv[1:2] not in (['--document-worker'], ['--nest-worker'], ['--telemetry-worker'], ['--macos-service-helper'], ['--macos-update-worker'], ['--request-macos-update'], ['eznest-update://install']) and '--web' not in sys.argv:
    sys.argv.append('--web')
from launcher import main
raise SystemExit(main())
'''


def pinned_requirements(root):
    """Read the existing pins; packaging does not maintain another version list."""
    pins = {}
    for filename in ('requirements.txt', 'requirements-build.txt'):
        for line in (root / filename).read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or line == '-r requirements.txt':
                continue
            if not re.fullmatch(r'[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+', line):
                raise ValueError(f'Expected a pinned build requirement in {filename}.')
            name, version = line.split('==')
            pins[name] = version
    if set(pins) != set(PACKAGES):
        raise ValueError('Build dependency inventory changed; review the macOS metadata and license list.')
    return pins


def preflight(out, root=ROOT):
    if sys.platform != 'darwin' or sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8:
        raise RuntimeError('Build with 64-bit Python 3.12 on macOS.')
    arch = platform.machine()
    if arch not in ('arm64', 'x86_64'):
        raise RuntimeError('Use a native arm64 or x86_64 Python build; universal builds are not supported.')
    out, root = Path(out).resolve(), Path(root).resolve()
    if out == root or root in out.parents or out in root.parents:
        raise ValueError('Choose a new build directory outside the source folder and its parents.')
    if out.exists():
        raise ValueError('The output directory already exists. Choose a new directory; nothing was replaced.')
    for name, version in pinned_requirements(root).items():
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError as error:
            raise RuntimeError(f'Install the pinned requirement: {name}=={version}') from error
        if installed != version:
            raise RuntimeError(f'Install the pinned requirement: {name}=={version}')
    return out, arch


def collect_licenses(destination):
    """Collect repository, dependency and Python notices before bundle signing."""
    shutil.copytree(ROOT / 'licenses', destination)
    for name in PACKAGES:
        distribution = metadata.distribution(name)
        for entry in distribution.files or []:
            path = Path(entry)
            if not any(part.lower().startswith(('license', 'licence', 'copying', 'notice', 'copyright')) for part in path.parts):
                continue
            source = Path(distribution.locate_file(entry))
            if not source.is_file():
                continue
            parts = [part for part in path.parts if part not in ('.', '..', path.anchor)]
            target = destination / name / Path(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    candidates = (Path(sys.base_prefix) / 'LICENSE.txt',
                  Path(sys.base_prefix) / 'lib' / 'python3.12' / 'LICENSE.txt')
    license_file = next((path for path in candidates if path.is_file()), None)
    if license_file is None:
        raise RuntimeError('Python LICENSE.txt is missing from this build interpreter; do not distribute an incomplete bundle.')
    shutil.copy2(license_file, destination / 'Python-LICENSE.txt')


def bundle_spec(root, out, arch, version, *, service_edition=False, codesign_identity=None):
    """Include notices and version metadata before signing all collected code."""
    signing_team(codesign_identity)
    short_version = version.split('-', 1)[0]
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', version):
        raise ValueError('version.json must contain the application release version.')
    data = [(str(root / name), '.') for name in dict.fromkeys([*STATIC, *DOCUMENTS])]
    data += [(str(root / 'fonts'), 'fonts'), (str(out / 'licenses'), 'licenses'),
             (str(out / 'BUILD.json'), '.')]
    return f'''# Generated by build_macos.py. Public identity only; no credentials.
from PyInstaller.utils.hooks import collect_all, copy_metadata
datas = {data!r}
binaries = []
hiddenimports = ['launcher', 'installer_update', 'output_gate']
for module in ('spyrrow', 'pypdfium2', 'pypdfium2_raw'):
    module_data, module_binaries, module_imports = collect_all(module)
    datas += module_data
    binaries += module_binaries
    hiddenimports += module_imports
for package in {PACKAGES[:-2]!r}:
    datas += copy_metadata(package)
a = Analysis([{str(out / 'macos_entry.py')!r}], pathex=[{str(root)!r}],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['tkinter'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='eznest',
          console=False, strip=False, upx=False, target_arch={arch!r},
          argv_emulation={service_edition!r},
          codesign_identity={codesign_identity!r}, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='eznest')
app = BUNDLE(coll, name='eznest.app', bundle_identifier='io.jeezlabs.eznest',
             version={short_version!r},
             info_plist={{'CFBundleShortVersionString': {short_version!r},
                         'CFBundleVersion': {short_version!r},
                         'EzNestVersion': {version!r},
                         'EzNestShopService': {service_edition!r},
                         **{({'CFBundleURLTypes':[{'CFBundleURLName':'io.jeezlabs.eznest.update','CFBundleURLSchemes':['eznest-update']}]} if service_edition else {})!r},
                         'NSHighResolutionCapable': True, 'LSUIElement': True}})
'''


def source_fingerprint(root=ROOT):
    """Fingerprint packaged application inputs, including uncommitted Python code."""
    paths = set(root.glob('*.py'))
    paths.update(root / name for name in set(STATIC) | set(DOCUMENTS))
    for folder in ('fonts', 'licenses'):
        paths.update(path for path in (root / folder).rglob('*') if path.is_file())
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode() + b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()


def signing_team(identity):
    if identity is None:
        return None
    match = re.fullmatch(r'Developer ID Application: [^\r\n]+ \(([A-Z0-9]{10})\)', identity)
    if not match:
        raise ValueError('Use the full Developer ID Application identity, including Team ID.')
    return match[1]


def verify_signature(app, team):
    details = subprocess.check_output(['/usr/bin/codesign', '--display', '--verbose=4', str(app)],
                                      stderr=subprocess.STDOUT, text=True)
    flags = re.search(r'\bflags=0x([0-9a-fA-F]+)\b', details)
    if (re.findall(r'^TeamIdentifier=([A-Z0-9]{10})$', details, re.MULTILINE) != [team]
            or 'Authority=Developer ID Application:' not in details
            or flags is None or not int(flags[1], 16) & 0x10000):
        raise RuntimeError('The bundle must have the requested Developer ID and hardened runtime.')
    requirement = f'anchor apple generic and certificate leaf[subject.OU] = "{team}"'
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--all-architectures',
                    '-R=' + requirement, str(app)], check=True)


def build(out, *, service_edition=False, codesign_identity=None):
    team = signing_team(codesign_identity)
    out, arch = preflight(out)
    info = json.loads((ROOT / 'version.json').read_text(encoding='utf-8'))
    spec = bundle_spec(ROOT, out, arch, info['version'], service_edition=service_edition,
                       codesign_identity=codesign_identity)
    # Exclusive creation owns all subsequent writes and preserves previous builds.
    out.mkdir(parents=True, exist_ok=False)
    collect_licenses(out / 'licenses')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    manifest = {'app': info, 'commit': commit, 'python': sys.version,
                'architecture': arch, 'buildOS': platform.mac_ver()[0],
                'sourceSha256': source_fingerprint(),
                'sourceDirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
                'signing': codesign_identity or 'ad-hoc pilot only', 'notarized': False,
                'automaticUpdates': False,
                'shopServiceEdition': service_edition,
                'dependencies': {name: metadata.version(name) for name in PACKAGES}}
    (out / 'BUILD.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (out / 'macos_entry.py').write_text(ENTRY, encoding='utf-8')
    spec_path = out / 'eznest-macos.spec'
    spec_path.write_text(spec, encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--distpath', str(out / 'dist'),
                    '--workpath', str(out / 'work'), str(spec_path)], cwd=ROOT, check=True)
    app = out / 'dist' / 'eznest.app'
    if not (app / 'Contents' / 'MacOS' / 'eznest').is_file():
        raise RuntimeError('PyInstaller did not create the expected macOS application.')
    # Signature checks do not substitute for the separate notarization gate.
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    if team:
        verify_signature(app, team)
    archive = out / f'eznest-macos-{arch}-{info["version"]}.zip'
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app), str(archive)], check=True)
    with archive.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    print(f'Build candidate: {archive}\nNot notarized or approved for public rollout.')
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='New dedicated directory outside the source tree')
    parser.add_argument('--service-edition', action='store_true', help='Build the system shop-host edition; installation still requires Developer ID signing and notarization')
    parser.add_argument('--codesign-identity', help='Full Developer ID Application identity from the local Keychain')
    args = parser.parse_args()
    build(args.out, service_edition=args.service_edition, codesign_identity=args.codesign_identity)


if __name__ == '__main__':
    main()
