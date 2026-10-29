"""Command line for the Shop Connector.

pair, status, disconnect, replay, and run. Replay prints events and does not
send them unless --send is given, and --send works only when this computer
is paired.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import output_pairing

from connector import client, runtime
from connector.config import ConfigError, data_directory, default_settings, load_settings
from connector.store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m connector', description='Shop Connector')
    parser.add_argument('--config', help='Local config file. Plug-in paths are read only from this file.')
    commands = parser.add_subparsers(dest='command', required=True)
    pair = commands.add_parser('pair', help='Exchange one OUTPUT pairing code for a shop key')
    pair.add_argument('code')
    commands.add_parser('status', help='Show pairing and each plug-in')
    commands.add_parser('disconnect', help='Stop sending and delete the local shop key')
    replay = commands.add_parser('replay', help='Preview events from synthetic fixtures')
    replay.add_argument('--fixtures', required=True)
    replay.add_argument('--send', action='store_true', help='POST the preview. Requires pairing.')
    run = commands.add_parser('run', help='Watch enabled plug-ins and send new events when paired')
    run.add_argument('--once', action='store_true', help='Poll one time and exit')
    args = parser.parse_args(argv)
    try:
        specs, store = _open(args.config)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    if args.command == 'pair':
        return _pair(args, store)
    if args.command == 'status':
        print(runtime.format_status(specs, store))
        return 0
    if args.command == 'disconnect':
        return _disconnect(store)
    if args.command == 'replay':
        return _replay(args, store)
    if args.command == 'run':
        return _run(args, specs, store)
    return 1


def _open(config):
    chosen = config or os.environ.get('EZ_NEST_CONNECTOR_CONFIG')
    if chosen:
        specs, directory = load_settings(chosen)
    else:
        specs, directory = default_settings(), data_directory()
    return specs, Store(directory)


def _pair(args, store):
    try:
        result = client.pair(store.directory, args.code, host_ref=store.instance_id())
    except output_pairing.PairingError as error:
        print(error, file=sys.stderr)
        return 1
    print('Connected to OUTPUT.')
    if result.get('shopName'):
        print(result['shopName'])
    return 0


def _disconnect(store):
    try:
        had = client.disconnect(store.directory)
    except output_pairing.PairingError as error:
        print(error, file=sys.stderr)
        return 1
    dropped = store.clear_outbox()
    if not had and dropped == 0:
        print('This computer is not connected with a pairing code.', file=sys.stderr)
        return 1
    print('Disconnected. Sending is stopped.')
    return 0


def _replay(args, store):
    fixtures = Path(args.fixtures)
    if not fixtures.is_dir():
        print('The fixture folder was not found.', file=sys.stderr)
        return 1
    try:
        events = runtime.replay(fixtures, store)
    except PermissionError as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(events, indent=2))
    if not args.send:
        print(f'dry run: {len(events)} events, nothing sent', file=sys.stderr)
        return 0
    token = client.token_for(store.directory)
    if not token:
        print('Pair this computer before sending.', file=sys.stderr)
        return 1
    sent = client.send_many(events, token)
    print(f'sent {sent} of {len(events)}', file=sys.stderr)
    return 0 if sent == len(events) else 1


def _run(args, specs, store):
    stream = None
    if any(spec.enabled and spec.source_type == 'stdin' for spec in specs.values()):
        stream = runtime.StdinSource(sys.stdin.buffer)
    while True:
        runtime.poll(specs, store, stdin=stream, send=True)
        if args.once:
            return 0
        time.sleep(30)
