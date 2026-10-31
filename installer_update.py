"""Install a checked shop build and put the previous one back if it does not start.

The download is eznest-setup.exe, or a zip of the app files. Shop settings and
the hot-folder path live in the data directory and are copied back after the
installer runs. The data directory itself is never replaced.
"""
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from zipfile import ZipFile

import shop_deploy

EXE_NAMES = ('eznest.exe', 'eznest', 'eznest.py')
KEEP_FILES = ('shop.json', 'output-folder.json')
CONFIRM_ATTEMPTS = 3
CONFIRM_TIMEOUT = 120


def updates_enabled(data_dir=None):
    return shop_deploy.updates_allowed(data_dir)


def install_root():
    override = os.environ.get('EZ_NEST_INSTALL_ROOT', '').strip()
    if override:
        return Path(override).resolve()
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return None


def find_exe(root):
    for name in EXE_NAMES:
        candidate = Path(root) / name
        if candidate.is_file():
            return candidate
    return None


def apply_supported(root):
    # macOS bundles need a platform-specific, publisher-verified updater.
    if sys.platform == 'darwin':
        return False
    if root is None or find_exe(root) is None:
        return False
    if os.name == 'nt':
        # The limited boot account must never try to replace Program Files,
        # exit the working server, or gain elevated permissions silently.
        for variable in ('ProgramFiles', 'ProgramFiles(x86)'):
            protected = os.environ.get(variable)
            if protected and Path(root).resolve().is_relative_to(Path(protected).resolve()):
                return False
    return True


def updates_dir(data_dir):
    path = Path(data_dir) / 'updates'
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path):
    file = Path(path)
    if not file.is_file():
        return None
    try:
        return json.loads(file.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_matches(actual, expected):
    return shop_deploy.checksum_matches(actual, expected)


def pending_state(data_dir):
    pending = read_json(updates_dir(data_dir) / 'pending.json')
    if not pending or not pending.get('verified'):
        return None
    file = Path(pending.get('file', ''))
    if file.is_symlink() or not file.resolve().is_relative_to((Path(data_dir) / 'updates' / 'incoming').resolve()):
        return None
    if not file.is_file() or not checksum_matches(sha256_file(file), pending.get('sha256', '')):
        return None
    return pending


def snapshot_settings(data_dir):
    saved = {}
    root = Path(data_dir)
    for name in KEEP_FILES:
        file = root / name
        saved[name] = file.read_bytes() if file.is_file() else None
    return saved


def restore_settings(data_dir, saved):
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    for name, payload in saved.items():
        file = root / name
        if payload is None:
            if file.is_file() and not file.is_symlink():
                file.unlink()
            continue
        temporary = file.with_suffix(file.suffix + '.tmp')
        temporary.write_bytes(payload)
        temporary.replace(file)


def _is_symlink(info):
    return ((info.external_attr >> 16) & 0xF000) == 0xA000


def safe_extract(zip_path, dest):
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    root = dest.resolve()
    with ZipFile(zip_path) as archive:
        infos = archive.infolist()
        for info in infos:
            name = info.filename.replace('\\', '/')
            if not name:
                continue
            raw_parts = Path(name).parts
            if not raw_parts or raw_parts[0] in ('/', '\\') or any(part in ('..', '') or ':' in part for part in raw_parts) or raw_parts[0].endswith(':'):
                raise ValueError('Update archive contains an unsafe path.')
            parts = [part for part in raw_parts if part not in ('/', '\\')]
            target = dest.joinpath(*parts).resolve()
            if root != target and root not in target.parents:
                raise ValueError('Update archive contains an unsafe path.')
            if _is_symlink(info):
                raise ValueError('Update archive contains a link.')
        archive.extractall(dest)
    for directory, dirnames, filenames in os.walk(dest):
        for name in dirnames + filenames:
            if (Path(directory) / name).is_symlink():
                raise ValueError('Update archive contains a link.')
    return locate_payload(dest)


def locate_payload(extracted):
    extracted = Path(extracted)
    if find_exe(extracted) or (extracted / 'version.json').is_file():
        return extracted
    children = [entry for entry in extracted.iterdir() if entry.name != '__MACOSX']
    if len(children) == 1 and children[0].is_dir() and (find_exe(children[0]) or (children[0] / 'version.json').is_file()):
        return children[0]
    raise ValueError('Update archive does not contain the app.')


def app_entries(root):
    for entry in Path(root).iterdir():
        if entry.name in ('data', 'updates'):
            continue
        if entry.is_symlink() or entry.is_junction():
            raise ValueError(f'Refusing to replace a linked file: {entry.name}')
        yield entry


def _copy_entry(source, dest):
    if source.is_dir():
        shutil.copytree(source, dest, symlinks=False)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    if not source.is_dir() and dest.name in EXE_NAMES and os.name != 'nt':
        dest.chmod(0o755)


def _clear_app(root):
    for entry in list(app_entries(root)):
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def snapshot_app(install_root, backup):
    """Finish the backup before any installation mutation can begin."""
    backup = Path(backup)
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir(parents=True)
    for entry in app_entries(install_root):
        _copy_entry(entry, backup / entry.name)


def replace_app_files(install_root, payload):
    _clear_app(install_root)
    for entry in Path(payload).iterdir():
        if entry.name not in ('data', 'updates', '__MACOSX'):
            _copy_entry(entry, Path(install_root) / entry.name)


def apply_files(install_root, payload, backup):
    snapshot_app(install_root, backup)
    try:
        replace_app_files(install_root, payload)
    except Exception:
        rollback_files(install_root, backup)
        raise


def rollback_files(install_root, backup):
    install_root, backup = Path(install_root), Path(backup)
    if not backup.is_dir() or not any(backup.iterdir()):
        raise ValueError('No backup is available to restore.')
    _clear_app(install_root)
    for entry in backup.iterdir():
        _copy_entry(entry, install_root / entry.name)


def read_version(root):
    return json.loads((Path(root) / 'version.json').read_text(encoding='utf-8'))['version']


def installer_command(setup, install_root):
    return [str(setup), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/DIR=' + str(install_root)]


def run_setup(setup, install_root, data_dir):
    """Replace the app. A zip is unpacked here. setup.exe is the Inno installer."""
    setup = Path(setup)
    if setup.suffix.lower() == '.zip':
        payload = safe_extract(setup, updates_dir(data_dir) / 'extracted')
        archive_version = read_version(payload)
        replace_app_files(install_root, payload)
        return archive_version
    if os.name != 'nt':
        raise ValueError('The installer runs on the shop PC.')
    completed = subprocess.run(installer_command(setup, install_root), timeout=600)
    if completed.returncode != 0:
        raise ValueError('The installer did not finish. Settings and the hot folder were kept.')
    return read_version(install_root)


def _log(data_dir, message):
    path = updates_dir(data_dir) / 'helper.log'
    with path.open('a', encoding='utf-8') as handle:
        handle.write(f'{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())} {message}\n')


def mark_healthy(data_dir):
    from app_info import VERSION
    directory = Path(data_dir) / 'updates'
    applying = directory / 'applying.json'
    if not applying.is_file():
        return
    payload = json.loads(applying.read_text(encoding='utf-8'))
    if payload.get('version') != VERSION:
        return
    write_json(directory / 'healthy.json', {'version': VERSION, 'pid': os.getpid(), 'time': time.time()})


def command_for(exe, data_dir, confirm):
    # Windows venv executables redirect to a child interpreter. Launch that
    # interpreter directly so the health marker belongs to the process we track.
    python = (getattr(sys, '_base_executable', None) or sys.executable) if os.name == 'nt' else sys.executable
    command = [python, str(exe)] if exe.suffix == '.py' else [str(exe)]
    command += ['--web', '--no-browser', '--data-dir', str(data_dir)]
    if confirm:
        command.append('--update-confirm')
    return command


def launch(exe, data_dir, confirm):
    env = os.environ.copy()
    env['EZ_NEST_DATA'] = str(data_dir)
    if os.name == 'nt' and Path(exe).suffix == '.py' and sys.prefix != sys.base_prefix:
        # Preserve the venv's dependency search path while bypassing its redirector.
        env['__PYVENV_LAUNCHER__'] = sys.executable
    return subprocess.Popen(command_for(exe, data_dir, confirm), cwd=str(Path(exe).parent), env=env)


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def wait_until_exit(pid, timeout=180):
    if not pid:
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(0.2)
    raise TimeoutError('eznest did not close before the update could be installed.')


def _wait_healthy(path, process, version, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        # An early/stale marker is not proof that the expected child survived.
        if process.poll() is not None:
            return False
        payload = read_json(path)
        if (payload and payload.get('version') == version
                and payload.get('pid') == process.pid):
            return process.poll() is None
        time.sleep(0.2)
    return False


_left_running = []


def _leave_running(process):
    """The shop app outlives this helper. Don't warn that its handle is still open."""
    if process.poll() is None:
        _left_running.append(process.pid)
        process.returncode = 0


def _end_pid(pid):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(pid), '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        return


def _reap_unix(pid, timeout):
    deadline = time.time() + timeout
    while True:
        try:
            found, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return
        if found == pid:
            return
        if time.time() >= deadline:
            _end_pid(pid)
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                return
            return
        time.sleep(0.05)


def reap_left_running(timeout=8):
    """Wait out a stub the tests relaunched, so Windows can delete its folder."""
    pids = list(_left_running)
    _left_running.clear()
    for pid in pids:
        if os.name == 'nt':
            try:
                wait_until_exit(pid, timeout=timeout)
            except TimeoutError:
                _end_pid(pid)
                try:
                    wait_until_exit(pid, timeout=3)
                except TimeoutError:
                    pass
        else:
            _reap_unix(pid, timeout)
    if pids and os.name == 'nt':
        time.sleep(0.3)


def _stop(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def apply_and_confirm(install_root, data_dir, wait_pid=None, timeout=CONFIRM_TIMEOUT, runner=None):
    install_root, data_dir = Path(install_root), Path(data_dir)
    if not apply_supported(install_root):
        raise ValueError('Automatic updates to Program Files are not supported yet. The current server is kept running.')
    directory = updates_dir(data_dir)
    if wait_pid:
        wait_until_exit(int(wait_pid))
    pending = pending_state(data_dir)
    if not pending:
        raise ValueError('No checked update is waiting to be installed.')
    version = pending['version']
    # Only an explicit retry may attempt this payload again after a failure.
    pending['applyOnRestart'] = False
    write_json(directory / 'pending.json', pending)
    settings = snapshot_settings(data_dir)
    previous = read_version(install_root)
    backup = directory / 'backup'
    _log(data_dir, f'Installing {version} over {previous}.')
    # A failed/partial copy must never be used to restore over the intact app.
    backed_up = False
    try:
        snapshot_app(install_root, backup)
        backed_up = True
        if runner is not None:
            runner(Path(pending['file']), install_root, data_dir)
        else:
            run_setup(pending['file'], install_root, data_dir)
        restore_settings(data_dir, settings)
        installed = read_version(install_root)
        if installed != version:
            raise ValueError(f'The installed build is {installed}, not {version}.')
        exe = find_exe(install_root)
        if exe is None:
            raise ValueError('The new build does not contain eznest.exe.')
    except Exception:
        _log(data_dir, f'Install failed. Restoring {previous}.')
        if backed_up:
            rollback_files(install_root, backup)
            restore_settings(data_dir, settings)
        (directory / 'applying.json').unlink(missing_ok=True)
        restored = find_exe(install_root)
        if restored is not None:
            try:
                _leave_running(launch(restored, data_dir, False))
            except OSError as error:
                _log(data_dir, f'{previous} could not restart: {error}')
        raise
    write_json(directory / 'applying.json', {'version': version, 'previous': previous, 'startedAt': time.time()})
    (directory / 'pending.json').unlink(missing_ok=True)
    (directory / 'healthy.json').unlink(missing_ok=True)
    started = False
    for attempt in range(1, CONFIRM_ATTEMPTS + 1):
        (directory / 'healthy.json').unlink(missing_ok=True)
        process = None
        try:
            process = launch(exe, data_dir, True)
            if _wait_healthy(directory / 'healthy.json', process, version, timeout):
                started = True
                _leave_running(process)
                break
        except (OSError, ValueError) as error:
            _log(data_dir, f'{version} could not start: {error}')
            if process is not None:
                _stop(process)
            break
        _stop(process)
        _log(data_dir, f'{version} did not start (attempt {attempt}).')
    if not started:
        _log(data_dir, f'Rolling back to {previous}.')
        rollback_files(install_root, backup)
        restore_settings(data_dir, settings)
        (directory / 'applying.json').unlink(missing_ok=True)
        write_json(directory / 'rollback.json', {
            'failed': version,
            'restored': previous,
            'reason': f'eznest restored {previous} because {version} did not start. Settings and the hot folder were kept.',
        })
        restored = find_exe(install_root)
        if restored is not None:
            _leave_running(launch(restored, data_dir, False))
        return {'ok': False, 'restored': previous, 'failed': version}
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    extracted = directory / 'extracted'
    if extracted.exists():
        shutil.rmtree(extracted, ignore_errors=True)
    (directory / 'rollback.json').unlink(missing_ok=True)
    _log(data_dir, f'{version} started.')
    return {'ok': True, 'version': version}


def spawn_helper(install_root, data_dir, wait_pid):
    install_root, data_dir = Path(install_root), Path(data_dir)
    args = ['--apply-update', '--wait-pid', str(wait_pid), '--install-root', str(install_root), '--data-dir', str(data_dir)]
    if getattr(sys, 'frozen', False):
        runner = updates_dir(data_dir) / 'runner'
        if runner.exists():
            shutil.rmtree(runner)
        runner.mkdir(parents=True)
        exe = Path(sys.executable)
        shutil.copy2(exe, runner / 'eznest-update.exe')
        internal = exe.parent / '_internal'
        if internal.is_dir():
            shutil.copytree(internal, runner / '_internal', symlinks=False)
        command = [str(runner / 'eznest-update.exe'), *args]
    else:
        command = [sys.executable, str(Path(__file__).resolve()), *args]
    kwargs = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL, 'stdin': subprocess.DEVNULL}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs['start_new_session'] = True
    subprocess.Popen(command, **kwargs)


def begin_apply(data_dir, install_root):
    if not apply_supported(install_root):
        raise ValueError('Run eznest-setup.exe on the shop PC to install this update.')
    pending = pending_state(data_dir)
    if not pending:
        raise ValueError('Download the update before installing it.')
    pending['applyOnRestart'] = True
    write_json(updates_dir(data_dir) / 'pending.json', pending)
    spawn_helper(install_root, data_dir, os.getpid())
    return {'ok': True, 'restarting': True, 'version': pending['version'], 'latest': pending['version'], 'message': f'Ez Nest is restarting to install {pending["version"]}. Settings and the hot folder stay.'}


def handoff_if_pending(install_root, data_dir):
    if not updates_enabled(data_dir) or not apply_supported(install_root):
        return False
    pending = pending_state(data_dir)
    if not pending or not pending.get('applyOnRestart'):
        return False
    spawn_helper(install_root, data_dir, os.getpid())
    return True


def stage_file(data_dir, version, digest, payload, filename):
    if filename != Path(filename).name or '/' in filename or '\\' in filename or ':' in filename or Path(filename).suffix.lower() not in ('.exe', '.zip'):
        raise ValueError('Invalid update filename.')
    directory = updates_dir(data_dir)
    incoming = directory / 'incoming'
    incoming.mkdir(parents=True, exist_ok=True)
    target = incoming / filename
    partial = target.with_suffix(target.suffix + '.partial')
    if not checksum_matches(hashlib.sha256(payload).hexdigest(), digest):
        partial.unlink(missing_ok=True)
        raise ValueError('The downloaded update does not match its checksum. It was not installed.')
    partial.write_bytes(payload)
    partial.replace(target)
    kind = 'installer' if target.suffix.lower() == '.exe' else 'files'
    pending = {
        'version': version,
        'sha256': digest,
        'file': str(target),
        'filename': filename,
        'kind': kind,
        'channel': shop_deploy.load_shop(data_dir)['channel'],
        'verified': True,
        'applyOnRestart': True,
    }
    write_json(directory / 'pending.json', pending)
    return pending


def local_state(data_dir, install_root):
    pending = pending_state(data_dir)
    rollback = read_json(updates_dir(data_dir) / 'rollback.json')
    return {
        'applySupported': apply_supported(install_root),
        'staged': pending is not None,
        'stagedVersion': pending.get('version') if pending else None,
        'applyOnRestart': bool(apply_supported(install_root) and pending and pending.get('applyOnRestart')),
        'rollback': rollback if isinstance(rollback, dict) else None,
    }


def parse_changelog(text):
    entries = []
    current = None
    for line in text.splitlines():
        if line.startswith('## '):
            if current:
                entries.append(current)
            title = line[3:].strip()
            current = {'title': title, 'version': title.split()[0], 'lines': []}
        elif current is not None and not line.startswith('# '):
            current['lines'].append(line)
    if current:
        entries.append(current)
    for entry in entries:
        while entry['lines'] and not entry['lines'][0].strip():
            entry['lines'].pop(0)
        while entry['lines'] and not entry['lines'][-1].strip():
            entry['lines'].pop()
        entry['body'] = '\n'.join(entry['lines'])
        del entry['lines']
    return entries


def changelog_entries(root):
    path = Path(root) / 'CHANGELOG.md'
    if not path.is_file():
        return []
    return parse_changelog(path.read_text(encoding='utf-8'))


def current_notes(root, version):
    for entry in changelog_entries(root):
        if entry['version'] == version or entry['title'].startswith(version):
            return entry['body']
    entries = changelog_entries(root)
    return entries[0]['body'] if entries else ''


def write_sidecars(setup, out_dir, version):
    setup, out_dir = Path(setup), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = sha256_file(setup)
    sha_path = out_dir / f'{setup.name}.sha256'
    sha_path.write_text(f'{digest}  {setup.name}\n', encoding='utf-8')
    manifest = {
        'channel': 'rc',
        'version': version,
        'published': False,
        'filename': setup.name,
        'sha256': digest,
        'approval': 'Workflow artifact. eznest installs this only after an approved GitHub release includes this checksum.',
    }
    manifest_path = out_dir / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return {'sha256': digest, 'sha': str(sha_path), 'manifest': str(manifest_path)}


def apply_cli(argv):
    import argparse
    parser = argparse.ArgumentParser(description='Install a downloaded eznest update')
    parser.add_argument('--wait-pid', type=int, default=0)
    parser.add_argument('--install-root', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = apply_and_confirm(args.install_root, args.data_dir, wait_pid=args.wait_pid or None)
    except Exception as error:
        _log(args.data_dir, f'Update failed: {error}')
        print(str(error), file=sys.stderr)
        return 1
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--apply-update':
        raise SystemExit(apply_cli(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == '--write-sidecars':
        if len(sys.argv) != 5:
            raise SystemExit('Usage: installer_update.py --write-sidecars <setup.exe> <out-dir> <version>')
        written = write_sidecars(sys.argv[2], sys.argv[3], sys.argv[4])
        print(written['sha256'])
        raise SystemExit(0)
    raise SystemExit('Run eznest.exe --apply-update to install a downloaded update.')

