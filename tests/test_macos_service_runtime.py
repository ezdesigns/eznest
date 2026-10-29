import opt_out
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import sys

import launcher
import server
import macos_service_runtime as runtime
from update_queue import UpdateQueue
from build_macos_package import scripts
from macos_service_system import MacSystem


class MacServiceRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='posix','Mac account metadata uses pwd/grp')
    def test_directory_access_groups_are_distinct_from_daemon_primary_credentials(self):
        import pwd
        import grp
        account=SimpleNamespace(pw_uid=350,pw_gid=350,pw_shell='/usr/bin/false',pw_dir='/var/empty')
        group=SimpleNamespace(gr_gid=350,gr_mem=[])
        adapter=MacSystem.__new__(MacSystem)
        with patch.object(pwd,'getpwnam',return_value=account), patch.object(grp,'getgrnam',return_value=group):
            for memberships,allowed in (('350 12 61',True),('350 80',False),('350 0',False)):
                with patch.object(adapter,'run',return_value=subprocess.CompletedProcess([],0,memberships,'')):
                    if allowed: adapter.ensure_account()
                    else:
                        with self.assertRaises(ValueError): adapter.ensure_account()
            args=SimpleNamespace(shop_test=False,isolated=False,no_browser=True,data_dir=runtime.DATA,port=8765)
            st=os.stat_result((0o40750,0,0,1,350,350,0,0,0,0))
            with patch.object(runtime,'service_edition',return_value=True), patch.object(os,'getuid',return_value=350), \
                 patch.object(os,'geteuid',return_value=350) as euid, patch.object(os,'getgid',return_value=350), \
                 patch.object(os,'getegid',return_value=350) as egid, patch.object(Path,'lstat',return_value=st), \
                 patch.object(os,'getgroups',return_value=[350,12,61]) as directory_groups, patch.dict(os.environ):
                runtime.validate_start(args)
                directory_groups.assert_not_called()
                egid.return_value=80
                with self.assertRaisesRegex(ValueError,'primary group'): runtime.validate_start(args)
                egid.return_value=350; euid.return_value=0
                with self.assertRaisesRegex(ValueError,'limited service account'): runtime.validate_start(args)

    def test_source_cannot_run_privileged_installer_commands(self):
        with patch('subprocess.run') as run:
            with self.assertRaisesRegex(ValueError,'signed installer'): MacSystem()
            run.assert_not_called()

    def test_service_edition_offline_never_creates_personal_inventory(self):
        with patch.object(sys,'argv',['eznest','--web']), \
             patch.object(runtime,'service_edition',return_value=True), \
             patch.object(launcher,'urlopen',side_effect=URLError('offline')), \
             patch.object(launcher,'data_directory') as directory, patch.object(server,'serve') as serve:
            with self.assertRaisesRegex(RuntimeError,'no separate stock'): launcher.main()
            directory.assert_not_called(); serve.assert_not_called()

    def test_service_client_requires_daemon_identity(self):
        for is_service in (False,True):
            response=io.BytesIO(json.dumps({'app':'eznest','version':launcher.VERSION,'shopService':is_service}).encode())
            with patch.object(sys,'argv',['eznest','--no-browser']), \
                 patch.object(runtime,'service_edition',return_value=True), \
                 patch.object(launcher,'urlopen',return_value=response), patch.object(server,'serve') as serve:
                if is_service: self.assertEqual(launcher.main(),0)
                else:
                    with self.assertRaisesRegex(RuntimeError,'not the installed'): launcher.main()
                serve.assert_not_called()

    def test_privileged_helper_dispatch_does_not_import_server_lifecycle(self):
        with patch.object(sys,'argv',['eznest','--macos-service-helper','recover']), \
             patch('macos_service_system.main',return_value=0) as helper, patch.object(server,'serve') as serve:
            self.assertEqual(launcher.main(),0)
            helper.assert_called_once_with(['recover']); serve.assert_not_called()

    def test_maintenance_fail_closed_and_ticket_is_bound_to_awaiting_phase(self):
        with patch.object(runtime,'active',return_value=True):
            for phase in ('awaiting','testing','recovering'):
                with patch.object(runtime,'transaction',return_value={'ticket':'a'*32,'phase':phase}):
                    self.assertEqual(runtime.maintenance(),phase!='awaiting')
                    if phase=='awaiting': runtime.authorize_claim('a'*32)
                    else:
                        with self.assertRaises(ValueError):runtime.authorize_claim('a'*32)
                    with self.assertRaises(ValueError):runtime.authorize_claim('b'*32)
            with patch.object(runtime,'transaction',side_effect=ValueError('invalid')):
                self.assertTrue(runtime.maintenance())

    def test_package_scripts_have_volume_guard_clean_environment_and_explicit_lan(self):
        for lan in (False,True):
            values=scripts(lan=lan)
            self.assertIn('[ "$3" = / ]',values['preinstall'])
            self.assertIn('/usr/bin/env -i',values['postinstall'])
            self.assertEqual('--lan' in values['postinstall'],lan)
            self.assertNotIn('sudo',values['postinstall'])

    def test_real_http_admission_busy_cancel_maintenance_and_session_token(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(server,'WORK',Path(tmp)), patch.object(server,'STATE',{'status':'running'}), \
             patch.object(server,'UPDATE_QUEUE',UpdateQueue()), \
             patch.object(runtime,'active',return_value=True), \
             patch.object(runtime,'transaction',return_value={'ticket':'a'*32,'phase':'awaiting'}) as transaction:
            service=server.LocalServer(('127.0.0.1',0),server.Handler)
            port_patch=patch.object(server,'PORT',service.server_address[1]); port_patch.start()
            thread=threading.Thread(target=service.serve_forever,daemon=True); thread.start()
            address='http://127.0.0.1:'+str(service.server_address[1])
            def post(path,ticket='a'*32,token=True):
                headers={'Content-Type':'application/json'}
                if token: headers['X-EZ-Token']=server.TOKEN
                return json.load(urlopen(Request(address+path,data=json.dumps({'ticket':ticket}).encode(),headers=headers),timeout=3))
            try:
                with self.assertRaises(HTTPError) as error:post('/api/macos-service/claim',token=False)
                self.assertEqual(error.exception.code,403)
                with self.assertRaises(HTTPError):post('/api/macos-service/claim',ticket='b'*32)
                self.assertFalse(post('/api/macos-service/claim')['ready'])
                server.STATE.update(status='ready',deliveryCompleted=False)
                self.assertFalse(post('/api/macos-service/claim')['ready'])
                server.STATE.update(status='idle')
                self.assertTrue(post('/api/macos-service/claim')['ready'])
                with self.assertRaises(HTTPError) as error:post('/api/work/discard')
                self.assertEqual(error.exception.code,503)
                self.assertTrue(post('/api/macos-service/cancel')['ok'])
                self.assertFalse(server.UPDATE_QUEUE.stopping)
                transaction.return_value={'ticket':'a'*32,'phase':'testing'}
                with self.assertRaises(HTTPError) as error:post('/api/materials/reserve')
                self.assertEqual(error.exception.code,503)
                with self.assertRaises(HTTPError):post('/api/macos-service/cancel')
                session=json.load(urlopen(address+'/api/session',timeout=3))
                self.assertTrue(session['maintenance']); self.assertTrue(session['shopService'])
            finally:
                service.shutdown();thread.join(3);service.server_close()
                port_patch.stop()


if __name__=='__main__':unittest.main()
