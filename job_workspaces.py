"""Private working jobs; inventory and shop membership stay at the shop root."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
import re
import threading


@dataclass
class Workspace:
    directory: Path
    state: dict = field(default_factory=lambda: {'status': 'idle'})
    process: object = None
    lock: object = field(default_factory=threading.RLock)


CURRENT = ContextVar('eznest_job_workspace', default=None)
_workspaces = {}
_guard = threading.RLock()


@contextmanager
def select(root, owner, restore):
    """Owner is derived by the server from authenticated membership, never JSON."""
    if owner is None:
        token = CURRENT.set(None)
        try:
            yield
        finally:
            CURRENT.reset(token)
        return
    if not re.fullmatch(r'(member-[a-f0-9]{32}|browser-[a-f0-9]{64})', owner):
        raise ValueError('Invalid job workspace')
    root = Path(root).resolve()
    with _guard:
        key = (root, owner)
        workspace = _workspaces.get(key)
        fresh = workspace is None
        if fresh:
            directory = root / 'designers' / owner
            if not directory.resolve().is_relative_to(root) or directory.is_symlink():
                raise ValueError('Invalid job workspace folder')
            directory.mkdir(parents=True, exist_ok=True)
            workspace = _workspaces[key] = Workspace(directory)
        token = CURRENT.set(workspace)
        if fresh:
            try:
                restore()
            except BaseException:
                CURRENT.reset(token)
                _workspaces.pop(key, None)
                raise
    try:
        yield
    finally:
        CURRENT.reset(token)


def all_for(root):
    with _guard:
        return [item for (directory, _), item in _workspaces.items() if directory == Path(root).resolve()]
