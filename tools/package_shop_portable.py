"""Package only a fresh build_windows.py output, never a running shop folder."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

MARKER = {'edition': 'shop-portable', 'schema': 1}
ASSET = 'eznest-shop-windows.zip'
ALLOWED_ROOTS = {'eznest.exe', '_internal', 'version.json', 'BUILD.json', 'CHANGELOG.md',
                 'LICENSE', 'NOTICE', 'THIRD_PARTY.md', 'licenses', 'fonts', 'examples', 'illustrator',
                 'START HERE.txt', 'Stop EZ Nest.cmd', 'Stop EZ Nest.ps1', 'eznest-web.bat',
                 'eznest-server.cmd', 'install-shop.ps1', 'uninstall-shop.ps1', 'update-shop.ps1',
                 'portable-update.json', 'Start EZ Nest.cmd', 'SHOP UPDATES.txt'}
EXCLUDED_ROOTS = {'START HERE.txt', 'Stop EZ Nest.cmd', 'Stop EZ Nest.ps1', 'eznest-web.bat',
                  'eznest-server.cmd', 'install-shop.ps1', 'uninstall-shop.ps1', 'update-shop.ps1'}


def package(app, destination):
    app, destination = Path(app).resolve(), Path(destination).resolve()
    if destination == app or destination.is_relative_to(app):
        raise ValueError('Place download files outside the application.')
    if not (app / 'eznest.exe').is_file() or not (app / '_internal').is_dir():
        raise ValueError('Package a fresh Windows build, not source code.')
    version = json.loads((app / 'version.json').read_text(encoding='utf-8'))['version']
    build = json.loads((app / 'BUILD.json').read_text(encoding='utf-8'))
    if build.get('app', {}).get('version') != version:
        raise ValueError('The build and app versions do not match.')
    paths = list(app.rglob('*'))
    for path in paths:
        relative = path.relative_to(app)
        if (relative.parts[0] not in ALLOWED_ROOTS or path.is_symlink() or path.is_junction()
                or path.name.casefold() in {'shop.json', 'output-folder.json', '.env'}
                or path.suffix.casefold() in {'.sqlite', '.sqlite3', '.db', '.p12', '.pfx', '.pem', '.key'}):
            raise ValueError('Unexpected file in build; package only a fresh application build.')
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / ASSET
    if target.exists() or target.with_suffix('.zip.sha256').exists():
        raise ValueError('The download already exists. Use a new output folder.')
    (app / 'portable-update.json').write_text(json.dumps(MARKER) + '\n', encoding='utf-8')
    (app / 'Start EZ Nest.cmd').write_text('@echo off\nstart "" "%~dp0eznest.exe" --web --lan --data-dir "%~dp0data"\n', encoding='utf-8')
    (app / 'SHOP UPDATES.txt').write_text(
        'Extract this entire ZIP into a new folder under your Windows user account.\n'
        'Open Start EZ Nest.cmd on the host PC. Keep this PC running.\n'
        'Create your shop and invite designers to open its address in their browsers.\n'
        'In Settings > App updates, enable Check for updates. Enable Test channel for previews.\n'
        'Choose Update shop after saving work. Connected browsers receive the new version.\n'
        'Keep the data folder: it contains your shop inventory and settings.\n'
        'Do not extract later releases over a running shop. Use the in-app updater.\n'
        'This user-mode edition does not start at boot or install a Windows service.\n', encoding='utf-8')
    with ZipFile(target, 'x', compression=ZIP_DEFLATED) as archive:
        for path in sorted(app.rglob('*')):
            if path.is_file() and path.relative_to(app).parts[0] not in EXCLUDED_ROOTS:
                archive.write(path, path.relative_to(app).as_posix())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(f'{digest}  {ASSET}\n', encoding='ascii')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(package(args.app, args.destination))
