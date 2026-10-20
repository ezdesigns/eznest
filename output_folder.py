"""Save frozen print packs to an explicit operator-selected local directory."""
import io
import json
import shutil
import tempfile
import re
from pathlib import Path
from zipfile import ZipFile

FILES = {'artwork.svg','sheet-map.svg','sorting-guide.html','piece-checklist.csv','batch.json','READ ME.txt'}


def unreachable_message(path):
    return f"The hot folder can't be reached: {path}. Check that the folder or share is there, and that this PC can write to it."


class OutputFolder:
    def __init__(self, storage):
        self.storage = Path(storage)
        self.root = None
        try:
            value = json.loads(self.storage.read_text(encoding='utf-8'))['path']
            self.root = Path(value) if value else None
        except (OSError, ValueError, KeyError):
            pass

    def status(self):
        return {'path':str(self.root) if self.root else '', 'configured':self.root is not None}

    def _store(self, path):
        self.storage.parent.mkdir(parents=True, exist_ok=True)
        self.storage.write_text(json.dumps({'path': path, 'configured': bool(path)}), encoding='utf-8')

    def connect(self, value, source=None):
        if not value:
            self.root = None
            self._store('')
            return self.status()
        if not isinstance(value, str) or len(value) > 400:
            raise ValueError('Hot folder path is invalid.')
        try:
            root = Path(value).expanduser().resolve(strict=True)
        except OSError:
            self.root = Path(value).expanduser()
            self._store(value)
            raise ValueError(unreachable_message(value)) from None
        if not root.is_dir() or root == Path(root.anchor):
            raise ValueError('Choose an output folder, not an entire drive.')
        if source and root.is_relative_to(source.resolve()):
            raise ValueError('Choose an output folder outside the watched source folder to avoid importing exports.')
        try:
            # Empty, non-printable probe; exercise this server account's access.
            with tempfile.TemporaryFile(prefix='.eznest-check-', suffix='.tmp', dir=root):
                pass
        except OSError:
            # Retain the requested destination, never silently send to an older
            # working folder after the operator tried to change it.
            self.root = root
            self._store(str(root))
            raise ValueError('The hot folder exists, but eznest cannot write to it. Ask your shop administrator to give the eznest-svc account access, then save again.') from None
        self.root = root
        self._store(str(root))
        return self.status()

    def save(self, run_id, content, source=None):
        if not self.root:
            return None
        try:
            root = self.root.expanduser().resolve(strict=True)
        except OSError:
            raise ValueError(unreachable_message(self.root)) from None
        if not root.is_dir() or (source and root.is_relative_to(source.resolve())):
            raise ValueError('Output folder is unavailable or inside the watched source folder.')
        if len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id):
            raise ValueError('Invalid batch identity.')
        destination = root / ('eznest-'+run_id)
        with ZipFile(io.BytesIO(content)) as archive:
            names=archive.namelist(); base=FILES-{'artwork.svg'}
            artwork=set(names)-base
            if len(names)!=len(set(names)) or not base.issubset(names) or not artwork or len(artwork)>100 or any(not re.fullmatch(r'(?:artwork\.(?:svg|pdf)|sheet-\d{3}\.(?:svg|pdf))',name) for name in artwork):
                raise ValueError('Unexpected batch files.')
            files = {name:archive.read(name) for name in names}
        if destination.exists():
            if destination.is_symlink() or destination.is_junction() or not destination.is_dir():
                raise ValueError('The output name is already in use.')
            if any(not (destination/name).is_file() or (destination/name).is_symlink() or (destination/name).read_bytes()!=data for name,data in files.items()):
                raise ValueError('Existing batch files differ. Choose another output folder; no files were overwritten.')
            return str(destination)
        try:
            temporary = Path(tempfile.mkdtemp(prefix='.eznest-', dir=root))
        except OSError:
            raise ValueError(unreachable_message(root)) from None
        try:
            for name, data in files.items():
                (temporary/name).write_bytes(data)
            temporary.rename(destination)
        except OSError:
            raise ValueError(unreachable_message(root)) from None
        finally:
            if temporary.exists() and not temporary.is_symlink() and not temporary.is_junction() and temporary.resolve().is_relative_to(root):
                shutil.rmtree(temporary)
        return str(destination)


def stage_pack(folder, run_id, content, source=None):
    """Copy one frozen pack into an optional staging folder. An empty path stays off."""
    if not folder:
        return None
    if not isinstance(folder, str) or len(folder) > 400:
        raise ValueError('Staging folder path is invalid.')
    try:
        root = Path(folder).expanduser().resolve(strict=True)
    except OSError:
        raise ValueError('Staging folder is not a folder on this computer.') from None
    holder = OutputFolder.__new__(OutputFolder)
    holder.root = root
    holder.storage = None
    return holder.save(run_id, content, source)


