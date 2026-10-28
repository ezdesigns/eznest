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
    if sys.argv[1:2] == ['--macos-service-helper']:
        from macos_service_system import main as service_helper
        return service_helper(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == '--request-shop-update':
        import managed_update
        return managed_update.request()
    if len(sys.argv) > 1 and sys.argv[1] == '--apply-update':
        import installer_update
        return installer_update.apply_cli(sys.argv[2:])
    if len(sys.argv) in (4, 5) and sys.argv[1] == '--document-worker':
        from pdf_io import worker
        worker(*sys.argv[2:])
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == '--nest-worker':
        from nesting import worker
        worker(sys.argv[2], sys.argv[3])
        return 0
    parser = argparse.ArgumentParser(description='eznest local nesting workspace')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--web', action='store_true', help='Open the simple nest page')
    parser.add_argument('--host', default=None, help='127.0.0.1; use --lan for shop network access')
    parser.add_argument('--lan', action='store_true', help='Open the shop network on this computer')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--isolated', action='store_true', help='Require a separate data folder and refuse an existing server')
    parser.add_argument('--shop-test', action='store_true', help='Start a separate local trial with TEST output and updates off')
    parser.add_argument('--update-confirm', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--shop-service', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    import macos_service_runtime
    # The ordinary app opens the one installed host. It must never create a
    # second per-user stock database when the system service is offline.
    service_client = macos_service_runtime.service_edition() and not args.shop_test
    os.environ.pop('EZ_NEST_MACOS_SERVICE', None)
    if args.shop_service:
        macos_service_runtime.validate_start(args)
    elif service_client and (args.data_dir is not None or args.port != 8765 or args.lan or args.isolated):
        raise ValueError('Open the installed shop host without custom server settings.')
    if args.shop_test:
        from shop_test import default_data_directory
        args.isolated = True
        args.web = True
        args.data_dir = args.data_dir or default_data_directory()
    if args.isolated and (args.data_dir is None or args.lan):
        raise ValueError('An isolated test requires --data-dir and loopback access; do not use --lan.')
    if args.host is not None and args.host != '127.0.0.1':
        raise ValueError('Bind to 127.0.0.1 by default. Use --lan to open the shop network.')
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
        if args.shop_service:
            raise RuntimeError('The shop service port is already in use; no second host was started.')
        if args.isolated:
            raise RuntimeError(f'Port {args.port} is already in use. This isolated test will not open or change the running application.')
        if existing.get('app') != 'eznest' or existing.get('version') != VERSION:
            raise RuntimeError(f'Another application or eznest version is using port {args.port}. Close it before starting this build.')
        if service_client and existing.get('shopService') is not True:
            raise RuntimeError('The listener is not the installed shop service.')
        if not args.no_browser:
            import webbrowser
            webbrowser.open(address + page)
        return 0
    if service_client and not args.shop_service:
        raise RuntimeError('The shop service is offline. Ask the administrator to restore it; no separate stock database was created.')
    package_root = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    frozen = getattr(sys, 'frozen', False)
    data = data_directory(package_root, args.data_dir, frozen=frozen, program_files=os.environ.get('ProgramFiles'), program_data=os.environ.get('ProgramData'))
    if args.shop_test:
        from shop_test import prepare
        prepare(data)
        os.environ['EZ_NEST_UPDATES'] = '0'
    saved = load_shop(data)
    if args.lan:
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
    if not args.update_confirm and not args.shop_test:
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

