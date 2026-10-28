"""Prepare a Mac shop package from an already signed, notarized service app.

This builds an unsigned package for the separate signing/notarization gate; it
does not read identities, submit binaries, publish or install anything.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

from macos_service_config import verify_publisher
from macos_service_install import tree_size


def scripts(*, lan=False):
    if type(lan) is not bool:
        raise ValueError('Select shop-network access explicitly.')
    # Installer can target another volume. All application paths are fixed to
    # the live boot volume, so reject that mode before any service mutation.
    preinstall = '#!/bin/sh\nset -eu\n[ "$3" = / ] || { echo "Install only on the running Mac." >&2; exit 1; }\n'
    postinstall = preinstall + '''script_dir=$(/usr/bin/dirname "$0")
candidate="$script_dir/candidate.app"
exec /usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin LC_ALL=C \\
  "$candidate/Contents/MacOS/eznest" --macos-service-helper install \\
  --candidate "$candidate"''' + (' --lan' if lan else '') + '\n'
    return {'preinstall':preinstall, 'postinstall':postinstall}


def build(app, out, *, team_id, lan=False):
    if sys.platform != 'darwin':
        raise ValueError('Package on macOS with the reviewed system packaging tools.')
    app, out = Path(app).resolve(), Path(out).resolve()
    if out.exists() or out == app or app in out.parents or out in app.parents:
        raise ValueError('Choose a new dedicated package directory outside the bundle.')
    info = verify_publisher(app,expected_team=team_id)
    with (app/'Contents/Info.plist').open('rb') as handle:
        if plistlib.load(handle).get('EzNestShopService') is not True:
            raise ValueError('Build the shared shop service edition first.')
    tree_size(app,links=True)
    out.mkdir(parents=True,exist_ok=False)
    folder=out/'scripts'; folder.mkdir()
    candidate=folder/'candidate.app'
    shutil.copytree(app,candidate,symlinks=True)
    if verify_publisher(candidate,expected_team=team_id) != info:
        raise ValueError('The packaged application changed during copying.')
    for name,source in scripts(lan=lan).items():
        path=folder/name; path.write_text(source,encoding='utf-8'); path.chmod(0o755)
    package=out/f'eznest-shop-{info["architecture"]}-{info["version"]}-unsigned.pkg'
    subprocess.run(['/usr/bin/pkgbuild','--nopayload','--scripts',str(folder),
                    '--identifier','io.jeezlabs.eznest.shop','--version',info['version'].split('-',1)[0],
                    str(package)],check=True)
    with package.open('rb') as handle: digest=hashlib.file_digest(handle,'sha256').hexdigest()
    (out/'PACKAGE.json').write_text(json.dumps({**info,'sha256':digest,'lanOnFirstInstall':lan,
        'packageSigned':False,'packageNotarized':False,'installed':False},indent=2)+'\n')
    print('Unsigned package prepared. Developer ID Installer signing, package notarization, and clean-Mac acceptance remain required.')
    return package


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--team-id',required=True)
    parser.add_argument('--lan',action='store_true')
    args=parser.parse_args()
    build(args.app,args.out,team_id=args.team_id,lan=args.lan)


if __name__=='__main__': main()
