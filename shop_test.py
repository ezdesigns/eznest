"""Opt-in portable trial setup. Never adopts an existing unmarked data folder."""
import json
import os
from pathlib import Path
from output_folder import OutputFolder
from shop_deploy import save_shop


def default_data_directory():
    local = os.environ.get('LOCALAPPDATA')
    if not local:
        raise ValueError('The shop trial needs a local Windows user folder.')
    return Path(local) / 'eznest-shop-trial' / 'Data'


def prepare(data):
    data = Path(data).resolve()
    marker = data / 'shop-trial.json'
    if marker.exists():
        saved = json.loads(marker.read_text(encoding='utf-8'))
        if saved != {'kind': 'eznest-shop-trial', 'version': 1}:
            raise ValueError('Unrecognized shop-trial folder. Existing files were left unchanged.')
        return
    if data.exists() and any(data.iterdir()):
        raise ValueError('This folder already has data from another setup. Choose a new shop-trial folder.')
    output = data.parent / 'TEST Output'
    if output.exists():
        raise ValueError('The TEST Output folder already exists without a trial setup. Choose a new trial folder.')
    data.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    OutputFolder(data / 'output-folder.json').connect(str(output))
    save_shop(data, False, False, updates=False, outputNetwork=False,
              setupComplete=True, printer='Shop trial - TEST output', units='in',
              thru='CutContour_Thru-cut', kiss='CutContour_Kiss-cut', hotFolder=str(output))
    marker.write_text(json.dumps({'kind': 'eznest-shop-trial', 'version': 1}), encoding='utf-8')
