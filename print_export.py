"""Named local exports from frozen packs, with a Windows Save As dialog."""
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from zipfile import ZipFile


def browse_folders(value, initial):
    """List folders for the authenticated chooser on this PC; never read file contents."""
    if value == '':
        roots = [Path(item) for item in os.listdrives()] if os.name == 'nt' else [Path('/')]
        return {'path': '', 'parent': None, 'folders': [{'name': str(root), 'path': str(root)} for root in roots]}
    if value is None:
        value = str(initial or Path.home()/'Documents')
    if not isinstance(value, str) or len(value) > 1000 or not Path(value).is_absolute():
        raise ValueError('Enter a full folder path.')
    root = Path(value).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Choose a folder, not a file.')
    folders = []
    with os.scandir(root) as entries:
        for entry in entries:
            try:
                if entry.is_dir() and not entry.name.startswith('.'):
                    folders.append({'name': entry.name, 'path': str(root/entry.name)})
            except OSError:
                continue
    folders.sort(key=lambda item: item['name'].casefold())
    return {'path': str(root), 'parent': str(root.parent) if root != root.parent else '', 'folders': folders}


def export_filename(name, kind):
    if kind not in ('pdf', 'pack'):
        raise ValueError('Choose PDF or a complete print pack.')
    extension = '.pdf' if kind == 'pdf' else '.zip'
    if not isinstance(name, str) or not name or len(name) > 100:
        raise ValueError('Enter a file name of up to 100 characters.')
    if name.lower().endswith(extension):
        name = name[:-len(extension)]
    if not name or name[-1] in '. ' or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', name, re.I):
        raise ValueError('Use a file name without folder paths or special characters.')
    return name + extension


def native_save_available():
    """Session-zero services cannot show a dialog on the employee's desktop."""
    if os.name != 'nt':
        return False
    import ctypes
    session = ctypes.c_ulong()
    try:
        return bool(ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)) and session.value != 0)
    except (AttributeError, OSError):
        return False


def pick_save_path(name, kind):
    """Ask Windows for a destination; cancellation never creates a file."""
    filename = export_filename(name, kind)
    if not native_save_available():
        raise ValueError('Windows Save As is unavailable in this session. Use browser download.')
    script = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.Opacity = 0
$picker = New-Object System.Windows.Forms.SaveFileDialog
$picker.Title = 'Save print file'
$picker.FileName = $request.name
$picker.Filter = $request.filter
$picker.DefaultExt = $request.extension
$picker.AddExtension = $true
$picker.CheckPathExists = $true
$picker.OverwritePrompt = $false
try {
    $owner.Show()
    if ($picker.ShowDialog($owner) -eq 'OK') { [Console]::Write($picker.FileName) }
} finally { $picker.Dispose(); $owner.Dispose() }
'''
    request = {'name': filename, 'extension': 'pdf' if kind == 'pdf' else 'zip',
               'filter': 'Print file (*.pdf)|*.pdf' if kind == 'pdf' else 'Complete print pack (*.zip)|*.zip'}
    try:
        selected = subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-EncodedCommand',
                                   base64.b64encode(script.encode('utf-16le')).decode('ascii')],
                                  input=json.dumps(request).encode('utf-8'), capture_output=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW, timeout=300, check=True)
    except (subprocess.SubprocessError, OSError) as error:
        raise ValueError('The Windows save window could not finish. Try Save to My Computer again.') from error
    return selected.stdout.decode('utf-8-sig').strip() or None


def export_content(package, name, kind):
    filename = export_filename(name, kind)
    content = package
    if kind == 'pdf':
        with ZipFile(io.BytesIO(package)) as archive:
            if 'artwork.pdf' not in archive.namelist():
                raise ValueError('This layout needs a complete print pack because it has multiple sheets or SVG artwork.')
            content = archive.read('artwork.pdf')
    return filename, content


def existing_digest(path):
    if path.is_symlink() or path.is_junction():
        raise ValueError('Choose a regular file, not a linked file.')
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError('That name belongs to a folder. Choose another file name.')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_file(path, content, work, expected=None, source=None):
    """Publish atomically; explicit replacements retain the previous bytes locally."""
    path = Path(path)
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir() or (source and parent.is_relative_to(source.resolve())):
        raise ValueError('Choose a folder outside the watched source folder.')
    path = parent / path.name
    before = existing_digest(path)
    digest = hashlib.sha256(content).hexdigest()
    if before == digest:
        return {'path': str(path), 'sha256': digest}
    if before is not None and before != expected:
        return {'exists': True, 'path': str(path), 'existingSha256': before}
    backup = None
    if before is not None:
        previous = path.read_bytes()
        if hashlib.sha256(previous).hexdigest() != before:
            raise ValueError('The existing file changed. Review and save again.')
        backups = Path(work) / 'export-backups'
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / (uuid.uuid4().hex + path.suffix)
        backup.write_bytes(previous)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.eznest-', suffix='.tmp', dir=parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if existing_digest(path) != before:
            raise ValueError('The destination changed while saving. Review and save again.')
        if before is None:
            # An exclusive create avoids replacing a file that appeared meanwhile.
            if os.name == 'nt':
                os.rename(temporary, path)
            else:
                os.link(temporary, path)
        else:
            os.replace(temporary, path)
        return {'path': str(path), 'sha256': digest, 'backup': str(backup) if backup else None}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
