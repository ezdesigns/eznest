"""Compile the native Mac window with Apple's installed SDK; no third-party UI runtime."""
import argparse
import shutil
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def build(out, architecture, *, testing=False):
    if sys.platform != 'darwin' or architecture not in ('arm64', 'x86_64'):
        raise ValueError('Compile with the macOS SDK for a supported native architecture.')
    out = Path(out).resolve()
    if out.exists() or out == ROOT or out in ROOT.parents or ROOT in out.parents:
        raise ValueError('Use a new dedicated native build directory outside the source tree.')
    out.mkdir(parents=True, exist_ok=False)
    for name in ('startup-nesting.gif', 'startup-companion.png'):
        shutil.copy2(ROOT / name, out / name)
    source = ROOT / 'native/macos/EZNestDesktop.swift'
    executable = out / 'eznest-desktop'
    args = ['xcrun', '--sdk', 'macosx', 'swiftc', '-O', '-parse-as-library',
            '-swift-version', '5', '-target', f'{architecture}-apple-macos26.0',
            '-module-cache-path', str(out / 'module-cache'),
            '-framework', 'AppKit', '-framework', 'WebKit', str(source)]
    if testing:
        args += ['-D', 'EZNEST_DESKTOP_TESTING', str(ROOT / 'tests/macos_desktop_checks.swift'),
                 str(ROOT / 'tests/macos_workspace_checks.swift')]
    subprocess.run([*args, '-o', str(executable)], check=True, timeout=180)
    if not executable.is_file() or executable.is_symlink():
        raise RuntimeError('The native desktop executable was not produced.')
    return executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--architecture', required=True, choices=('arm64', 'x86_64'))
    parser.add_argument('--testing', action='store_true')
    args = parser.parse_args()
    print(build(args.out, args.architecture, testing=args.testing))


if __name__ == '__main__':
    main()
