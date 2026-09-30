"""Build the portable Windows app. Run using the project's pinned build venv."""
import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
STATIC=['production.html','queue.css','queue-app.js','queue-core.js','shop-profiles.js','svg-io.js','sample-artwork.svg','sample.json','version.json','classic.html','app.js','style.css']

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True,help='Dedicated new build directory outside the source folder')
    args=parser.parse_args();out=args.out.resolve()
    if sys.platform!='win32' or sys.version_info[:2]!=(3,12) or struct.calcsize('P')!=8:raise RuntimeError('Build with 64-bit Python 3.12 on Windows.')
    if out==ROOT or ROOT in out.parents:raise ValueError('Choose a build directory outside the source folder.')
    for requirement in (ROOT/'requirements.txt').read_text().splitlines():
        name,version=requirement.split('==')
        if metadata.version(name)!=version:raise RuntimeError(f'Install the pinned requirements: {requirement}')
    for name,version in [('pyinstaller','6.22.3'),('pyinstaller-hooks-contrib','2026.7')]:
        if metadata.version(name)!=version:raise RuntimeError(f'Install {name}=={version}')
    out.mkdir(parents=True,exist_ok=True)
    if (out/'dist'/'eznest').exists():raise ValueError('The output already contains a build. Choose a new directory.')
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--windowed','--name','eznest','--icon',str(ROOT/'assets'/'eznest.ico'),'--distpath',str(out/'dist'),'--workpath',str(out/'work'),'--specpath',str(out),'--collect-all','spyrrow','--exclude-module','tkinter']
    for name in STATIC:command+=['--add-data',f'{ROOT/name}:.']
    for name in ['spyrrow','shapely','numpy']:command+=['--copy-metadata',name]
    subprocess.run(command+[str(ROOT/'launcher.py')],cwd=ROOT,check=True)
    release=out/'dist'/'eznest'
    for name in ['START HERE.txt','Stop EZ Nest.cmd','Stop EZ Nest.ps1','THIRD_PARTY.md','version.json']:shutil.copy2(ROOT/name,release/name)
    (release/'examples').mkdir();shutil.copy2(ROOT/'sample-artwork.svg',release/'examples'/'sample-artwork.svg')
    shutil.copytree(ROOT/'licenses',release/'licenses')
    licenses=release/'licenses'
    for name in ['spyrrow','shapely','numpy','pyinstaller']:
        distribution=metadata.distribution(name)
        for entry in distribution.files or []:
            path=Path(entry)
            if any(part.lower().startswith(('license','licence','copying','notice','copyright')) for part in path.parts):
                source=Path(distribution.locate_file(entry))
                if not source.is_file():continue
                target=licenses/name/Path(*[part for part in path.parts if part not in ('.','..')]);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    shutil.copy2(Path(sys.base_prefix)/'LICENSE.txt',licenses/'Python-LICENSE.txt')
    manifest={name:metadata.version(name) for name in ['spyrrow','shapely','numpy','pyinstaller','pyinstaller-hooks-contrib']}
    manifest['python']=sys.version;manifest['app']=json.loads((ROOT/'version.json').read_text())
    (release/'BUILD.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(f'Portable app: {release}')

if __name__=='__main__':main()
