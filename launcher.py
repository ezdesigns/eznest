"""Portable entry point, also reused by the source launcher."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.request import urlopen
from urllib.error import URLError
from app_info import VERSION


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--apply-update':
        import updater
        return updater.apply_cli(sys.argv[2:])
    if len(sys.argv) == 4 and sys.argv[1] == '--document-worker':
        from pdf_io import worker
        worker(sys.argv[2],sys.argv[3])
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == '--nest-worker':
        from nesting import worker
        worker(sys.argv[2], sys.argv[3])
        return 0
    parser = argparse.ArgumentParser(description='eznest local nesting workspace')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--update-confirm', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise ValueError('Choose a local port from 1024 to 65535.')
    address = f'http://127.0.0.1:{args.port}'
    try:
        with urlopen(address+'/api/session', timeout=2) as response:
            existing = json.load(response)
    except (URLError, TimeoutError, OSError):
        existing = None
    if existing is not None:
        if existing.get('app') != 'eznest' or existing.get('version') != VERSION:
            raise RuntimeError(f'Another application or eznest version is using port {args.port}. Close it before starting this build.')
        if not args.no_browser:
            import webbrowser
            webbrowser.open(address)
        return 0
    package_root = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    data = args.data_dir or package_root / ('data' if getattr(sys, 'frozen', False) else '.local')
    data.mkdir(parents=True, exist_ok=True)
    os.environ['EZ_NEST_DATA'] = str(data.resolve())
    os.environ['EZ_NEST_PORT'] = str(args.port)
    if os.environ.get('EZ_NEST_UPDATES', '1') != '0' and not args.update_confirm:
        import updater
        if updater.handoff_if_pending(updater.install_root(), data):
            return 0
    # Do not expose development-only pages in a distributed executable.
    if getattr(sys, 'frozen', False):
        os.environ.pop('EZ_NEST_TEST_UI', None)
    from server import serve
    serve(open_browser=not args.no_browser)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        message = str(error)
        if sys.stderr:
            print(message, file=sys.stderr)
        if os.name == 'nt' and '--no-browser' not in sys.argv and '--update-confirm' not in sys.argv and '--apply-update' not in sys.argv and '--nest-worker' not in sys.argv and '--document-worker' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'eznest could not start', 0x10)
        raise SystemExit(1)
