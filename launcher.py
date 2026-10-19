"""Portable entry point, also reused by the source launcher."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.request import urlopen
from urllib.error import URLError
from app_info import VERSION
from shop_deploy import data_directory, load_shop


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--apply-update':
        import installer_update
        return installer_update.apply_cli(sys.argv[2:])
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
    parser.add_argument('--web', action='store_true', help='Open the simple nest page')
    parser.add_argument('--host', default=None, help='127.0.0.1, or 0.0.0.0 inside a local container')
    parser.add_argument('--lan', action='store_true', help='Open the shop network on this computer')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--update-confirm', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.host is not None and args.host not in ('127.0.0.1', '0.0.0.0'):
        raise ValueError('Bind to 127.0.0.1, or 0.0.0.0 inside a local container.')
    if not 1024 <= args.port <= 65535:
        raise ValueError('Choose a local port from 1024 to 65535.')
    address = f'http://127.0.0.1:{args.port}'
    page = '/web' if args.web else '/'
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
            webbrowser.open(address + page)
        return 0
    package_root = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    frozen = getattr(sys, 'frozen', False)
    data = data_directory(package_root, args.data_dir, frozen=frozen, program_files=os.environ.get('ProgramFiles'), program_data=os.environ.get('ProgramData'))
    saved = load_shop(data)
    if args.lan:
        host, lan = '0.0.0.0', True
    elif args.host == '0.0.0.0':
        host, lan = '0.0.0.0', False
    elif args.host == '127.0.0.1':
        host, lan = '127.0.0.1', False
    elif saved['lan']:
        host, lan = '0.0.0.0', True
    else:
        host, lan = '127.0.0.1', False
    data.mkdir(parents=True, exist_ok=True)
    os.environ['EZ_NEST_DATA'] = str(data.resolve())
    os.environ['EZ_NEST_PORT'] = str(args.port)
    os.environ['EZ_NEST_HOST'] = host
    os.environ['EZ_NEST_LAN'] = '1' if lan else '0'
    running = sys.modules.get('server')
    if running is not None:
        running.HOST = host
        running.PORT = args.port
        running.LAN = lan
    # Do not expose development-only pages in a distributed executable.
    if getattr(sys, 'frozen', False):
        os.environ.pop('EZ_NEST_TEST_UI', None)
    if os.environ.get('EZ_NEST_UPDATES', '1') != '0' and not args.update_confirm:
        import installer_update
        if installer_update.handoff_if_pending(installer_update.install_root(), data):
            return 0
    from server import serve
    serve(open_browser=not args.no_browser, page=page)
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
