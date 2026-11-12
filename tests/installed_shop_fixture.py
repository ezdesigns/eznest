"""Synthetic shop used by disposable installer acceptance tests; no customer data."""
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import job_drafts
import material_inventory as inventory
import shop_members as members


def seed(data):
    data = Path(data)
    shop = members.create(data, 'Installer acceptance shop')
    joined = members.join(data, members.invite(data)['code'], 'Test designer', 'fixture')
    revoked = members.join(data, members.invite(data)['code'], 'Removed designer', 'fixture')
    members.revoke(data, revoked['member']['id'])
    profile = {'preset-name': 'Acceptance roll', 'unit': 'mm', 'width': '500',
               'roll': '510', 'available-length': '1000', 'roll-length': '5000',
               'gap': '2', 'margin': '5', 'mark-margin': '0', 'sheet': '1000',
               'rotations': '0,90,180,270', 'auto-bleed': '0', 'bleed': '0',
               'cost': '', 'roll-cost': '', 'low-stock': '200', 'print-layout': 'sections'}
    inventory.save(data, 'acceptance-roll', profile, 0)
    inventory.reserve(data, 'acceptance-roll', 'used-job', 100, 500, 'used-layout')
    inventory.transition(data, 'used-job', 'use')
    inventory.reserve(data, 'acceptance-roll', 'waiting-job', 200, 500, 'waiting-layout')
    workspace = data / 'designers' / ('member-' + joined['member']['id'])
    workspace.mkdir(parents=True)
    artwork = json.dumps({'format': 'svg', 'parts': [{'id': 'sticker'}],
                         'svgSource': {'xml': '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'}})
    key = hashlib.sha256(artwork.encode()).hexdigest()
    job_drafts.save(workspace, {'revision': None, 'entries': [
        {'id': 'sticker', 'name': 'Synthetic sticker.svg', 'sourceFile': 'Synthetic sticker.svg',
         'role': 'required', 'sets': 1000, 'dataKey': key}],
        'fields': {'material': 'acceptance-roll', 'nesting-effort': '5'}, 'assets': {key: artwork}})
    return {'shop': shop['id'], 'member': joined['member'], 'token': joined['token'],
            'revokedToken': revoked['token'], 'inventory': inventory.read(data),
            'draft': job_drafts.public(workspace),
            'files': {str(p.relative_to(data)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in workspace.rglob('*') if p.is_file()}}


def check(data, expected):
    data = Path(data)
    assert members.status(data)['id'] == expected['shop'], 'Shop identity changed'
    assert members.member(data, expected['token']) == expected['member'], 'Returning designer needs to rejoin'
    assert members.member(data, expected['revokedToken']) is None, 'Revoked access was restored'
    assert len(members.status(data, admin=True)['members']) == 1, 'Membership changed'
    assert inventory.read(data) == expected['inventory'], 'Stock or reservations changed'
    workspace = data / 'designers' / ('member-' + expected['member']['id'])
    assert job_drafts.public(workspace) == expected['draft'], 'Saved upload changed'
    for name, digest in expected['files'].items():
        assert hashlib.sha256((data / name).read_bytes()).hexdigest() == digest, 'Saved artwork changed'


if __name__ == '__main__':
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise SystemExit('Installer fixture CLI is restricted to disposable GitHub-hosted runners.')
    action, directory, evidence = sys.argv[1:]
    if action == 'seed':
        Path(evidence).write_text(json.dumps(seed(directory)), encoding='utf-8')
    elif action == 'check':
        check(directory, json.loads(Path(evidence).read_text(encoding='utf-8')))
    else:
        raise SystemExit('Unknown fixture action')
    print('Synthetic shop, sign-in, stock, reservations and saved upload verified.')
