"""Read-only polling of one operator-selected SVG production folder."""
import hashlib
import json
import os
import time
from pathlib import Path


class FolderQueue:
    def __init__(self, storage, clock=time.monotonic):
        self.storage = Path(storage)
        self.clock = clock
        self.root = None
        self.seen = {}
        self.entries = {}
        try:
            root = Path(json.loads(self.storage.read_text(encoding='utf-8'))['path'])
            if root.is_dir():
                self.root = root.resolve()
        except (OSError, KeyError, ValueError):
            pass

    def connect(self, value):
        root = Path(value).expanduser().resolve(strict=True)
        if not root.is_dir() or root == Path(root.anchor):
            raise ValueError('Choose a production folder, not an entire drive.')
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
        if not self.root:
            return {'connected': False, 'files': []}
        if not self.root.is_dir():
            return {'connected': True, 'path': str(self.root), 'files': [], 'error': 'The connected folder is unavailable. Previously loaded jobs remain snapshots.'}
        files, current, unsupported = [], {}, 0
        for directory, directories, names in os.walk(self.root, followlinks=False):
            directories[:] = sorted(d for d in directories if not d.startswith('.') and not (Path(directory)/d).is_symlink() and not (Path(directory)/d).is_junction())
            for name in sorted(names):
                path = Path(directory)/name
                if path.is_symlink() or name.startswith('.') or not path.resolve().is_relative_to(self.root):
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
                            if (after.st_size,after.st_mtime_ns) != signature:
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
        self.seen = {key:value for key,value in self.seen.items() if key in current}
        return {'connected': True, 'path': str(self.root), 'files': files, 'unsupported': unsupported}

    def read(self, ident, revision):
        path = self.entries.get(ident)
        if not path or not self.root or not path.resolve().is_relative_to(self.root) or path.is_symlink():
            raise ValueError('File is no longer in the connected folder. Refresh the queue.')
        with path.open('rb') as stream:
            raw = stream.read(8_000_001)
        if len(raw) > 8_000_000 or hashlib.sha256(raw).hexdigest() != revision:
            raise ValueError('File changed while loading. Wait for the folder to refresh.')
        return raw.decode('utf-8-sig')
