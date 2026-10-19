"""Swap a verified portable build into place and restore the previous one.

User files under data/ are not replaced. The running executable cannot replace
itself, so a helper starts after this process exits, installs the new files,
and rolls them back if the new build does not signal that it started.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from zipfile import ZipFile

import updates

EXE_NAMES = ('eznest.exe', 'eznest', 'eznest.py')
CONFIRM_ATTEMPTS = 3
CONFIRM_TIMEOUT = 120


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
    return root is not None and find_exe(root) is not None


def _is_symlink(info):
    return ((info.external_attr >> 16) & 0xF000) == 0xA000


def safe_extract(zip_path, dest):
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    root = dest.resolve()
    with ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename.replace('\\', '/')
            if not name:
                continue
            raw_parts = Path(name).parts
            if not raw_parts or raw_parts[0] in ('/', '\\') or any(part in ('..', '') for part in raw_parts) or raw_parts[0].endswith(':'):
                raise ValueError('Update archive contains an unsafe path.')
            parts = [part for part in raw_parts if part not in ('/', '\\')]
            target = (dest.joinpath(*parts)).resolve()
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
    raise ValueError('Update archive does not contain the portable app.')


def app_entries(root):
    for entry in Path(root).iterdir():
        if entry.name == 'data':
            continue
        if entry.is_symlink():
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


def apply_files(install_root, payload, backup):
    install_root, payload, backup = Path(install_root), Path(payload), Path(backup)
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir(parents=True)
    for entry in app_entries(install_root):
        _copy_entry(entry, backup / entry.name)
    try:
        _clear_app(install_root)
        for entry in payload.iterdir():
            if entry.name in ('data', '__MACOSX'):
                continue
            _copy_entry(entry, install_root / entry.name)
    except Exception:
        _clear_app(install_root)
        for entry in backup.iterdir():
            _copy_entry(entry, install_root / entry.name)
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
    raise TimeoutError('Ez Nest did not close before the update could be installed.')


def command_for(exe, open_browser, confirm):
    command = [sys.executable, str(exe)] if exe.suffix == '.py' else [str(exe)]
    if not open_browser:
        command.append('--no-browser')
    if confirm:
        command.append('--update-confirm')
    return command


def _log(data_dir, message):
    path = updates.updates_dir(data_dir) / 'helper.log'
    with path.open('a', encoding='utf-8') as handle:
        handle.write(f'{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())} {message}\n')


def mark_healthy(data_dir):
    from app_info import VERSION
    directory = Path(data_dir) / 'updates'
    applying_path = directory / 'applying.json'
    if not applying_path.is_file():
        return
    applying = json.loads(applying_path.read_text(encoding='utf-8'))
    if applying.get('version') != VERSION:
        return
    updates.write_json(directory / 'healthy.json', {'version': VERSION, 'pid': os.getpid(), 'time': time.time()})


def _wait_healthy(path, process, version, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = updates.read_json(path)
        if payload and payload.get('version') == version:
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.2)
    return False


def _stop(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def apply_and_confirm(install_root, data_dir, wait_pid=None, timeout=CONFIRM_TIMEOUT):
    install_root, data_dir = Path(install_root), Path(data_dir)
    directory = updates.updates_dir(data_dir)
    if wait_pid:
        wait_until_exit(int(wait_pid))
    pending = updates.pending_state(data_dir)
    if not pending:
        raise ValueError('No verified update is waiting to be installed.')
    version = pending['version']
    payload = safe_extract(pending['zip'], directory / 'extracted')
    archive_version = read_version(payload)
    if archive_version != version:
        raise ValueError(f'The archive is {archive_version}, not {version}.')
    previous = read_version(install_root)
    backup = directory / 'backup'
    _log(data_dir, f'Installing {version} over {previous}.')
    apply_files(install_root, payload, backup)
    updates.write_json(directory / 'applying.json', {
        'version': version,
        'previous': previous,
        'backup': str(backup),
        'startedAt': time.time(),
    })
    (directory / 'pending.json').unlink(missing_ok=True)
    (directory / 'healthy.json').unlink(missing_ok=True)
    exe = find_exe(install_root)
    if exe is None:
        rollback_files(install_root, backup)
        raise ValueError('The new build does not contain eznest.exe.')
    open_browser = pending.get('openBrowser', True) is not False
    started = False
    for attempt in range(1, CONFIRM_ATTEMPTS + 1):
        (directory / 'healthy.json').unlink(missing_ok=True)
        process = subprocess.Popen(command_for(exe, open_browser, True), cwd=str(install_root))
        if _wait_healthy(directory / 'healthy.json', process, version, timeout):
            started = True
            break
        _stop(process)
        _log(data_dir, f'{version} did not start (attempt {attempt}).')
    if not started:
        _log(data_dir, f'Rolling back to {previous}.')
        rollback_files(install_root, backup)
        (directory / 'applying.json').unlink(missing_ok=True)
        updates.write_json(directory / 'rollback.json', {
            'failed': version,
            'restored': previous,
            'reason': 'The new version did not start. Ez Nest restored the previous build. Jobs and settings were kept.',
        })
        restored = find_exe(install_root)
        if restored is not None:
            subprocess.Popen(command_for(restored, open_browser, False), cwd=str(install_root))
        return {'ok': False, 'restored': previous, 'failed': version}
    for folder in (directory / 'extracted', backup):
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
    incoming = Path(pending['zip'])
    incoming.unlink(missing_ok=True)
    (directory / 'rollback.json').unlink(missing_ok=True)
    _log(data_dir, f'{version} started.')
    return {'ok': True, 'version': version}


def spawn_helper(install_root, data_dir, wait_pid):
    install_root, data_dir = Path(install_root), Path(data_dir)
    args = ['--apply-update', '--wait-pid', str(wait_pid), '--install-root', str(install_root), '--data-dir', str(data_dir)]
    if getattr(sys, 'frozen', False):
        runner = updates.updates_dir(data_dir) / 'runner'
        if runner.exists():
            shutil.rmtree(runner)
        runner.mkdir(parents=True)
        exe = Path(sys.executable)
        shutil.copy2(exe, runner / exe.name)
        internal = exe.parent / '_internal'
        if internal.is_dir():
            shutil.copytree(internal, runner / '_internal', symlinks=False)
        command = [str(runner / exe.name), *args]
    else:
        command = [sys.executable, str(Path(__file__).resolve()), *args]
    kwargs = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL, 'stdin': subprocess.DEVNULL}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs['start_new_session'] = True
    subprocess.Popen(command, **kwargs)


def handoff_if_pending(install_root, data_dir):
    if not apply_supported(install_root) or not updates.updates_enabled():
        return False
    pending = updates.pending_state(data_dir)
    if not pending or not (pending.get('applyOnRestart') or pending.get('applyNow')):
        return False
    spawn_helper(install_root, data_dir, os.getpid())
    return True


def apply_cli(argv):
    import argparse
    parser = argparse.ArgumentParser(description='Install a downloaded Ez Nest update')
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
    raise SystemExit('Run eznest.exe --apply-update to install a downloaded update.')
