"""Local configuration. Paths come from this file, never from a log line or a reply."""
import json
import os
from pathlib import Path

LOG_PLUGINS = ('onyx_joblog', 'summa_joblog')
PLUGIN_NAMES = ('eznest', 'onyx_joblog', 'summa_joblog', 'inventory')
SOURCE_TYPES = ('file', 'stdin', 'mounted')


class ConfigError(ValueError):
    pass


class PluginSpec:
    def __init__(self, name, enabled, source_type, path, options):
        self.name = name
        self.enabled = enabled
        self.source_type = source_type
        self.path = path
        self.options = options


class RolePaths:
    """Frozen allow-list of files this process may open. There is no add method."""

    def __init__(self, logs, view, telemetry):
        if len(logs) > 2:
            raise ConfigError('The log readers open only the ONYX log and the Summa log.')
        self.logs = frozenset(logs)
        self.view = view
        self.telemetry = telemetry

    def open_log(self, path):
        from connector.readfiles import open_shared_read
        resolved = Path(path).resolve()
        if resolved not in self.logs:
            raise PermissionError('That path is not one of the two configured logs.')
        return open_shared_read(resolved)

    def open_view(self, path):
        from connector.readfiles import open_shared_read
        resolved = Path(path).resolve()
        if self.view is None or resolved != self.view:
            raise PermissionError('That path is not the configured inventory view.')
        return open_shared_read(resolved)

    def telemetry_file(self):
        return self.telemetry


def default_settings():
    return {name: PluginSpec(name, False, 'file', None, {}) for name in PLUGIN_NAMES}


def data_directory(config_path=None):
    env = os.environ.get('EZ_NEST_CONNECTOR_DATA')
    if env:
        if '://' in env:
            raise ConfigError('The connector data folder must be a local path.')
        return Path(env)
    return Path('.local') / 'connector'


def load_settings(path):
    """Load plug-in switches and locked paths from a local JSON file."""
    if path is None:
        return default_settings(), data_directory()
    target = Path(path)
    text = str(target)
    if '://' in text:
        raise ConfigError('Config is a local file.')
    raw = json.loads(target.read_text(encoding='utf-8'))
    if not isinstance(raw, dict):
        raise ConfigError('Config must be a JSON object.')
    plugins = raw.get('plugins') if isinstance(raw.get('plugins'), dict) else {}
    specs = {}
    for name in PLUGIN_NAMES:
        specs[name] = _plugin(name, plugins.get(name) if isinstance(plugins.get(name), dict) else {}, target.parent)
    directory = data_directory(target)
    if not os.environ.get('EZ_NEST_CONNECTOR_DATA') and isinstance(raw.get('dataDir'), str) and raw['dataDir'].strip():
        if '://' in raw['dataDir']:
            raise ConfigError('The connector data folder must be a local path.')
        directory = Path(raw['dataDir'])
        if not directory.is_absolute():
            directory = (target.parent / directory).resolve()
    return specs, directory


def roles_for(specs):
    logs = []
    view = None
    telemetry = None
    for name in LOG_PLUGINS:
        spec = specs[name]
        if spec.enabled and spec.source_type in ('file', 'mounted') and spec.path is not None:
            logs.append(spec.path)
    inventory = specs['inventory']
    if inventory.enabled and inventory.path is not None:
        view = inventory.path
    eznest = specs['eznest']
    if eznest.enabled and eznest.path is not None:
        telemetry = eznest.path if eznest.path.name == 'telemetry.sqlite3' else eznest.path / 'telemetry.sqlite3'
        telemetry = telemetry.resolve()
    return RolePaths(tuple(logs), view, telemetry)


def _plugin(name, body, base):
    enabled = body.get('enabled') is True
    source = body.get('source') if isinstance(body.get('source'), dict) else {}
    if 'paths' in body or 'paths' in source:
        raise ConfigError('Each plug-in has one source, not a list of paths.')
    source_type = source.get('type') or 'file'
    if source_type not in SOURCE_TYPES:
        raise ConfigError('Source type must be file, stdin, or mounted.')
    path = None
    if source_type == 'stdin':
        if source.get('path'):
            raise ConfigError('A stdin source does not take a path.')
    else:
        raw_path = source.get('path') or ''
        if not isinstance(raw_path, str):
            raise ConfigError('A source path must be text from the config file.')
        path = _local_path(raw_path, base) if raw_path.strip() else None
    options = {}
    for key in (
        'columns', 'printers', 'delimiter', 'dateOrder', 'sizeUnit', 'kinds',
    ):
        if key in body:
            options[key] = body[key]
    _check_options(options)
    return PluginSpec(name, enabled, source_type, path, options)


def _local_path(text, base):
    if '://' in text or text.startswith('\\\\') or '\n' in text or '\r' in text:
        raise ConfigError('Paths must be local files named in config, not network addresses.')
    path = Path(text)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _check_options(options):
    if 'delimiter' in options and options['delimiter'] not in (',', ';', '\t'):
        raise ConfigError('Delimiter must be a comma, semicolon, or tab.')
    if 'dateOrder' in options and options['dateOrder'] not in ('dmy', 'mdy', 'ymd'):
        raise ConfigError('dateOrder must be dmy, mdy, or ymd.')
    if 'sizeUnit' in options and options['sizeUnit'] not in ('mm', 'cm', 'in'):
        raise ConfigError('sizeUnit must be mm, cm, or in.')
    printers = options.get('printers')
    if printers is not None:
        if not isinstance(printers, list) or len(printers) > 8 or any(not isinstance(item, str) or len(item) > 80 for item in printers):
            raise ConfigError('List at most eight printer names in the config file.')
    columns = options.get('columns')
    if columns is not None and (not isinstance(columns, list) or any(not isinstance(item, str) for item in columns)):
        raise ConfigError('Columns must be a list of names.')
    kinds = options.get('kinds')
    if kinds is not None and (not isinstance(kinds, list) or any(not isinstance(item, str) for item in kinds)):
        raise ConfigError('kinds must be a list of event names.')
