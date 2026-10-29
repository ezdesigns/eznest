"""Signed Mac shop updates: bounded download, then interactive Installer approval.

The unprivileged shop process never invokes Installer or elevates itself. The
interactive installed app rechecks the downloaded package against its publisher.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from functools import lru_cache
from urllib.request import Request, build_opener, ProxyHandler

import macos_service_config as config
import macos_service_runtime as runtime
import shop_deploy as release
from app_info import VERSION
from macos_service_system import NoRedirect

MAX_BYTES = 300_000_000
CHECK_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 180
LOCK = threading.RLock()
STATE = {'busy': False, 'message': '', 'error': None}
THREAD = None
IDENTITY = None


@lru_cache(maxsize=1)
def publisher():
    if (sys.platform != 'darwin' or not getattr(sys,'frozen',False) or
            Path(sys.executable).resolve() != config.EXECUTABLE.resolve() or not runtime.service_edition()):
        raise ValueError('Use the installed, signed Mac shop application.')
    value = config.verify_publisher(config.APP)
    if value['version'] != VERSION:
        raise ValueError('The installed application changed; reopen it.')
    return value


def enabled(directory):
    return (runtime.active() and not runtime.maintenance() and
            release.updates_allowed(directory))


def verify_package(path, team, version, *, runner=subprocess.run):
    config.version_key(version)
    if not isinstance(team,str) or not config.TEAM.fullmatch(team):
        raise ValueError('A valid application publisher is required.')
    st = Path(path).lstat()
    if not stat.S_ISREG(st.st_mode) or not 0 < st.st_size <= MAX_BYTES:
        raise ValueError('The update is not a bounded regular package.')
    env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LC_ALL':'C'}
    result=runner(['/usr/sbin/pkgutil','--check-signature',str(path)],capture_output=True,text=True,timeout=30,env=env)
    output=(result.stdout or '')+'\n'+(result.stderr or '')
    identities=re.findall(r'^\s*1\.\s+Developer ID Installer: [^\n]+\(([A-Z0-9]{10})\)\s*$',output,re.MULTILINE)
    statuses=re.findall(r'^\s*Status: (.+?)\s*$',output,re.MULTILINE)
    trusted_statuses=('signed by a certificate trusted by macOS',
                      'signed by a developer certificate issued by Apple for distribution')
    if result.returncode or identities != [team] or len(statuses)!=1 or statuses[0] not in trusted_statuses:
        raise ValueError('The package must have a trusted Developer ID Installer signature from the application publisher.')
    result=runner(['/usr/sbin/spctl','--assess','--type','install','--verbose=2',str(path)],capture_output=True,text=True,timeout=30,env=env)
    output=(result.stdout or '')+'\n'+(result.stderr or '')
    if result.returncode or 'source=Notarized Developer ID' not in output:
        raise ValueError('The update package must pass notarized Gatekeeper assessment.')
    # Only after trust checks, let the system package reader inspect identity.
    # This is not an installation and never runs the package's scripts.
    with tempfile.TemporaryDirectory(prefix='eznest-package-check-') as temporary:
        expanded=Path(temporary)/'expanded'
        result=runner(['/usr/sbin/pkgutil','--expand',str(path),str(expanded)],capture_output=True,text=True,timeout=30,env=env)
        info=expanded/'PackageInfo'
        if result.returncode or info.is_symlink() or not info.is_file() or info.stat().st_size>65536:
            raise ValueError('The package identity cannot be verified.')
        raw=info.read_bytes()
        if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
            raise ValueError('Unexpected package metadata declarations.')
        root=ET.fromstring(raw)
        if root.tag!='pkg-info' or root.get('identifier')!='io.jeezlabs.eznest.shop' or root.get('version')!=version.split('-',1)[0]:
            raise ValueError('The signed package is not the expected Ez Nest shop version.')


def selected(payload, current, architecture, test_channel):
    config.version_key(current)
    if architecture not in ('arm64','x86_64'):
        raise ValueError('Unsupported Mac update architecture.')
    candidates=[]
    for item in payload if isinstance(payload,list) else [payload]:
        if not isinstance(item,dict) or item.get('draft'):
            continue
        version=str(item.get('tag_name','')).removeprefix('v')
        try: key=config.version_key(version)
        except ValueError: continue
        if (item.get('prerelease') or '-' in version) and not test_channel:
            continue
        if key > config.version_key(current): candidates.append((key,version,item))
    if not candidates: return None
    _,version,item=max(candidates,key=lambda value:value[0])
    name=f'eznest-shop-{architecture}-{version}.pkg'
    assets=[asset for asset in item.get('assets',[]) if isinstance(asset,dict) and asset.get('name')==name]
    if len(assets)!=1:
        raise ValueError('The release needs exactly one signed package for this Mac architecture.')
    return item, assets[0], version


def worker_work(request, *, opener=None):
    """Network-only child. The parent kills it on the whole-operation deadline."""
    opener=opener or build_opener(ProxyHandler({}),release._StopRedirect)
    repo,token=request['repo'],request['token']
    with release._open(opener,request['api'],token,15,repo) as response:
        raw=response.read(1_048_577)
    if len(raw)>1_048_576: raise ValueError('The release catalog is too large.')
    choice=selected(json.loads(raw),request['current'],request['architecture'],request['testChannel'])
    if choice is None: return {'ok':True,'updateAvailable':False,'latest':request['current'],'message':'This is the latest release.'}
    item,asset,version=choice
    url=asset.get('browser_download_url','')
    if not release.release_url_allowed(url,repo=repo): raise ValueError('Unexpected release asset URL.')
    result={'ok':True,'updateAvailable':True,'latest':version,'name':asset['name'],
            'releaseNotes':str(item.get('body',''))[:4000],'message':f'{version} is available.'}
    if request['operation']=='check': return result
    previous_limit=release.MAX_RELEASE_BYTES
    try:
        release.MAX_RELEASE_BYTES=65536
        digest=release.release_checksum(item,asset['name'],opener,token,repo)
    finally:
        release.MAX_RELEASE_BYTES=previous_limit
    hasher=hashlib.sha256(); count=0
    with release._open(opener,url,token,30,repo) as response, open(request['output'],'xb') as handle:
        while True:
            block=response.read(1024*1024)
            if not block: break
            count+=len(block)
            if count>MAX_BYTES: raise ValueError('The package is too large.')
            handle.write(block); hasher.update(block)
        handle.flush(); os.fsync(handle.fileno())
    if not count or not release.checksum_matches(hasher.hexdigest(),digest):
        raise ValueError('The package checksum does not match.')
    return {**result,'sha256':digest,'size':count}


def worker_command():
    if getattr(sys,'frozen',False): return [sys.executable,'--macos-update-worker']
    return [sys.executable,str(Path(__file__).resolve()),'--worker']


def run_worker(request):
    result=subprocess.run(worker_command(),input=json.dumps(request),capture_output=True,text=True,
                          timeout=DOWNLOAD_TIMEOUT if request['operation']=='download' else CHECK_TIMEOUT)
    if result.returncode or len(result.stdout)>16384:
        raise ValueError('The update could not be checked or downloaded.')
    value=json.loads(result.stdout)
    if not isinstance(value,dict) or value.get('ok') is not True:
        raise ValueError('The update could not be checked or downloaded.')
    return value


def folder(directory):
    root=Path(directory)/'macos-updates'
    if root.is_symlink(): raise ValueError('The update directory cannot be a link.')
    root.mkdir(mode=0o700,exist_ok=True)
    return root


def pending(directory):
    root=Path(directory)/'macos-updates'
    path=root/'pending.json'
    if not path.exists(): return None
    st=path.lstat()
    if root.is_symlink() or not stat.S_ISREG(st.st_mode) or st.st_size>4096:
        raise ValueError('Invalid staged update metadata.')
    value=json.loads(path.read_text())
    if not isinstance(value,dict) or set(value)!={'version','sha256','size','name','channel','teamId','architecture'}:
        raise ValueError('Invalid staged update metadata.')
    config.version_key(value['version'])
    if (not isinstance(value['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['sha256']) or
            type(value['size']) is not int or not 0<value['size']<=MAX_BYTES or
            value['architecture'] not in ('arm64','x86_64') or value['channel'] not in ('stable','test') or
            not isinstance(value['teamId'],str) or not config.TEAM.fullmatch(value['teamId']) or
            value['name']!=f'eznest-shop-{value["architecture"]}-{value["version"]}.pkg'):
        raise ValueError('Invalid staged update identity.')
    path=root/(value['sha256']+'.pkg')
    st=path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size!=value['size']:
        raise ValueError('The staged package is missing or changed.')
    return value


def status(directory):
    base={'ok':True,'platform':'macos','current':VERSION,'latest':VERSION,'updateAvailable':False,
          'staged':False,'applyOnRestart':False,'managedSupported':False,'busy':False,'message':'Mac updates are off.','error':None}
    if not enabled(directory): return base
    try:
        with LOCK:
            identity=IDENTITY
            info={**base,**STATE,'managedSupported':identity is not None}
        if identity is None: return info
        value=pending(directory)
        if value and config.version_key(value['version'])>config.version_key(VERSION) and value['channel']==release.load_shop(directory)['channel']:
            if value['teamId']!=identity['teamId'] or value['architecture']!=identity['architecture']:
                raise ValueError('The staged update publisher or architecture changed.')
            info.update(staged=True,stagedVersion=value['version'],latest=value['version'],sha256=value['sha256'],
                        size=value['size'],name=value['name'],message='Update checked. Open the installer on this Mac and approve the administrator prompt.')
        return info
    except (OSError,ValueError,subprocess.SubprocessError):
        return {**base,'message':'A signed, notarized shop installation is required for Mac updates.','error':'Mac update verification is unavailable.'}


def _perform(directory, operation, channel):
    global IDENTITY
    temporary=None
    try:
        # Includes codesign and Gatekeeper; never perform this inside server
        # work admission, including status() calls while first trust is pending.
        identity=publisher()
        with LOCK: IDENTITY=identity
        if not enabled(directory): raise ValueError('Updates are off.')
        request={'operation':operation,'repo':release.repo_for_release(directory),'api':release.release_api(directory),
                 'token':release.github_token(directory),'current':VERSION,'architecture':identity['architecture'],
                 'testChannel':channel=='test'}
        if operation=='download':
            root=folder(directory)
            temporary=root/'download.partial'
            temporary.unlink(missing_ok=True)  # Only this module's serialized incomplete download.
            request['output']=str(temporary)
        result=run_worker(request)
        if not enabled(directory) or release.load_shop(directory)['channel']!=channel:
            raise ValueError('The update preference changed.')
        if operation=='download' and result.get('updateAvailable'):
            verify_package(temporary,identity['teamId'],result['latest'])
            # Trust/signature checks can take time; recheck the operator's gate.
            if not enabled(directory) or release.load_shop(directory)['channel']!=channel:
                raise ValueError('The update preference changed.')
            value={'version':result['latest'],'sha256':result['sha256'],'size':result['size'],'name':result['name'],
                   'channel':channel,'teamId':identity['teamId'],'architecture':identity['architecture']}
            previous=pending(directory)
            destination=root/(value['sha256']+'.pkg')
            os.replace(temporary,destination)
            from installer_update import write_json
            write_json(root/'pending.json',value)
            if previous and previous['sha256']!=value['sha256']:
                (root/(previous['sha256']+'.pkg')).unlink(missing_ok=True)
        with LOCK: STATE.update(result,busy=False,error=None)
    except Exception:
        with LOCK: STATE.update(busy=False,error='The Mac update could not be verified. The current app stays running.',
                                message='The Mac update could not be verified. The current app stays running.')
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def start(directory, operation='check'):
    global THREAD
    if operation not in ('check','download'): raise ValueError('Unknown update operation.')
    if not enabled(directory): return status(directory)
    with LOCK:
        if STATE['busy']: return status(directory)
        STATE.update(busy=True,error=None,message='Downloading and checking the Mac update.' if operation=='download' else 'Checking for a Mac update.')
        THREAD=threading.Thread(target=_perform,args=(directory,operation,release.load_shop(directory)['channel']),
                                name='eznest-macos-update',daemon=True)
        THREAD.start()
    return status(directory)


def package_path(directory):
    info=status(directory)
    if info.get('busy') or not info.get('staged'): raise ValueError('No checked Mac update is ready.')
    return Path(directory)/'macos-updates'/(info['sha256']+'.pkg'), info


def request_install():
    identity=publisher()
    if os.geteuid()==0 or Path('/dev/console').stat().st_uid!=os.getuid():
        raise ValueError('Open the update from the logged-in Mac desktop, not from the system service.')
    http=build_opener(ProxyHandler({}),NoRedirect())
    def read(path):
        with http.open('http://127.0.0.1:8765'+path,timeout=3) as response:
            raw=response.read(16385)
        if len(raw)>16384: raise ValueError('Unexpected shop response.')
        return json.loads(raw)
    session=read('/api/session'); info=read('/api/update')
    if (session.get('app')!='eznest' or session.get('version')!=VERSION or session.get('shopService') is not True or
            info.get('platform')!='macos' or info.get('staged') is not True or info.get('managedSupported') is not True or
            not isinstance(info.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',info['sha256'])):
        raise ValueError('A checked update on the installed shop host is required.')
    config.upgrade_candidate(identity,{**identity,'version':info['stagedVersion']})
    # A private per-invocation directory prevents another local account from
    # replacing this copy. macOS Installer owns the administrator approval.
    with tempfile.TemporaryDirectory(prefix='eznest-update-') as temporary:
        package=Path(temporary)/'eznest-update.pkg'
        request=Request('http://127.0.0.1:8765/api/macos-update/package',headers={'X-EZ-Token':session['token']})
        hasher=hashlib.sha256(); size=0
        with http.open(request,timeout=10) as response, package.open('xb') as handle:
            while True:
                block=response.read(1024*1024)
                if not block: break
                size+=len(block)
                if size>MAX_BYTES: raise ValueError('The package is too large.')
                handle.write(block); hasher.update(block)
        if hasher.hexdigest()!=info['sha256']: raise ValueError('The update changed during copying.')
        verify_package(package,identity['teamId'],info['stagedVersion'])
        subprocess.run(['/usr/bin/open','-W','-n','-a','/System/Library/CoreServices/Installer.app',str(package)],check=True)
    return 0


def worker_main():
    try:
        # Windowed frozen apps may expose None for sys.stdin/sys.stdout. The
        # parent supplies explicit OS pipes; use duplicated descriptors.
        with os.fdopen(os.dup(0),'r',encoding='utf-8') as handle:
            raw=handle.read(65537)
        if len(raw)>65536: raise ValueError('Worker input is too large.')
        request=json.loads(raw)
        if request.get('operation') not in ('check','download'): raise ValueError('Unknown operation.')
        result=worker_work(request)
    except Exception:
        result={'ok':False}
    with os.fdopen(os.dup(1),'w',encoding='utf-8') as handle:
        json.dump(result,handle); handle.flush()
    return 0 if result.get('ok') else 1


if __name__=='__main__':
    if sys.argv[1:]!=['--worker']: raise SystemExit('Use the installed app update controls.')
    raise SystemExit(worker_main())
