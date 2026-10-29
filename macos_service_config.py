"""Trust and configuration for the administrator-installed macOS shop service.

This module does not install accounts, write system files, start launchd jobs,
provision credentials, or sign anything. Privileged transactions must validate
these inputs before touching the fixed installation paths.
"""
import os
from pathlib import Path
import plistlib
import re
import stat
import struct
import subprocess

LABEL = 'io.jeezlabs.eznest'
ACCOUNT = '_eznest'
APP = Path('/Applications/eznest.app')
DATA = Path('/Library/Application Support/eznest')
CONTROL = Path('/Library/Application Support/eznest-update-control')
RECOVERY = Path('/Library/Application Support/eznest-update-recovery')
DAEMON = Path('/Library/LaunchDaemons/io.jeezlabs.eznest.plist')
EXECUTABLE = APP / 'Contents/MacOS/eznest'
VERSION = re.compile(r'([0-9]{1,5})\.([0-9]{1,5})\.([0-9]{1,5})(?:-(alpha|beta|rc)\.([0-9]{1,5}))?')
TEAM = re.compile(r'[A-Z0-9]{10}')
CPU_TYPES = {0x01000007: 'x86_64', 0x0100000C: 'arm64'}


def version_key(value):
    match = VERSION.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError('The bundle needs a supported application version.')
    major, minor, patch, kind, sequence = match.groups()
    return (int(major), int(minor), int(patch), {'alpha':0,'beta':1,'rc':2,None:3}[kind], int(sequence or 0))


def metadata(bundle):
    bundle = Path(bundle)
    info_path = bundle / 'Contents/Info.plist'
    executable = bundle / 'Contents/MacOS/eznest'
    if bundle.is_symlink() or not bundle.is_dir() or info_path.is_symlink() or executable.is_symlink():
        raise ValueError('Use an intact application bundle, not linked install paths.')
    if not info_path.is_file() or info_path.stat().st_size > 65536:
        raise ValueError('Application metadata is missing or too large.')
    try:
        info = plistlib.loads(info_path.read_bytes())
    except (ValueError, plistlib.InvalidFileException) as error:
        raise ValueError('Application metadata is invalid.') from error
    if not isinstance(info, dict) or info.get('CFBundleIdentifier') != LABEL or info.get('CFBundleExecutable') != 'eznest':
        raise ValueError('This is not the expected Ez Nest application.')
    version = info.get('EzNestVersion')
    version_key(version)
    if info.get('CFBundleShortVersionString') != version.split('-',1)[0]:
        raise ValueError('Application version metadata does not agree.')
    with executable.open('rb') as handle:
        header = handle.read(8)
    if len(header) != 8 or header[:4] != b'\xcf\xfa\xed\xfe':
        raise ValueError('Use a native architecture-specific 64-bit Mac bundle.')
    architecture = CPU_TYPES.get(struct.unpack('<I',header[4:])[0])
    if architecture is None:
        raise ValueError('Unsupported Mac executable architecture.')
    return {'version':version, 'architecture':architecture}


def verify_publisher(bundle, *, expected_team=None, runner=subprocess.run):
    """Read-only signature/trust checks; ad-hoc pilots can never pass this gate."""
    info = metadata(bundle)
    if expected_team is not None and (not isinstance(expected_team, str) or not TEAM.fullmatch(expected_team)):
        raise ValueError('A valid expected publisher Team ID is required.')
    env = {'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LC_ALL':'C'}
    def run(args):
        result = runner(args, capture_output=True, text=True, timeout=30, env=env)
        if result.returncode != 0:
            raise ValueError('The application publisher or notarization could not be verified.')
        return (result.stdout or '') + '\n' + (result.stderr or '')
    details = run(['/usr/bin/codesign','--display','--verbose=4',str(bundle)])
    teams = re.findall(r'^TeamIdentifier=([A-Z0-9]{10})$',details,re.MULTILINE)
    if len(teams) != 1 or 'Authority=Developer ID Application:' not in details:
        raise ValueError('A Developer ID signed application is required; ad-hoc pilots cannot update the service.')
    team = teams[0]
    if expected_team is not None and team != expected_team:
        raise ValueError('The update publisher does not match the installed application.')
    flags = re.search(r'\bflags=0x([0-9a-fA-F]+)\b',details)
    if flags is None or not int(flags[1],16) & 0x10000:
        raise ValueError('The signed application must use the hardened runtime.')
    # Inline requirement syntax is one argv item, never a shell expression.
    requirement = f'anchor apple generic and certificate leaf[subject.OU] = "{team}"'
    run(['/usr/bin/codesign','--verify','--deep','--strict','--all-architectures','-R='+requirement,str(bundle)])
    assessment = run(['/usr/sbin/spctl','--assess','--type','execute','--verbose=2',str(bundle)])
    if 'source=Notarized Developer ID' not in assessment:
        raise ValueError('A notarized Developer ID application is required.')
    return {**info, 'teamId':team}


def upgrade_candidate(current, candidate):
    if current['teamId'] != candidate['teamId']:
        raise ValueError('The publisher cannot change during a managed update.')
    if current['architecture'] != candidate['architecture']:
        raise ValueError('The update must match the installed architecture.')
    if version_key(candidate['version']) <= version_key(current['version']):
        raise ValueError('Install a newer version; rollback uses only the protected transaction backup.')


def launch_configuration(*, lan=False, environment=None):
    if type(lan) is not bool:
        raise ValueError('Choose shop-network access explicitly.')
    # A launchd plist targets macOS even when generated on a Windows build host.
    args = [EXECUTABLE.as_posix(),'--no-browser','--web','--shop-service','--data-dir',DATA.as_posix(),'--port','8765']
    if lan:
        args.append('--lan')
    config = {'Label':LABEL, 'ProgramArguments':args, 'UserName':ACCOUNT,
              'GroupName':ACCOUNT, 'InitGroups':False, 'RunAtLoad':True, 'KeepAlive':True,
              'ThrottleInterval':30, 'ProcessType':'Background', 'Umask':0o077,
              'WorkingDirectory':DATA.as_posix()}
    # Existing operator-provisioned settings may be preserved by a root-only
    # installer transaction. This function never creates a credential or opt-in.
    if environment is not None:
        if not isinstance(environment,dict) or set(environment)-{'EZ_NEST_OUTPUT_TOKEN','EZ_NEST_OUTPUT_UPLOADS'}:
            raise ValueError('Unexpected service environment configuration.')
        if 'EZ_NEST_OUTPUT_UPLOADS' in environment and environment['EZ_NEST_OUTPUT_UPLOADS'] not in ('0','1'):
            raise ValueError('Invalid OUTPUT delivery gate.')
        token = environment.get('EZ_NEST_OUTPUT_TOKEN')
        if token is not None and (not isinstance(token,str) or not re.fullmatch(r'osa_[A-Za-z0-9_-]{43}',token)):
            raise ValueError('Invalid scoped shop credential format.')
        config['EnvironmentVariables']=dict(environment)
    return config


def read_launch_configuration(path=DAEMON):
    path=Path(path)
    st=path.lstat()
    # Plists can contain an operator-provisioned credential. Require root-only
    # access even when none exists; never echo the plist or its environment.
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077 or st.st_size > 65536:
        raise ValueError('The installed service configuration must be a root-owned private regular file.')
    with path.open('rb') as handle:
        config=plistlib.load(handle)
    if not isinstance(config,dict):
        raise ValueError('Unexpected installed service configuration.')
    args=config.get('ProgramArguments')
    lan=isinstance(args,list) and args[-1:]==['--lan']
    expected=launch_configuration(lan=lan,environment=config.get('EnvironmentVariables'))
    if config != expected:
        raise ValueError('The installed service has unexpected paths, identity or launch arguments.')
    return expected
