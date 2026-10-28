"""Build the portable Windows app. Run using the project's pinned build venv."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
STATIC=['production.html','queue.css','queue-app.js','queue-core.js','production-features.js','cut-mapping.js','shop-profiles.js','svg-io.js','sample-artwork.svg','sample.json','version.json','CHANGELOG.md','app.js','style.css','web.html','web.css','web.js','tester-results.js']
INNO_SETUP_URL='https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe'

def pinned_distribution(name, version):
    try:
        installed=metadata.version(name)
    except metadata.PackageNotFoundError:
        raise RuntimeError(f'Missing {name}=={version}. From the repository root, with 64-bit Python 3.12, run: py -3.12 -m pip install -r requirements.txt -r requirements-build.txt') from None
    if installed!=version:
        raise RuntimeError(f'{name} {installed} is installed; this build needs exactly {name}=={version}. Use a clean 64-bit Python 3.12 virtual environment and install requirements.txt and requirements-build.txt.')

def check_build_directory(out):
    if any(ch.isspace() for ch in str(out)):
        raise ValueError(r'Choose a build directory with no spaces. Example: C:\eznest-build')
    if out==ROOT or ROOT in out.parents:
        raise ValueError('Choose a build directory outside the source folder.')

def iscc_supported(version):
    """None means the file version could not be read. Inno Setup 6.3 added ExecAndLogOutput."""
    if version is None:
        return True
    return tuple(version[:2])>=(6, 3)

def iscc_file_version(path):
    if os.name!='nt':
        return None
    import ctypes
    from ctypes import wintypes
    size=ctypes.windll.version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    buf=ctypes.create_string_buffer(size)
    if not ctypes.windll.version.GetFileVersionInfoW(str(path), 0, size, buf):
        return None
    value=ctypes.c_void_p(); length=wintypes.UINT()
    if not ctypes.windll.version.VerQueryValueW(buf, '\\', ctypes.byref(value), ctypes.byref(length)):
        return None
    class VS_FIXEDFILEINFO(ctypes.Structure):
        _fields_=[('dwSignature',wintypes.DWORD),('dwStrucVersion',wintypes.DWORD),('dwFileVersionMS',wintypes.DWORD),('dwFileVersionLS',wintypes.DWORD),
                  ('dwProductVersionMS',wintypes.DWORD),('dwProductVersionLS',wintypes.DWORD),('dwFileFlagsMask',wintypes.DWORD),('dwFileFlags',wintypes.DWORD),
                  ('dwFileOS',wintypes.DWORD),('dwFileType',wintypes.DWORD),('dwFileSubtype',wintypes.DWORD),('dwFileDateMS',wintypes.DWORD),('dwFileDateLS',wintypes.DWORD)]
    info=ctypes.cast(value, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
    ms, ls=info.dwFileVersionMS, info.dwFileVersionLS
    return ((ms>>16)&0xFFFF, ms&0xFFFF, (ls>>16)&0xFFFF, ls&0xFFFF)

def find_iscc():
    """Prefer the newest Inno Setup 6. An older ISCC earlier on PATH must not win."""
    candidates=[]
    for key, fallback in (('ProgramFiles(x86)', r'C:\Program Files (x86)'), ('ProgramFiles', r'C:\Program Files')):
        candidates.append(Path(os.environ.get(key, fallback))/'Inno Setup 6'/'ISCC.exe')
    found=shutil.which('ISCC')
    if found:
        candidates.append(Path(found))
    best=None; best_version=None; seen=set()
    for path in candidates:
        key=str(path).casefold()
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        version=iscc_file_version(path)
        if best is None or (version or (0,))>(best_version or (0,)):
            best, best_version=path, version
    if best is None:
        return None
    if not iscc_supported(best_version):
        found_version='.'.join(str(part) for part in best_version)
        raise RuntimeError(f'Inno Setup {found_version} at {best} is older than 6.3, so installer/eznest.iss cannot compile (ExecAndLogOutput). Install Inno Setup 6.7.3, the version the Windows installer workflow uses: {INNO_SETUP_URL}')
    return str(best), best_version

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True,help='Dedicated new build directory outside the source folder')
    parser.add_argument('--portable-only',action='store_true',help='Build the portable app without compiling an installer')
    args=parser.parse_args();out=args.out.resolve()
    if sys.platform!='win32' or sys.version_info[:2]!=(3,12) or struct.calcsize('P')!=8:raise RuntimeError('Build with 64-bit Python 3.12 on Windows.')
    check_build_directory(out)
    for requirement in (ROOT/'requirements.txt').read_text().splitlines():
        if not requirement.strip() or requirement.lstrip().startswith('#'):
            continue
        name,version=requirement.split('==')
        pinned_distribution(name, version)
    for name,version in [('pyinstaller','6.22.3'),('pyinstaller-hooks-contrib','2026.7')]:
        pinned_distribution(name, version)
    out.mkdir(parents=True,exist_ok=True)
    if (out/'dist'/'eznest').exists():raise ValueError('The output already contains a build. Choose a new directory.')
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--windowed','--name','eznest','--icon',str(ROOT/'assets'/'eznest.ico'),'--distpath',str(out/'dist'),'--workpath',str(out/'work'),'--specpath',str(out),'--collect-all','spyrrow','--collect-all','pypdfium2','--collect-all','pypdfium2_raw','--hidden-import','installer_update','--hidden-import','output_pairing','--hidden-import','output_credential','--exclude-module','tkinter']
    for name in STATIC:command+=['--add-data',f'{ROOT/name}{os.pathsep}.']
    command+=['--add-data',f'{ROOT/"fonts"}{os.pathsep}fonts']
    for name in ['spyrrow','shapely','numpy','pypdf','pypdfium2','pillow','charset-normalizer']:command+=['--copy-metadata',name]
    subprocess.run(command+[str(ROOT/'launcher.py')],cwd=ROOT,check=True)
    release=out/'dist'/'eznest'
    for name in ['START HERE.txt','Stop EZ Nest.cmd','Stop EZ Nest.ps1','eznest-web.bat','eznest-server.cmd','THIRD_PARTY.md','version.json','CHANGELOG.md','LICENSE','NOTICE']:shutil.copy2(ROOT/name,release/name)
    shutil.copy2(ROOT/'installer'/'install-shop.ps1',release/'install-shop.ps1')
    shutil.copy2(ROOT/'installer'/'uninstall-shop.ps1',release/'uninstall-shop.ps1')
    shutil.copy2(ROOT/'installer'/'update-shop.ps1',release/'update-shop.ps1')
    (release/'examples').mkdir();shutil.copy2(ROOT/'sample-artwork.svg',release/'examples'/'sample-artwork.svg')
    shutil.copytree(ROOT/'licenses',release/'licenses')
    shutil.copytree(ROOT/'illustrator',release/'illustrator')
    licenses=release/'licenses'
    for name in ['spyrrow','shapely','numpy','pypdf','pypdfium2','pillow','charset-normalizer','pyinstaller']:
        distribution=metadata.distribution(name)
        for entry in distribution.files or []:
            path=Path(entry)
            if any(part.lower().startswith(('license','licence','copying','notice','copyright')) for part in path.parts):
                source=Path(distribution.locate_file(entry))
                if not source.is_file():continue
                target=licenses/name/Path(*[part for part in path.parts if part not in ('.','..')]);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    shutil.copy2(Path(sys.base_prefix)/'LICENSE.txt',licenses/'Python-LICENSE.txt')
    manifest={name:metadata.version(name) for name in ['spyrrow','shapely','numpy','pypdf','pypdfium2','pillow','charset-normalizer','pyinstaller','pyinstaller-hooks-contrib']}
    manifest['python']=sys.version;manifest['app']=json.loads((ROOT/'version.json').read_text())
    # Portable dependency list. The setup pin (version, commit, exe sha256) is installer/Output/BUILD.json.
    (release/'BUILD.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(f'Portable app: {release}')
    if os.environ.get('WINDOWS_CERT_BASE64', '').strip():
        subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT/'installer'/'sign-payload.ps1'), '-App', str(release/'eznest.exe')], check=True)
    if not args.portable_only:compile_setup(release)


def compile_setup(release):
    """Compile eznest-setup.exe when Inno Setup 6.3 or newer is installed. A missing compiler leaves the portable folder."""
    found=find_iscc()
    if not found:
        print('Inno Setup 6.3 or newer is not installed. The portable folder is ready. Install Inno Setup 6.7.3 and run this build again: '+INNO_SETUP_URL)
        return
    iscc, version=found
    print('Inno Setup: '+iscc+(' ' + '.'.join(str(part) for part in version) if version else ''))
    version = json.loads((ROOT / 'version.json').read_text(encoding='utf-8'))['version']
    subprocess.run([iscc, '/DMyAppVersion=' + version, '/DSourceDir=' + str(release), str(ROOT / 'installer' / 'eznest.iss')], cwd=ROOT, check=True)
    setup = ROOT / 'installer' / 'Output' / 'eznest-setup.exe'
    pin = write_release_pin(setup.parent / 'BUILD.json', version, git_commit(), setup)
    print('Installer: ' + str(setup))
    print('commit: ' + pin['commit'])
    print('sha256: ' + pin['sha256'])


def git_commit():
    for name in ('EZ_NEST_COMMIT', 'GITHUB_SHA'):
        value = os.environ.get(name, '').strip()
        if value:
            return value
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def write_release_pin(dest, version, commit, exe_path):
    """Write version, commit, and the setup exe's SHA-256 beside the exe.

    The hash is of the finished installer, so this file stays outside the exe.
    """
    exe = Path(exe_path)
    pin = {
        'version': version,
        'commit': commit,
        'sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
    }
    Path(dest).write_text(json.dumps(pin, indent=2) + '\n', encoding='utf-8')
    return pin

if __name__=='__main__':main()

