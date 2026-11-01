"""Release policy and draft publication boundaries. No network or native OS changes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import auto_release as release
from tools import macos_release as mac

COMMIT = 'a' * 40
OTHER = 'b' * 40
VERSION = '1.0.0-rc.6'
TAG = 'v' + VERSION


def event():
    return {'repository': {'full_name': release.REPO}, 'workflow_run': {
        'head_repository': {'full_name': release.REPO}, 'event': 'push', 'head_branch': 'main',
        'path': '.github/workflows/test.yml', 'head_sha': COMMIT,
        'status': 'completed', 'conclusion': 'success'}}


class FakeGitHub:
    def __init__(self):
        self.tip = COMMIT
        self.rows = []
        self.tag = None
        self.assets = []
        self.writes = []
        self.corrupt_upload = False
        self.fail_upload = None

    def releases(self):
        return iter(self.rows)

    def tag_commit(self, _tag):
        return self.tag

    def request(self, method, path, data=None, **_kwargs):
        if method == 'GET' and path.endswith('git/ref/heads/main'):
            return {'object': {'sha': self.tip}}
        if method == 'GET' and '/assets?' in path:
            return copy.deepcopy(self.assets)
        if method == 'GET' and path.endswith('/releases/7'):
            return copy.deepcopy(self.rows[0])
        self.writes.append((method, path, data))
        if method == 'POST':
            row = {**data, 'id': 7}
            self.rows.append(row)
            return row
        if method == 'PATCH':
            self.rows[0].update(data)
            return self.rows[0]
        raise AssertionError((method, path))

    def upload(self, _tag, path):
        if path.name == self.fail_upload:
            raise release.ReleaseError('Fixture upload interruption')
        self.assets.append({'name': path.name, 'digest': 'sha256:' +
                            ('0' * 64 if self.corrupt_upload else release.digest(path))})


def artifacts(root):
    win, apple = root / 'windows', root / 'macos'
    win.mkdir(); apple.mkdir()
    exe, pkg = win / 'eznest-setup.exe', apple / f'eznest-shop-arm64-{VERSION}.pkg'
    exe.write_bytes(b'synthetic windows package'); pkg.write_bytes(b'synthetic mac package')
    for path in (exe, pkg):
        path.with_name(path.name + '.sha256').write_text(release.digest(path) + '  ' + path.name + '\n')
    win_receipt = dict(version=VERSION, commit=COMMIT, sha256=release.digest(exe))
    mac_receipt = dict(version=VERSION, commit=COMMIT, sha256=release.digest(pkg), architecture='arm64',
                       applicationNotarized=True, packageNotarized=True, packageSigned=True,
                       installed=True, offlineFileFlows=True, restartPersistence=True, cleanup=True)
    (win / 'BUILD.json').write_text(json.dumps(win_receipt))
    (win / 'manifest.json').write_text(json.dumps({**win_receipt, 'filename': exe.name}))
    (apple / 'MACOS-RELEASE.json').write_text(json.dumps(mac_receipt))


class ReleasePolicyTests(unittest.TestCase):
    def test_only_successful_same_repo_main_push_can_release(self):
        for field, value in [('event','pull_request'), ('head_branch','feature'),
                             ('conclusion','failure'), ('status','in_progress'),
                             ('path','.github/workflows/other.yml'), ('head_sha','main; echo bad')]:
            payload = event(); payload['workflow_run'][field] = value
            with self.subTest(field=field), self.assertRaises(release.ReleaseError):
                release.plan(FakeGitHub(), payload, VERSION)
        payload = event(); payload['workflow_run']['head_repository']['full_name'] = 'attacker/fork'
        with self.assertRaises(release.ReleaseError): release.trusted_run(payload)

    def test_stale_ci_does_not_build_or_publish(self):
        api = FakeGitHub(); api.tip = OTHER
        self.assertFalse(release.plan(api, event(), VERSION)['should_release'])
        self.assertEqual(api.writes, [])

    def test_existing_public_version_and_used_tag_are_not_overwritten(self):
        for row, tag in [([{'tag_name':TAG,'draft':False}], COMMIT), ([], OTHER)]:
            api = FakeGitHub(); api.rows = row; api.tag = tag
            self.assertFalse(release.plan(api, event(), VERSION)['should_release'])
            self.assertEqual(api.writes, [])

    def test_version_must_be_supported_and_strictly_newer(self):
        api = FakeGitHub(); api.rows = [{'tag_name':'v1.0.0','draft':False}]
        with self.assertRaises(release.ReleaseError): release.plan(api, event(), VERSION)
        for version in ('1.0.0; echo bad','../v1','1.0.0-rc.6\nother=1','1.0'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                release.plan(FakeGitHub(), event(), version)

    def test_draft_for_another_commit_is_preserved(self):
        api = FakeGitHub(); api.rows = [{'tag_name':TAG,'draft':True,'target_commitish':OTHER}]
        with self.assertRaises(release.ReleaseError): release.plan(api, event(), VERSION)
        self.assertEqual(api.writes, [])

    def test_new_version_and_matching_draft_are_releasable(self):
        api = FakeGitHub()
        self.assertTrue(release.plan(api, event(), VERSION)['should_release'])
        api.rows = [{'tag_name':TAG,'draft':True,'target_commitish':COMMIT}]
        self.assertTrue(release.plan(api, event(), VERSION)['should_release'])


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        artifacts(self.root)
        self.api = FakeGitHub()

    def tearDown(self): self.temp.cleanup()

    def publish(self):
        return release.publish(self.api, event(), VERSION, self.root, upload=self.api.upload)

    def test_both_platforms_are_verified_before_first_remote_write(self):
        pin = self.root / 'macos/MACOS-RELEASE.json'
        row = json.loads(pin.read_text()); row['packageNotarized'] = False; pin.write_text(json.dumps(row))
        with self.assertRaises(release.ReleaseError): self.publish()
        self.assertEqual(self.api.writes, [])

    def test_source_version_checksum_and_cleanup_must_match(self):
        pin = self.root / 'macos/MACOS-RELEASE.json'
        original = json.loads(pin.read_text())
        for key, value in [('commit',OTHER),('version','0.1.0'),('sha256','0'*64),('cleanup',False)]:
            pin.write_text(json.dumps({**original,key:value}))
            with self.subTest(key=key), self.assertRaises(release.ReleaseError): self.publish()
            self.assertEqual(self.api.writes, [])
        pin.write_text(json.dumps(original))
        (self.root / 'windows/eznest-setup.exe.sha256').write_text('wrong checksum')
        with self.assertRaises(release.ReleaseError): self.publish()
        self.assertEqual(self.api.writes, [])

    def test_draft_then_all_checked_assets_then_publish(self):
        self.assertTrue(self.publish()['should_release'])
        self.assertEqual([w[0] for w in self.api.writes], ['POST','PATCH'])
        self.assertTrue(self.api.writes[0][2]['draft'])
        self.assertFalse(self.api.writes[-1][2]['draft'])
        self.assertEqual(self.api.writes[0][2]['target_commitish'],COMMIT)
        self.assertEqual(len(self.api.assets),7)
        before = copy.deepcopy(self.api.writes)
        self.assertFalse(self.publish()['should_release'])
        self.assertEqual(self.api.writes,before)

    def test_failed_upload_stays_draft_and_missing_identical_assets_resume(self):
        self.api.fail_upload = 'BUILD.json'
        with self.assertRaises(release.ReleaseError): self.publish()
        self.assertTrue(self.api.rows[0]['draft'])
        self.assertFalse(any(w[0]=='PATCH' for w in self.api.writes))
        self.api.fail_upload = None
        self.publish()
        self.assertFalse(self.api.rows[0]['draft'])
        self.assertEqual(len({a['name'] for a in self.api.assets}),7)
        self.assertEqual(len(self.api.assets),7)

    def test_different_existing_asset_is_not_replaced(self):
        self.api.rows = [{'tag_name':TAG,'target_commitish':COMMIT,'draft':True,'id':7}]
        self.api.assets = [{'name':'eznest-setup.exe','digest':'sha256:'+'0'*64}]
        with self.assertRaises(release.ReleaseError): self.publish()
        self.assertEqual(self.api.writes,[])

    def test_uploaded_hash_mismatch_is_never_published(self):
        self.api.corrupt_upload=True
        with self.assertRaises(release.ReleaseError): self.publish()
        self.assertTrue(self.api.rows[0]['draft'])
        self.assertFalse(any(w[0]=='PATCH' for w in self.api.writes))

    def test_main_advancing_during_upload_leaves_a_private_draft(self):
        def upload(tag, path):
            self.api.upload(tag, path)
            self.api.tip = OTHER
        state = release.publish(self.api, event(), VERSION, self.root, upload=upload)
        self.assertFalse(state['should_release'])
        self.assertTrue(self.api.rows[0]['draft'])
        self.assertFalse(any(w[0] == 'PATCH' for w in self.api.writes))

    def test_draft_or_tag_mutation_during_upload_blocks_publication(self):
        for field, value in [('target_commitish', OTHER), ('tag_name', 'v0.0.1'), ('draft', False)]:
            self.api = FakeGitHub()
            def upload(tag, path):
                self.api.upload(tag, path)
                self.api.rows[0][field] = value
            with self.subTest(field=field), self.assertRaises(release.ReleaseError):
                release.publish(self.api, event(), VERSION, self.root, upload=upload)
            self.assertFalse(any(w[0] == 'PATCH' for w in self.api.writes))
        self.api = FakeGitHub()
        def upload(tag, path):
            self.api.upload(tag, path)
            self.api.tag = OTHER
        self.assertFalse(release.publish(self.api, event(), VERSION, self.root, upload=upload)['should_release'])
        self.assertTrue(self.api.rows[0]['draft'])
        self.assertFalse(any(w[0] == 'PATCH' for w in self.api.writes))

    def test_stale_commit_is_rechecked_after_builds(self):
        self.api.tip=OTHER
        self.assertFalse(self.publish()['should_release'])
        self.assertEqual(self.api.writes,[])


class MacSigningTests(unittest.TestCase):
    def test_missing_signing_material_blocks_without_os_commands(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(mac,'run') as command:
            with self.assertRaises(ValueError): mac.preflight()
            command.assert_not_called()

    def test_wrong_publisher_and_development_identity_are_rejected(self):
        values={name:'fixture' for name in mac.REQUIRED}
        values.update(MACOS_APP_IDENTITY='Apple Development: Someone (JC6858UYM9)',
                      MACOS_INSTALLER_IDENTITY='Developer ID Installer: Someone (JC6858UYM9)')
        with patch.dict(os.environ, values, clear=True), self.assertRaises(ValueError): mac.preflight()
        values['MACOS_APP_IDENTITY']='Developer ID Application: Someone (ZZZZZZZZZZ)'
        with patch.dict(os.environ, values, clear=True), self.assertRaises(ValueError): mac.preflight()

    def test_notary_waits_on_same_submission_and_requires_accepted(self):
        identifier='a'*8+'-'+'b'*4+'-'+'c'*4+'-'+'d'*4+'-'+'e'*12
        credentials={'MACOS_NOTARY_KEY_ID':'fixture','MACOS_NOTARY_ISSUER_ID':'fixture'}
        with patch.object(mac,'run',side_effect=[json.dumps({'id':identifier}),json.dumps({'status':'Accepted'})]) as command:
            self.assertEqual(mac.notarize(Path('app.zip'),Path('key.p8'),credentials),identifier)
            self.assertEqual(command.call_count,2)
            self.assertIn(identifier,command.call_args_list[1].args[0])
        with patch.object(mac,'run',side_effect=[json.dumps({'id':identifier}),json.dumps({'status':'Invalid'})]), self.assertRaises(ValueError):
            mac.notarize(Path('app.zip'),Path('key.p8'),credentials)

class AdditionalPublicationBoundaries(unittest.TestCase):
    def test_an_unchecked_asset_in_a_draft_is_never_exposed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); artifacts(root)
            api=FakeGitHub(); api.rows=[{'tag_name':TAG,'target_commitish':COMMIT,'draft':True,'id':7}]
            api.assets=[{'name':'private-diagnostics.txt','digest':'sha256:'+'0'*64}]
            with self.assertRaises(release.ReleaseError):
                release.publish(api,event(),VERSION,root,upload=api.upload)
            self.assertEqual(api.writes,[])

    def test_platform_directory_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); artifacts(root)
            linked=root/'linked'; linked.symlink_to(root, target_is_directory=True)
            with self.assertRaises(release.ReleaseError): release.checked_assets(linked,VERSION,COMMIT)

    def test_mac_finalize_requires_every_runtime_and_cleanup_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); artifacts(root)
            out=root/'macos'
            accepted=dict(version=VERSION,sha256=json.loads((out/'MACOS-RELEASE.json').read_text())['sha256'],
                installed=True,offlineFileFlows=True,persistenceVerified=True,restarted=True,
                sharingOff=True,updatesOff=True,loopbackOnly=True,cleanup=True)
            with patch.dict(os.environ,{'RUNNER_TEMP':str(root)}):
                for key in ('installed','offlineFileFlows','persistenceVerified','restarted','sharingOff','updatesOff','loopbackOnly','cleanup'):
                    (root/'eznest-macos-acceptance.json').write_text(json.dumps({**accepted,key:False}))
                    with self.subTest(key=key), self.assertRaises(ValueError): mac.finalize(out)
                (root/'eznest-macos-acceptance.json').write_text(json.dumps(accepted))
                mac.finalize(out)
                self.assertTrue(json.loads((out/'MACOS-RELEASE.json').read_text())['cleanup'])

    def test_mac_signing_cannot_touch_a_local_machine(self):
        values={name:'fixture' for name in mac.REQUIRED}
        values.update(MACOS_APP_IDENTITY='Developer ID Application: Fixture (JC6858UYM9)',
                      MACOS_INSTALLER_IDENTITY='Developer ID Installer: Fixture (JC6858UYM9)')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,values,clear=True), patch.object(mac,'run') as commands:
            import test_published_macos as acceptance
            with self.assertRaises(acceptance.AcceptanceError): mac.build(Path(folder)/'new')
            commands.assert_not_called()

class OfflineAcceptanceTests(unittest.TestCase):
    def test_offline_flow_never_pairs_and_records_only_local_evidence(self):
        import test_published_macos as acceptance
        import macos_svg_acceptance
        class API:
            def request(self, path, body=None):
                if path == '/api/telemetry/output': return 200, {'configured':False,'enabled':False}
                if path == '/api/work/discard': return 200, {}
                raise AssertionError('Unexpected API path: ' + path)
            def session(self): return {'pid':1}
            def healthy(self): return {'pid':2}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); receipt=root/'eznest-macos-acceptance.json'
            receipt.write_text(json.dumps({'installed':True,'unpairedApiOpen':True,'paired':False}))
            with patch.object(acceptance,'LocalAPI',return_value=API()), \
                 patch.object(acceptance,'preview_settings'), patch.object(acceptance,'pdf_file_flow',return_value={'format':'pdf'}), \
                 patch.object(macos_svg_acceptance,'svg_file_flow',return_value={'format':'svg'}), \
                 patch.object(acceptance,'verify_persistence') as persistence, patch.object(acceptance,'command') as command:
                acceptance.offline(root)
                self.assertEqual([e['format'] for e in persistence.call_args.args[1]],['pdf','svg'])
                self.assertEqual(command.call_count,1)
                self.assertIn('kickstart',command.call_args.args[0])
                saved=json.loads(receipt.read_text())
                self.assertFalse(saved['paired'])
                self.assertTrue(saved['offlineFileFlows'])
                self.assertTrue(saved['sharingOff'])

    def test_offline_acceptance_refuses_an_already_paired_installation(self):
        import test_published_macos as acceptance
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'eznest-macos-acceptance.json').write_text(json.dumps({'installed':True,'unpairedApiOpen':True,'paired':True}))
            with patch.object(acceptance,'LocalAPI') as api, self.assertRaises(acceptance.AcceptanceError):
                acceptance.offline(root)
            api.assert_not_called()

    def test_svg_acceptance_opens_the_simple_view_with_its_controls(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'tests/macos_svg_acceptance.py').read_text()
        self.assertIn("page.goto(ORIGIN + '/?view=simple'", source)
        simple = (root / 'web.html').read_text()
        for control in ('edit-material', 'start-nesting', 'save-destination'):
            self.assertIn('id="' + control + '"', simple)

    def test_release_workflow_keeps_secrets_and_write_access_out_of_pr_jobs(self):
        root=Path(__file__).resolve().parents[1]
        workflow=(root/'.github/workflows/auto-release.yml').read_text()
        validate=workflow.split('  validate:',1)[1].split('  plan:',1)[0]
        self.assertNotIn('secrets.',validate)
        self.assertIn("github.event_name == 'workflow_run'",workflow)
        self.assertIn('needs: [plan, windows, macos]',workflow)
        self.assertEqual(workflow.count('contents: write'),1)
        self.assertNotIn('secrets:',workflow.split('  windows:',1)[1].split('  macos:',1)[0])
        windows=(root/'.github/workflows/windows-installer.yml').read_text()
        self.assertIn('workflow_call:',windows)
        self.assertNotIn('  publish:',windows)
        self.assertNotIn('--clobber',windows)
