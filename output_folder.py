"""Save frozen print packs to an explicit operator-selected local directory."""
import io
import json
import shutil
import tempfile
import re
from pathlib import Path
from zipfile import ZipFile

FILES = {'artwork.svg','sheet-map.svg','sorting-guide.html','piece-checklist.csv','batch.json','READ ME.txt'}


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

    def connect(self, value, source=None):
        if not value:
            self.root = None
        else:
            root = Path(value).expanduser().resolve(strict=True)
            if not root.is_dir() or root == Path(root.anchor):
                raise ValueError('Choose an output folder, not an entire drive.')
            if source and root.is_relative_to(source.resolve()):
                raise ValueError('Choose an output folder outside the watched source folder to avoid importing exports.')
            self.root = root
        self.storage.write_text(json.dumps(self.status()), encoding='utf-8')
        return self.status()

    def save(self, run_id, content, source=None):
        if not self.root:
            return None
        root = self.root.resolve(strict=True)
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
        temporary = Path(tempfile.mkdtemp(prefix='.eznest-', dir=root))
        try:
            for name, data in files.items():
                (temporary/name).write_bytes(data)
            temporary.rename(destination)
        finally:
            if temporary.exists() and not temporary.is_symlink() and not temporary.is_junction() and temporary.resolve().is_relative_to(root):
                shutil.rmtree(temporary)
        return str(destination)
