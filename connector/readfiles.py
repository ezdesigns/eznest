"""Read shop logs without taking them away from the program that writes them.

Opens are shared and read-only. This module never renames, moves, or truncates
the file it was given. A half-written last line stays unparsed until a later
read sees its newline. If the file is busy or changes mid-read, the bytes are
copied into the connector data folder and parsed from that copy.
"""
import errno
import os
import shutil
import tempfile
from pathlib import Path

OPENED = []

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
_INVALID_HANDLE = 0xFFFFFFFF


class FileContended(OSError):
    """The writer still has the log. Try a private copy, not an exclusive lock."""


def windows_open_arguments():
    """Read access, and share read, write, and delete so the RIP can keep logging."""
    access = GENERIC_READ
    share = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
    return access, share, OPEN_EXISTING


def open_shared_read(path):
    """Open path for reading while other processes may write it. Never writable."""
    target = Path(path)
    OPENED.append(str(target.resolve()) if target.exists() else str(target))
    if os.name == 'nt':
        return _open_windows(target)
    flags = os.O_RDONLY
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    if hasattr(os, 'O_BINARY'):
        flags |= os.O_BINARY
    fd = os.open(target, flags)
    return os.fdopen(fd, 'rb', closefd=True)


def _open_windows(path):
    import ctypes
    import msvcrt
    access, share, disposition = windows_open_arguments()
    if access & GENERIC_WRITE:
        raise OSError('refusing a write handle')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
    ]
    kernel.CreateFileW.restype = ctypes.c_void_p
    handle = kernel.CreateFileW(str(path), access, share, None, disposition, FILE_ATTRIBUTE_NORMAL, None)
    if handle in (None, _INVALID_HANDLE, ctypes.c_void_p(-1).value):
        err = ctypes.get_last_error()
        if err in (32, 33):
            raise FileContended('busy')
        raise OSError(err, 'Could not open the log for shared reading.')
    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
    return os.fdopen(fd, 'rb', closefd=True)


def _is_contention(error):
    if isinstance(error, FileContended):
        return True
    if isinstance(error, (BlockingIOError, TimeoutError)):
        return True
    number = getattr(error, 'errno', None)
    if number in (errno.EAGAIN, errno.EBUSY):
        return True
    if getattr(error, 'winerror', None) in (32, 33):
        return True
    return False


def _read_once(path, offset):
    with open_shared_read(path) as handle:
        before = os.fstat(handle.fileno())
        handle.seek(max(0, offset))
        data = handle.read()
        after = os.fstat(handle.fileno())
        if after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
            raise FileContended('changed')
        return data


def _copy_then_read(path, offset, directory):
    """Copy bytes into our own folder, close the log, then read the copy."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='read-', dir=directory)
    os.close(fd)
    try:
        with open_shared_read(path) as src, open(name, 'wb') as dst:
            src.seek(max(0, offset))
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        with open(name, 'rb') as dst:
            return dst.read()
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass


def read_bytes(path, offset, directory):
    """Read from offset to EOF. On contention, copy then parse. The log stays put."""
    try:
        return _read_once(path, offset)
    except OSError as error:
        if not _is_contention(error):
            raise
        return _copy_then_read(path, offset, directory)


def file_size(path):
    """Size only. Used to place a future-only watermark without parsing history."""
    with open_shared_read(path) as handle:
        return os.fstat(handle.fileno()).st_size, os.fstat(handle.fileno())


def complete_lines(data, offset):
    """Return finished lines and the offset just past the last newline.

    Bytes after the final newline are a half-written line and are not returned.
    The offset does not advance into them.
    """
    if not data:
        return [], offset
    last = data.rfind(b'\n')
    if last < 0:
        return [], offset
    lines = [line for line in data[:last + 1].splitlines() if line.strip()]
    return lines, offset + last + 1
