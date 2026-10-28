"""macOS privileged adapter. Never instantiated by source or pilot execution."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

import macos_service_config as config
from macos_service_install import Installer, tree_size


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError('The local service cannot redirect installer requests.')


class MacSystem:
    app, data = config.APP, config.DATA
    recovery, control = config.RECOVERY, config.CONTROL

    def __init__(self):
        if sys.platform != 'darwin' or not getattr(sys, 'frozen', False) or os.geteuid() != 0:
            raise ValueError('Use the signed installer with administrator authorization on macOS.')
        # The helper itself is a bundled executable; no system Python, shell
        # startup files, development imports or user-selected executables run.
        self.verify(Path(sys.executable).parent.parent.parent)
        self.control_gid = None
        self.uid = None
        self.http = build_opener(ProxyHandler({}), NoRedirect())

    def run(self, arguments, *, accepted=(0,)):
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=30,
                                env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin', 'LC_ALL':'C'})
        if result.returncode not in accepted:
            raise RuntimeError('The administrator service operation failed; keep the recovery receipt for inspection.')
        if len(result.stdout or '') > 262144:
            raise ValueError('Unexpected system command output.')
        return result

    def parents(self, path):
        for parent in reversed(path.parents):
            st = parent.lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o002 or (st.st_mode & 0o020 and st.st_gid not in (0,80)):
                raise ValueError('Installation ancestors must be real administrator-controlled directories.')

    def private_dir(self, path, mode=0o700, gid=0):
        self.parents(path)
        try:
            st = path.lstat()
        except FileNotFoundError:
            path.mkdir(mode=mode)
            os.chown(path,0,gid)
            return
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_gid != gid or stat.S_IMODE(st.st_mode) != mode:
            raise ValueError('Unexpected ownership or permissions on a service control directory.')

    @contextmanager
    def lock(self):
        import fcntl
        path = Path('/Library/Application Support/eznest-install.lock')
        self.parents(path)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1:
                raise ValueError('Unsafe installer lock.')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def verify(self, app):
        tree_size(app, links=True)
        info = config.verify_publisher(app)
        with (app/'Contents/Info.plist').open('rb') as handle:
            if plistlib.load(handle).get('EzNestShopService') is not True:
                raise ValueError('The package requires the shared shop service edition.')
        return info

    def installed_configuration(self):
        self.parents(config.DAEMON)
        try:
            config.DAEMON.lstat()
        except FileNotFoundError:
            return None
        return config.read_launch_configuration()

    def ensure_account(self, *, recovery=False):
        import pwd
        import grp
        try:
            account = pwd.getpwnam(config.ACCOUNT)
        except KeyError:
            if recovery:
                raise ValueError('The service account is missing; administrator repair is required.')
            occupied = set()
            for database, key in (('/Users','UniqueID'),('/Groups','PrimaryGroupID')):
                result = self.run(['/usr/bin/dscl','.', '-list', database, key])
                for line in result.stdout.splitlines():
                    value = line.split()[-1:]
                    if value and value[0].isdigit(): occupied.add(int(value[0]))
            number = next((value for value in range(350,500) if value not in occupied), None)
            if number is None:
                raise ValueError('No unused system service identity is available.')
            # Refuse an existing group rather than silently claiming it.
            try: grp.getgrnam(config.ACCOUNT)
            except KeyError: pass
            else: raise ValueError('The service group already exists without its expected account.')
            group = '/Groups/'+config.ACCOUNT
            user = '/Users/'+config.ACCOUNT
            for record, key, value in ((group,'PrimaryGroupID',str(number)),
                    (user,'UniqueID',str(number)),(user,'PrimaryGroupID',str(number)),
                    (user,'NFSHomeDirectory','/var/empty'),(user,'UserShell','/usr/bin/false'),
                    (user,'IsHidden','1'),(user,'Password','*'),
                    (user,'AuthenticationAuthority',';DisabledUser;')):
                self.run(['/usr/bin/dscl','.', '-create', record, key, value])
            account = pwd.getpwnam(config.ACCOUNT)
        group = grp.getgrnam(config.ACCOUNT)
        if (not 350 <= account.pw_uid < 500 or account.pw_gid != group.gr_gid or
                account.pw_uid != account.pw_gid or account.pw_shell != '/usr/bin/false' or
                account.pw_dir != '/var/empty' or group.gr_mem):
            raise ValueError('The existing service identity has unexpected privileges.')
        memberships = self.run(['/usr/bin/id','-G',config.ACCOUNT]).stdout.split()
        # Directory Services includes implicit memberships such as everyone
        # and localaccounts. Do not mistake those for an installation failure.
        # The root-owned launchd configuration enforces InitGroups=false;
        # runtime separately verifies real/effective UID and primary GID.
        if not memberships or any(not value.isdigit() for value in memberships) or {0,80} & set(map(int,memberships)):
            raise ValueError('The service account cannot be a wheel or administrator member.')
        self.uid, self.control_gid = account.pw_uid, account.pw_gid

    def prepare(self, recovery=False):
        self.ensure_account(recovery=recovery)
        self.private_dir(self.recovery)
        self.private_dir(self.control, 0o750, self.control_gid)
        for path in (self.app, self.data, config.DAEMON): self.parents(path)
        if self.data.exists() or self.data.is_symlink():
            st=self.data.lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != self.uid or st.st_gid != self.control_gid or st.st_mode & 0o027:
                raise ValueError('The shared data directory has unexpected ownership or permissions.')

    def clear_closed_recovery(self):
        self.private_dir(self.recovery)
        allowed = {'receipt.json','receipt.json.new','incoming.app','previous.app','previous.plist',
                   'data-copy','data-backup','failed.app','failed-data'}
        if any(path.name not in allowed for path in self.recovery.iterdir()):
            raise ValueError('Unexpected recovery contents; administrator inspection is required.')
        for path in self.recovery.iterdir():
            if path.is_symlink(): raise ValueError('Unexpected recovery link.')
            if path.is_dir(): shutil.rmtree(path)
            else: path.unlink()

    def seal_application(self, root):
        tree_size(root, links=True)
        for path in [root, *root.rglob('*')]:
            st=path.lstat()
            os.chown(path,0,0,follow_symlinks=False)
            if not stat.S_ISLNK(st.st_mode):
                os.chmod(path,0o755 if stat.S_ISDIR(st.st_mode) or st.st_mode & 0o111 else 0o644)

    def sync_tree(self, root):
        paths=[root,*root.rglob('*')]
        for path in reversed(paths):
            if path.is_symlink(): continue
            fd=os.open(path,os.O_RDONLY | os.O_NOFOLLOW)
            try: os.fsync(fd)
            finally: os.close(fd)

    def sync_directory(self, path):
        fd=os.open(path,os.O_RDONLY | os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)

    def preserve_data_ownership(self, source, target):
        for path in [source,*source.rglob('*')]:
            st=path.lstat()
            if st.st_uid != self.uid or st.st_gid != self.control_gid or st.st_mode & 0o027 or (stat.S_ISREG(st.st_mode) and st.st_nlink != 1):
                raise ValueError('Shared data has unexpected ownership, permissions or hard links.')
            os.chown(target/path.relative_to(source),st.st_uid,st.st_gid,follow_symlinks=False)

    def create_data(self):
        self.data.mkdir(mode=0o750)
        os.chown(self.data,self.uid,self.control_gid)

    def save_configuration(self, path, value):
        with path.open('xb') as handle:
            os.fchmod(handle.fileno(),0o600)
            plistlib.dump(value,handle)
            handle.flush(); os.fsync(handle.fileno())

    def write_configuration(self, value):
        temporary=config.DAEMON.with_name(config.DAEMON.name+'.new')
        if temporary.exists() or temporary.is_symlink():
            st=temporary.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or stat.S_IMODE(st.st_mode)!=0o600 or st.st_nlink!=1:
                raise ValueError('Unsafe interrupted service configuration.')
            temporary.unlink()
        self.save_configuration(temporary,value)
        os.replace(temporary,config.DAEMON)
        self.sync_directory(config.DAEMON.parent)

    def restore_configuration(self, path):
        self.write_configuration(config.read_launch_configuration(path))

    def remove_configuration(self):
        config.DAEMON.unlink(missing_ok=True)
        self.sync_directory(config.DAEMON.parent)

    def job(self):
        result=self.run(['/bin/launchctl','print','system/'+config.LABEL],accepted=(0,113))
        if result.returncode == 113: return None
        found=re.findall(r'^\s*pid = ([1-9][0-9]*)$',result.stdout,re.MULTILINE)
        return int(found[0]) if len(found)==1 else 0

    def stop(self):
        if self.job() is None: return
        self.run(['/bin/launchctl','bootout','system/'+config.LABEL])
        for _ in range(40):
            if self.job() is None: return
            time.sleep(.25)
        raise RuntimeError('The old service did not stop; application files were not replaced.')

    def start(self):
        self.run(['/bin/launchctl','bootstrap','system',str(config.DAEMON)])

    def request(self, path, payload=None, token=None):
        headers={'Content-Type':'application/json'}
        if token: headers['X-EZ-Token']=token
        body=None if payload is None else json.dumps(payload).encode()
        with self.http.open(Request('http://127.0.0.1:8765'+path,data=body,headers=headers),timeout=2) as response:
            raw=response.read(4097)
        if len(raw)>4096: raise ValueError('Unexpected service response.')
        value=json.loads(raw)
        if not isinstance(value,dict): raise ValueError('Unexpected service response.')
        return value

    def session(self):
        value=self.request('/api/session')
        if value.get('app')!='eznest' or value.get('shopService') is not True or value.get('pid') != self.job():
            raise ValueError('The listener does not match the installed launchd service.')
        token=value.get('token')
        if not isinstance(token,str) or not re.fullmatch('[A-Za-z0-9_-]{43}',token):
            raise ValueError('Invalid local service session.')
        return value

    def claim_idle(self,ticket):
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            session=self.session()
            response=self.request('/api/macos-service/claim',{'ticket':ticket},session['token'])
            if response.get('ready') is True and response.get('pid')==session['pid']: return
            time.sleep(1)
        raise RuntimeError('The shop is busy. Finish or discard the reviewed job, then run the installer again.')

    def cancel_claim(self,ticket):
        if self.job() in (None,0): return
        session=self.session()
        response=self.request('/api/macos-service/cancel',{'ticket':ticket},session['token'])
        if response.get('ok') is not True: raise ValueError('The service update lease could not be cancelled.')

    def confirm_health(self,version):
        deadline=time.monotonic()+60
        stable_pid=None; stable_since=None
        while time.monotonic()<deadline:
            try:
                session=self.session()
                if session.get('version')!=version or session.get('maintenance') is not True:
                    raise ValueError('The candidate is not in guarded startup.')
                if session['pid']!=stable_pid:
                    stable_pid=session['pid']; stable_since=time.monotonic()
                if time.monotonic()-stable_since>=10: return
            except (OSError,ValueError):
                stable_pid=stable_since=None
            time.sleep(.5)
        raise RuntimeError('The service did not remain healthy; recovery is required.')

    def read_receipt(self,path):
        st=path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or stat.S_IMODE(st.st_mode)!=0o600 or st.st_size>16384:
            raise ValueError('Unsafe installation recovery receipt.')
        value=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value,dict) or set(value)!={'phase','ticket','previous','candidate','hadService'}:
            raise ValueError('Invalid installation recovery receipt.')
        if value['phase'] not in ('preparing','stopping','stopped','swapping','testing','committed','rolled-back'):
            raise ValueError('Unknown installation recovery phase.')
        if type(value['hadService']) is not bool or not isinstance(value['ticket'],str) or not re.fullmatch('[a-f0-9]{32}',value['ticket']):
            raise ValueError('Invalid installation recovery identity.')
        return value


def main(argv):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('install','recover'))
    parser.add_argument('--candidate',type=Path)
    parser.add_argument('--lan',action='store_true')
    args=parser.parse_args(argv)
    if args.operation=='install' and args.candidate is None:
        parser.error('install needs the signed package candidate')
    if args.operation=='recover' and (args.candidate is not None or args.lan):
        parser.error('recovery uses only the protected existing transaction')
    try:
        system=MacSystem()
        installer=Installer(system)
        if args.operation=='recover': installer.recover()
        else: installer.install(args.candidate,lan=args.lan)
        return 0
    except Exception:
        # Windowed frozen apps have no sys.stderr. Keep Installer noninteractive
        # and do not put paths, tokens or system-command output in its log.
        try:
            os.write(2,b'Ez Nest installation did not complete. Preserve the recovery receipt and ask the administrator to inspect it.\n')
        except OSError:
            pass
        return 1
