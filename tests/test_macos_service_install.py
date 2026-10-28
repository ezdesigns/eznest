import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from contextlib import nullcontext

from macos_service_install import Installer, tree_size
import macos_service_runtime as runtime


class FakeSystem:
    """Filesystem-real transaction tests; no account, launchd or trust mutation."""
    control_gid = None

    def __init__(self, root, existing=True, fail=None):
        self.root = root
        self.app, self.data = root/'app', root/'data'
        self.recovery, self.control = root/'recovery', root/'control'
        self.config = root/'service.json'
        self.trace, self.fail = [], fail
        if existing:
            self.app.mkdir(); (self.app/'version').write_text('1.0.0')
            self.data.mkdir(); (self.data/'stock').write_text('400')
            self.config.write_text('{"limited":true}')

    def step(self, name):
        self.trace.append(name)
        if self.fail == name:
            self.fail = None
            raise RuntimeError('injected '+name)

    def lock(self): return nullcontext()
    def verify(self, path):
        return {'version':(path/'version').read_text(), 'teamId':'TESTTEAM01', 'architecture':'arm64'}
    def installed_configuration(self):
        return json.loads(self.config.read_text()) if self.config.exists() else None
    def prepare(self, recovery=False):
        self.recovery.mkdir(exist_ok=True); self.control.mkdir(exist_ok=True)
    def clear_closed_recovery(self):
        shutil.rmtree(self.recovery); self.recovery.mkdir()
    def seal_application(self, path): self.step('seal')
    def sync_tree(self, path): self.step('sync')
    def sync_directory(self, path): self.step('sync-directory')
    def preserve_data_ownership(self, source, target): pass
    def save_configuration(self, path, value): path.write_text(json.dumps(value))
    def restore_configuration(self, path): self.config.write_bytes(path.read_bytes())
    def write_configuration(self, value):
        self.step('configure'); self.save_configuration(self.config, value)
    def remove_configuration(self): self.config.unlink(missing_ok=True)
    def create_data(self): self.data.mkdir(); (self.data/'stock').write_text('0')
    def claim_idle(self, ticket): self.step('claim')
    def cancel_claim(self, ticket): self.step('cancel')
    def stop(self): self.step('stop')
    def start(self):
        self.step('start')
        # Stand in for candidate startup migrations before admission opens.
        if (self.app/'version').read_text() == '1.1.0':
            (self.data/'stock').write_text('candidate changed data')
    def confirm_health(self, version): self.step('health')
    def read_receipt(self, path): return json.loads(path.read_text())


@unittest.skipUnless(os.name == 'posix', 'Mac installation snapshots require POSIX directory synchronization')
class MacServiceInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidate = self.root/'candidate'; self.candidate.mkdir()
        (self.candidate/'version').write_text('1.1.0')

    def test_success_keeps_previous_data_and_commits_before_admission(self):
        system=FakeSystem(self.root); installer=Installer(system)
        self.assertTrue(installer.install(self.candidate)['ok'])
        self.assertEqual((system.app/'version').read_text(), '1.1.0')
        self.assertEqual((system.recovery/'data-backup/stock').read_text(), '400')
        self.assertEqual(json.loads(installer.receipt.read_text())['phase'], 'committed')
        self.assertFalse((system.control/'transaction.json').exists())
        self.assertLess(system.trace.index('claim'), system.trace.index('stop'))
        self.assertEqual(system.trace.count('start'), 1)

    def test_busy_timeout_never_stops_active_work(self):
        system=FakeSystem(self.root, fail='claim')
        with self.assertRaisesRegex(RuntimeError, 'claim'): Installer(system).install(self.candidate)
        self.assertNotIn('stop', system.trace)
        self.assertNotIn('start', system.trace)
        self.assertIn('cancel', system.trace)
        self.assertEqual((system.data/'stock').read_text(), '400')

    def test_failures_restore_previous_program_data_and_service(self):
        for failure in ('stop', 'configure', 'start', 'health'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                system=FakeSystem(Path(tmp), fail=failure); installer=Installer(system)
                with self.assertRaisesRegex(RuntimeError, failure): installer.install(self.candidate)
                self.assertEqual((system.app/'version').read_text(), '1.0.0')
                self.assertEqual((system.data/'stock').read_text(), '400')
                self.assertEqual(json.loads(installer.receipt.read_text())['phase'], 'rolled-back')
                self.assertFalse((system.control/'transaction.json').exists())
                self.assertEqual(system.trace[-1], 'health')

    def test_failed_first_install_keeps_candidate_data_out_of_service(self):
        system=FakeSystem(self.root, existing=False, fail='health')
        with self.assertRaises(RuntimeError): Installer(system).install(self.candidate, lan=True)
        self.assertFalse(system.app.exists()); self.assertFalse(system.data.exists())
        self.assertFalse(system.config.exists())
        self.assertTrue((system.recovery/'failed-data/stock').exists())

    def test_publisher_architecture_and_version_fail_before_outage(self):
        system=FakeSystem(self.root)
        (self.candidate/'version').write_text('1.0.0')
        with self.assertRaisesRegex(ValueError, 'newer'): Installer(system).install(self.candidate)
        self.assertEqual(system.trace, [])
        self.assertFalse(system.recovery.exists())

    def test_completed_transaction_recovery_never_reverts_new_shop_writes(self):
        system=FakeSystem(self.root); installer=Installer(system)
        installer.install(self.candidate)
        (system.data/'stock').write_text('300')
        installer.recover()
        self.assertEqual((system.data/'stock').read_text(), '300')
        self.assertEqual((system.app/'version').read_text(), '1.1.0')

    def test_interrupted_unclosed_receipt_refuses_another_install(self):
        system=FakeSystem(self.root); system.prepare()
        (system.recovery/'receipt.json').write_text('{"phase":"testing"}')
        with self.assertRaisesRegex(ValueError, 'recovery'): Installer(system).install(self.candidate)
        self.assertEqual(system.trace, [])

    def test_snapshot_rejects_data_links_and_external_bundle_links(self):
        external=self.root/'outside'; external.write_text('private')
        (self.candidate/'bad').symlink_to(external)
        for links in (True, False):
            with self.assertRaises(ValueError): tree_size(self.candidate, links=links)
        (self.candidate/'bad').unlink()
        (self.candidate/'inside').symlink_to('version')
        self.assertGreater(tree_size(self.candidate, links=True), 0)
        with self.assertRaises(ValueError): tree_size(self.candidate)

    @unittest.skipUnless(hasattr(os,'fork'), 'Abrupt-death test needs POSIX fork')
    def test_abrupt_death_after_configuration_keeps_reboot_admission_closed(self):
        for existing in (False,True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as tmp:
                system=FakeSystem(Path(tmp),existing=existing)
                original=system.write_configuration
                def interrupted(value):
                    original(value)
                    os._exit(77)  # Deliberately bypass exception/finally recovery.
                system.write_configuration=interrupted
                pid=os.fork()
                if pid==0:
                    try:
                        Installer(system).install(self.candidate)
                    except BaseException:
                        os._exit(78)
                    os._exit(79)
                _,status=os.waitpid(pid,0)
                self.assertEqual(os.waitstatus_to_exitcode(status),77)
                self.assertEqual((system.app/'version').read_text(),'1.1.0')
                lease=json.loads((system.control/'transaction.json').read_text())
                self.assertEqual(lease['phase'],'testing')
                # Reboot loses the in-memory queue. The durable lease alone
                # still prevents accepting stock writes into the candidate.
                with patch.object(runtime,'active',return_value=True), patch.object(runtime,'transaction',return_value=lease):
                    self.assertTrue(runtime.maintenance())
                system.write_configuration=original
                Installer(system).recover()
                if existing:
                    self.assertEqual((system.app/'version').read_text(),'1.0.0')
                    self.assertEqual((system.data/'stock').read_text(),'400')
                else:
                    self.assertFalse(system.app.exists()); self.assertFalse(system.data.exists())


if __name__ == '__main__': unittest.main()
