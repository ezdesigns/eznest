"""Interactive Windows entry point; never elevate the shop server itself."""
import os
from pathlib import Path
import re
import subprocess
import sys


def program_directories():
    import winreg
    result = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion', 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        for name in ('ProgramFilesDir', 'ProgramFilesDir (x86)'):
            try:
                result.append(Path(winreg.QueryValueEx(key, name)[0]).resolve())
            except FileNotFoundError:
                pass
    return result


def supported(root):
    if os.name != 'nt' or root is None:
        return False
    root = Path(root).resolve()
    protected = program_directories()
    if not any(root.is_relative_to(p) and root != p for p in protected):
        return False
    try:
        thumbprint = (root / 'update-publisher.txt').read_text().strip()
    except OSError:
        return False
    return bool(re.fullmatch('[A-Fa-f0-9]{40}', thumbprint) and (root / 'update-shop.ps1').is_file() and (root / 'eznest.exe').is_file())


def request():
    if not getattr(sys, 'frozen', False):
        raise ValueError('Use the installed Windows update shortcut.')
    root = Path(sys.executable).resolve().parent
    if not supported(root):
        raise ValueError('This build is not configured for signed automatic updates. Install the checked setup manually.')
    # No URL fields, server-controlled paths or arguments enter the elevated command.
    import ctypes
    session = ctypes.c_ulong()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)) or session.value == 0:
        raise ValueError('Open Update eznest from the interactive Windows desktop.')
    system = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetSystemDirectoryW(system, len(system)):
        raise OSError('Windows system directory is unavailable.')
    shell = str(Path(system.value) / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe')
    args = subprocess.list2cmdline(['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(root / 'update-shop.ps1'), '-Run'])
    result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', shell, args, str(root), 0)
    if result <= 32:
        raise ValueError('Windows update approval was cancelled or unavailable. The app stays running.')
    return 0
