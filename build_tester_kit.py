"""Wrap a verified trial with a local tester guide. Does not rebuild the app."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(source, out, kit_id):
    source, out = Path(source).resolve(), Path(out).resolve()
    archive = out.with_suffix('.zip')
    if out.exists() or archive.exists():
        raise ValueError('Choose a new output folder and ZIP; previous kits are preserved.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,79}', kit_id):
        raise ValueError('Use a short kit ID with letters, numbers and hyphens.')
    files = json.loads((source / 'FILES.sha256.json').read_text())
    for name, expected in files.items():
        path = (source / name).resolve()
        if not path.is_relative_to(source) or not path.is_file() or digest(path) != expected:
            raise ValueError('Trial file failed verification: ' + name)
    manifest = json.loads((source / 'BUILD.json').read_text())
    if manifest.get('channel') != 'local-shop-trial' or manifest.get('automaticUpdates') is not False:
        raise ValueError('Use an isolated shop-trial package.')
    if digest(source / 'app/eznest.exe') != manifest['exeSha256']:
        raise ValueError('Executable does not match the verified trial build.')
    # Copy only files in the verified distribution, never later test jobs or data.
    for name in files:
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)
    substitutions = {'{{KIT_ID}}':kit_id, '{{APP_BUILD}}':manifest['buildId'], '{{VERSION}}':manifest['version']}
    guide = (ROOT / 'tester/START HERE.html').read_text(encoding='utf-8')
    for key, value in substitutions.items():
        guide = guide.replace(key, html.escape(value))
    (out / 'START HERE.html').write_text(guide, encoding='utf-8')
    for name in ('CODEX START PROMPT.txt', 'CODEX UPDATE PROMPT.txt', 'UPDATES.txt'):
        content = (ROOT / 'tester' / name).read_text(encoding='utf-8')
        for key, value in substitutions.items():
            content = content.replace(key, value)
        (out / name).write_text(content, encoding='utf-8')
    for name in ('feedback.js', 'tester.css'):
        shutil.copy2(ROOT / 'tester' / name, out / name)
    shutil.copy2(out / 'START Shop Test.cmd', out / 'START EZ NEST.cmd')
    (out / 'READ FIRST.txt').write_text(
        'EZ NEST PRIVATE TESTER KIT\nKit: ' + kit_id + '\n\n'
        '1. Extract the whole ZIP to a new folder on a separate Windows x64 PC.\n'
        '2. Open START HERE.html for the short walkthrough and feedback form.\n'
        '   For Codex help, open this folder in a local Codex chat and paste\n'
        '   the prompt from CODEX START PROMPT.txt.\n'
        '3. Double-click START EZ NEST.cmd. No Python or installer is needed.\n'
        '4. Try Examples/sample-artwork.svg, then a copy of your prepared file.\n'
        '5. Keep output in TEST Output. Use OPEN Test Output.cmd to view it.\n'
        '6. Save a feedback report from START HERE.html and send it to the person\n'
        '   who gave you this kit. Nothing is sent automatically.\n\n'
        'Use STOP Shop Test.cmd before updates. Keep the old kit and back up\n'
        '%LOCALAPPDATA%\\eznest-shop-trial while stopped. Updates use a new folder.\n'
        'Material presets are stored in your browser; use the same browser.\n\n'
        'Code changes do not update this copy automatically. See UPDATES.txt\n'
        'and CODEX UPDATE PROMPT.txt when your organizer sends a newer kit.\n\n'
        'This unsigned private trial is not production certification. If Windows\n'
        'blocks it, report the warning; do not disable security protections.\n'
        'Leave production installations and live print folders untouched.\n'
        'See START HERE.html for limits, Illustrator steps and print/cut checks.\n', encoding='utf-8')
    kit = {'kitId':kit_id, 'appBuildId':manifest['buildId'], 'appExeSha256':manifest['exeSha256'],
           'sourceVersion':manifest['version'], 'distribution':'private-windows-x64-test',
           'appRebuilt':False, 'feedback':'local-download-only',
           'basePackageManifestSha256':digest(source / 'FILES.sha256.json')}
    (out / 'KIT.json').write_text(json.dumps(kit, indent=2), encoding='utf-8')
    hashes = {p.relative_to(out).as_posix():digest(p) for p in sorted(out.rglob('*')) if p.is_file()}
    (out / 'FILES.sha256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file():
                z.write(p, (Path(out.name) / p.relative_to(out)).as_posix())
    archive.with_suffix('.zip.sha256').write_text(digest(archive) + '  ' + archive.name + '\n')
    return {'folder':str(out), 'zip':str(archive), 'sha256':digest(archive), 'files':len(hashes)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--kit-id', required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.source, args.out, args.kit_id)))
