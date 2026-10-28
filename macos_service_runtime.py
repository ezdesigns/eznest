"""Unprivileged half of the Mac shop service and its update admission gate."""
import json
import os
from pathlib import Path
import plistlib
import secrets
import stat
import sys

from macos_service_config import ACCOUNT, CONTROL, DATA


def service_edition():
    if sys.platform != 'darwin' or not getattr(sys, 'frozen', False):
        return False
    info = Path(sys.executable).parent.parent / 'Info.plist'
    with info.open('rb') as handle:
        return plistlib.load(handle).get('EzNestShopService') is True


def validate_start(args):
    """Fail before importing the server or creating a personal data directory."""
    if not service_edition():
        raise ValueError('Use the administrator-installed shop service edition.')
    import pwd
    account = pwd.getpwnam(ACCOUNT)
    if account.pw_uid == 0 or os.getuid() != account.pw_uid or os.geteuid() != account.pw_uid:
        raise ValueError('The shop service must run as its limited service account.')
    if os.getgid() != account.pw_gid or os.getegid() != account.pw_gid:
        raise ValueError('The shop service must run with its dedicated primary group.')
    # launchd's root-owned configuration enforces InitGroups=false. Modern
    # macOS os.getgroups() reports Directory Services access memberships, not
    # the process's setgroups() credentials; it cannot verify that policy here.
    if (args.shop_test or args.isolated or not args.no_browser or
            args.data_dir != DATA or args.port != 8765):
        raise ValueError('The shop service requires its fixed shared data directory and port.')
    st = DATA.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != account.pw_uid or st.st_mode & 0o027:
        raise ValueError('The shared data directory has unsafe ownership or permissions.')
    os.environ['EZ_NEST_MACOS_SERVICE'] = '1'


def active():
    return sys.platform == 'darwin' and os.environ.get('EZ_NEST_MACOS_SERVICE') == '1'


def transaction():
    """Only root can issue a maintenance lease; the service can only read it.

    A missing lease means normal operation. A malformed/insecure existing lease
    fails closed so a half-finished update cannot admit material/job mutations.
    """
    try:
        parent = CONTROL.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o027:
        raise ValueError('Unsafe service update control directory.')
    path = CONTROL / 'transaction.json'
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o027 or st.st_size > 4096:
        raise ValueError('Unsafe service update transaction.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or set(value) != {'ticket', 'phase'}:
        raise ValueError('Invalid service update transaction.')
    import re
    if not isinstance(value['ticket'], str) or not re.fullmatch('[a-f0-9]{32}', value['ticket']):
        raise ValueError('Invalid service update ticket.')
    if value['phase'] not in ('awaiting', 'testing', 'recovering'):
        raise ValueError('Invalid service update phase.')
    return value


def maintenance():
    if not active():
        return False
    try:
        value = transaction()
        return value is not None and value['phase'] != 'awaiting'
    except (OSError, ValueError):
        return True


def authorize_claim(ticket):
    if not active() or not isinstance(ticket, str):
        raise ValueError('A running Mac shop service is required.')
    value = transaction()
    if value is None or value['phase'] != 'awaiting' or not secrets.compare_digest(ticket, value['ticket']):
        raise ValueError('Administrator update authorization is missing or expired.')
