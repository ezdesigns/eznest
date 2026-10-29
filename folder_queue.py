"""Read-only polling of one operator-selected SVG production folder."""
import hashlib
import json
import os
import time
from pathlib import Path


def real_directory(value):
    """Absolute directory with no upward segments and no link components."""
    if not isinstance(value, str) or not value or len(value) > 400 or any(ord(char) < 32 for char in value):
        raise ValueError('Choose a production folder, not an entire drive.')
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise ValueError('Choose a production folder, not an entire drive.')
    if any(part in ('.', '..') for part in raw.parts):
        raise ValueError('The folder path cannot move upward.')
    cursor = Path(raw.anchor)
    for part in raw.parts[1:]:
        cursor = cursor / part
        if _linked(cursor):
            raise ValueError('The folder cannot be a link.')
    if not cursor.is_dir() or cursor == Path(cursor.anchor):
        raise ValueError('Choose a production folder, not an entire drive.')
    return cursor


def _linked(path):
    if path.is_symlink():
        return True
    checker = getattr(path, 'is_junction', None)
    return bool(checker and checker())


class FolderQueue:
    def __init__(self, storage, clock=time.monotonic, approved=None):
        self.storage = Path(storage)
        self.clock = clock
        self.approved = approved
        self.root = None
        self.seen = {}
        self.entries = {}
        self._load()

    def _approved(self, root):
        if self.approved is None:
            return True
        try:
            allowed = self.approved()
        except (OSError, ValueError):
            return False
        if not isinstance(allowed, (list, tuple)):
            return False
        target = str(root)
        for item in allowed:
            try:
                if str(real_directory(item)) == target:
                    return True
            except ValueError:
                continue
        return False

    def _load(self):
        try:
            raw = json.loads(self.storage.read_text(encoding='utf-8'))['path']
            root = real_directory(raw)
        except (OSError, KeyError, ValueError, TypeError):
            return
        if self._approved(root):
            self.root = root

    def _contained(self, path):
        if not self.root or not isinstance(path, Path) or _linked(path):
            return False
        try:
            resolved = path.resolve(strict=True)
            root = self.root.resolve()
        except OSError:
            return False
        return resolved.is_relative_to(root)

    def connect(self, value):
        root = real_directory(value)
        if not self._approved(root):
            raise ValueError('That folder is not an approved source folder. Choose it on the shop computer.')
        self.root = root
        self.seen.clear()
        self.entries.clear()
        self.storage.write_text(json.dumps({'path': str(root)}), encoding='utf-8')
        return self.scan()

    def disconnect(self):
        self.root = None
        self.seen.clear()
        self.entries.clear()
        self.storage.write_text('{}', encoding='utf-8')

    def scan(self):
        if not self.root or not self._approved(self.root):
            if self.root:
                return {'connected': False, 'files': [], 'error': 'The source folder is not approved. Choose it on the shop computer.'}
            return {'connected': False, 'files': []}
        if not self.root.is_dir():
            return {'connected': True, 'path': str(self.root), 'files': [], 'error': 'The connected folder is unavailable. Previously loaded jobs remain snapshots.'}
        files, current, unsupported = [], {}, 0
        for directory, directories, names in os.walk(self.root, followlinks=False):
            directories[:] = sorted(d for d in directories if not d.startswith('.') and not _linked(Path(directory)/d))
            for name in sorted(names):
                path = Path(directory)/name
                if _linked(path) or name.startswith('.') or not self._contained(path):
                    continue
                if path.suffix.lower() != '.svg':
                    if path.suffix.lower() in ('.ai','.pdf','.eps','.dxf'):
                        unsupported += 1
                    continue
                if len(files) >= 250:
                    self.entries = current
                    return {'connected': True, 'path': str(self.root), 'files': files, 'error': 'Folder is limited to 250 SVG files. Use a smaller ready-to-print folder.', 'unsupported': unsupported}
                relative = str(path.relative_to(self.root))
                ident = hashlib.sha256(relative.casefold().encode()).hexdigest()[:20]
                entry = {'id': ident, 'name': name, 'relativePath': relative, 'status': 'settling'}
                try:
                    info = path.stat()
                    signature = (info.st_size, info.st_mtime_ns)
                    previous = self.seen.get(ident)
                    if not previous or previous['signature'] != signature:
                        previous = {'signature': signature, 'since': self.clock()}
                    self.seen[ident] = previous
                    if info.st_size > 8_000_000:
                        entry.update(status='error', error='File exceeds 8 MB.')
                    elif self.clock()-previous['since'] >= 2:
                        if 'revision' not in previous:
                            raw = path.read_bytes()
                            after = path.stat()
                            if (after.st_size, after.st_mtime_ns) != signature:
                                previous['since'] = self.clock()
                            else:
                                previous['revision'] = hashlib.sha256(raw).hexdigest()
                        if 'revision' in previous:
                            entry.update(status='ready', revision=previous['revision'])
                    current[ident] = path
                except OSError:
                    entry.update(status='error', error='File cannot be read right now.')
                files.append(entry)
        self.entries = current
        self.seen = {key: value for key, value in self.seen.items() if key in current}
        return {'connected': True, 'path': str(self.root), 'files': files, 'unsupported': unsupported}

    def read(self, ident, revision):
        path = self.entries.get(ident)
        if not self._contained(path):
            raise ValueError('File is no longer in the connected folder. Refresh the queue.')
        with path.open('rb') as stream:
            raw = stream.read(8_000_001)
        if len(raw) > 8_000_000 or hashlib.sha256(raw).hexdigest() != revision:
            raise ValueError('File changed while loading. Wait for the folder to refresh.')
        return raw.decode('utf-8-sig')
