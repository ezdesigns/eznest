import json
from pathlib import Path

INFO = json.loads((Path(__file__).resolve().parent / 'version.json').read_text(encoding='utf-8'))
VERSION = INFO['version']
UPDATE_CHANNEL = INFO.get('updateChannel') or ('beta' if 'beta' in VERSION else 'stable')
