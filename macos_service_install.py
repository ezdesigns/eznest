"""Administrator-only, fixed-path Mac shop installation transaction.

The package invokes this from its signed frozen app. It never runs the web
server as root. Tests supply a temporary filesystem and a fake system adapter;
the command-line entry point cannot redirect privileged writes with arguments
or environment variables.
"""
import json
import os
from pathlib import Path
import secrets
import shutil
import stat

import macos_service_config as config


def atomic_json(path, value, mode=0o600, gid=None):
    temporary = path.with_name(path.name + '.new')
    try:
        stale = temporary.lstat()
    except FileNotFoundError:
        pass
    else:
        # The installer lock serializes this fixed root-controlled directory.
        # A power loss may leave its private pre-rename file behind.
        if not stat.S_ISREG(stale.st_mode) or stale.st_uid != os.geteuid() or stale.st_mode & 0o027 or stale.st_nlink != 1:
            raise ValueError('Unsafe interrupted transaction file.')
        temporary.unlink()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        if gid is not None:
            os.fchown(fd, 0, gid)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def tree_size(root, *, links=False):
    """Reject special files and external links before a privileged copy.

    The stopped service's data has no link semantics. App bundles may contain
    framework links, but every target must remain inside that exact bundle.
    """
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('An intact directory is required.')
    total = 0
    for path in root.rglob('*'):
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode):
            if not links or not path.resolve(strict=True).is_relative_to(root.resolve()):
                raise ValueError('External or data symlinks cannot enter an installation snapshot.')
        elif stat.S_ISREG(st.st_mode):
            total += st.st_size
        elif not stat.S_ISDIR(st.st_mode):
            raise ValueError('Special files cannot enter an installation snapshot.')
    return total


class Installer:
    """System adapter owns launchd/account/trust checks; this owns recovery order."""
    def __init__(self, system):
        self.system = system
        self.app, self.data = system.app, system.data
        self.recovery, self.control = system.recovery, system.control
        self.receipt = self.recovery / 'receipt.json'

    def record(self, phase, **extra):
        self.state.update(phase=phase, **extra)
        atomic_json(self.receipt, self.state)

    def lease(self, phase):
        atomic_json(self.control / 'transaction.json',
                    {'ticket': self.state['ticket'], 'phase': phase},
                    mode=0o640, gid=self.system.control_gid)

    def release(self):
        (self.control / 'transaction.json').unlink(missing_ok=True)

    def move(self, source, destination):
        os.replace(source, destination)
        self.system.sync_directory(destination.parent)
        if source.parent != destination.parent:
            self.system.sync_directory(source.parent)

    def install(self, candidate, *, lan=False):
        with self.system.lock():
            return self._install(Path(candidate), lan=lan)

    def _install(self, candidate, *, lan):
        # Trust, account/path validation and free-space checks precede outage.
        candidate_info = self.system.verify(candidate)
        old_config = self.system.installed_configuration()
        old_info = self.system.verify(self.app) if old_config else None
        if old_info:
            config.upgrade_candidate(old_info, candidate_info)
        elif self.app.exists() or self.data.exists():
            raise ValueError('An existing application or data directory needs explicit administrator migration.')
        self.system.prepare()
        if self.receipt.exists():
            prior = self.system.read_receipt(self.receipt)
            if prior.get('phase') not in ('committed', 'rolled-back'):
                raise ValueError('An interrupted installation needs administrator recovery first.')
            self.state = prior
            self._recover()
            # Only our closed transaction directory is reusable. Data from a
            # failed candidate was never opened for accepted shop operations.
            self.system.clear_closed_recovery()
        app_size = tree_size(candidate, links=True)
        data_size = tree_size(self.data) if old_config else 0
        if shutil.disk_usage(self.recovery).free < app_size * 2 + data_size * 2 + 256 * 1024 * 1024:
            raise ValueError('Insufficient space for staging and data-preserving recovery.')
        self.state = {'phase': 'preparing', 'ticket': secrets.token_hex(16),
                      'previous': old_info, 'candidate': candidate_info,
                      'hadService': bool(old_config)}
        self.record('preparing')
        incoming = self.recovery / 'incoming.app'
        try:
            shutil.copytree(candidate, incoming, symlinks=True)
            self.system.seal_application(incoming)
            # Verify the sealed copy; changes during the source copy cannot
            # cause unsigned bytes to be installed as root.
            if self.system.verify(incoming) != candidate_info:
                raise ValueError('The staged application changed.')
            self.system.sync_tree(incoming)
            if old_config:
                self.system.save_configuration(self.recovery / 'previous.plist', old_config)
                self.lease('awaiting')
                self.system.claim_idle(self.state['ticket'])
            self.record('stopping')
            # Survive a reboot at ANY later swap/configuration instruction.
            # The in-memory HTTP claim alone disappears when launchd restarts.
            self.lease('testing')
            self.system.stop()
            self.record('stopped')
            if old_config:
                # Recheck after the daemon and its process group have stopped.
                tree_size(self.data)
                shutil.copytree(self.data, self.recovery / 'data-copy', symlinks=False)
                self.system.preserve_data_ownership(self.data, self.recovery / 'data-copy')
                self.system.sync_tree(self.recovery / 'data-copy')
                self.move(self.recovery / 'data-copy', self.recovery / 'data-backup')
                self.record('swapping')
                self.move(self.app, self.recovery / 'previous.app')
            else:
                self.record('swapping')
                self.system.create_data()
            self.move(incoming, self.app)
            self.system.write_configuration(old_config or config.launch_configuration(lan=lan))
            self.record('testing')
            self.system.start()
            self.system.confirm_health(candidate_info['version'])
            # Durable commit precedes opening admission. Recovery after this
            # point must not roll back material writes accepted by the new app.
            self.record('committed')
            self.release()
            return {'ok': True, 'version': candidate_info['version']}
        except BaseException:
            self._recover()
            raise

    def recover(self):
        with self.system.lock():
            self.system.prepare(recovery=True)
            self.state = self.system.read_receipt(self.receipt)
            return self._recover()

    def _recover(self):
        phase = self.state['phase']
        if phase == 'committed':
            self.release()
            return {'ok': True, 'committed': True}
        if phase == 'rolled-back':
            self.release()
            return {'ok': True, 'rolledBack': True}
        if phase == 'preparing':
            # No app/data/config mutation yet. Cancel the exact root-issued
            # lease without killing an active search when an idle wait expires.
            if (self.control / 'transaction.json').exists():
                self.system.cancel_claim(self.state['ticket'])
            self.record('rolled-back')
            self.release()
            return {'ok': True, 'rolledBack': True}
        self.lease('recovering')
        self.system.stop()
        previous = self.recovery / 'previous.app'
        backup = self.recovery / 'data-backup'
        # Moves are idempotent across a second interruption during recovery.
        if previous.exists():
            if self.app.exists():
                self.move(self.app, self.recovery / 'failed.app')
            self.move(previous, self.app)
        elif not self.state['hadService'] and self.app.exists():
            self.move(self.app, self.recovery / 'failed.app')
        if backup.exists():
            if self.data.exists():
                self.move(self.data, self.recovery / 'failed-data')
            self.move(backup, self.data)
        elif not self.state['hadService'] and self.data.exists():
            self.move(self.data, self.recovery / 'failed-data')
        if self.state['hadService']:
            self.system.restore_configuration(self.recovery / 'previous.plist')
            if self.system.verify(self.app) != self.state['previous']:
                raise ValueError('The recovery application no longer matches the verified previous publisher/version.')
            self.system.start()
            self.system.confirm_health(self.state['previous']['version'])
        else:
            self.system.remove_configuration()
        self.record('rolled-back')
        self.release()
        return {'ok': True, 'rolledBack': True}
