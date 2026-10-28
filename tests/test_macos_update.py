import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import macos_update as update
import launcher
import build_macos
import server
from update_queue import UpdateQueue


class MacUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.version='1.1.0'; self.body=b'synthetic package bytes'
        self.digest=hashlib.sha256(self.body).hexdigest()
        self.identity={'version':update.VERSION,'teamId':'TESTTEAM01','architecture':'arm64'}
        self.real_publisher=update.publisher
        for mocked in (patch.object(update,'publisher',return_value=self.identity),
                       patch.object(update,'IDENTITY',None),
                       patch.object(update.release,'github_token',return_value='synthetic-only')):
            mocked.start();self.addCleanup(mocked.stop)
        self.name=f'eznest-shop-arm64-{self.version}.pkg'
        self.url='https://github.com/ezdesigns/eznest/releases/download/v1.1.0/'+self.name
        self.catalog=[{'tag_name':'v1.1.0','draft':False,'prerelease':False,'assets':[
            {'name':self.name,'browser_download_url':self.url},
            {'name':self.name+'.sha256','browser_download_url':self.url+'.sha256'}]}]
        self.state=patch.dict(update.STATE,{'busy':False,'message':'','error':None},clear=True)
        self.state.start(); self.addCleanup(self.state.stop)

    def request(self,operation='download'):
        return {'operation':operation,'repo':'ezdesigns/eznest','api':'https://api.github.com/repos/ezdesigns/eznest/releases?per_page=20',
                'token':'synthetic-only','current':'1.0.0','architecture':'arm64','testChannel':False,'output':str(self.root/'download')}

    def network(self,url,token,*_):
        self.assertEqual(token,'synthetic-only')
        if 'api.github.com' in url: return io.BytesIO(json.dumps(self.catalog).encode())
        if url.endswith('.sha256'): return io.BytesIO((self.digest+'  '+self.name).encode())
        self.assertEqual(url,self.url)
        return io.BytesIO(self.body)

    def downloaded(self,request):
        Path(request['output']).write_bytes(self.body)
        return {'ok':True,'latest':self.version,'name':self.name,'sha256':self.digest,'size':len(self.body),'updateAvailable':True}

    def test_release_selection_requires_exact_architecture_unique_asset_and_newer_version(self):
        self.assertEqual(update.selected(self.catalog,'1.0.0','arm64',False)[2],self.version)
        self.assertIsNone(update.selected(self.catalog,'1.1.0','arm64',False))
        with self.assertRaises(ValueError): update.selected(self.catalog,'1.0.0','x86_64',False)
        self.catalog[0]['assets'].append(dict(self.catalog[0]['assets'][0]))
        with self.assertRaises(ValueError): update.selected(self.catalog,'1.0.0','arm64',False)

    def test_prerelease_tag_cannot_bypass_stable_channel(self):
        self.catalog[0]['tag_name']='v1.2.0-rc.1'
        self.catalog[0]['assets'][0]['name']='eznest-shop-arm64-1.2.0-rc.1.pkg'
        self.assertIsNone(update.selected(self.catalog,'1.0.0','arm64',False))
        self.assertEqual(update.selected(self.catalog,'1.0.0','arm64',True)[2],'1.2.0-rc.1')

    def test_catalog_download_checksum_and_size_bound(self):
        with patch.object(update.release,'_open',side_effect=lambda opener,*args:self.network(*args)):
            result=update.worker_work(self.request())
        self.assertEqual(result['sha256'],self.digest)
        self.assertEqual((self.root/'download').read_bytes(),self.body)
        (self.root/'download').unlink()
        self.digest='0'*64
        with patch.object(update.release,'_open',side_effect=lambda opener,*args:self.network(*args)):
            with self.assertRaisesRegex(ValueError,'checksum'): update.worker_work(self.request())
        (self.root/'download').unlink()
        with patch.object(update,'MAX_BYTES',3), patch.object(update.release,'_open',side_effect=lambda opener,*args:self.network(*args)):
            with self.assertRaisesRegex(ValueError,'too large'): update.worker_work(self.request())

    def test_untrusted_asset_url_is_rejected_before_download(self):
        self.catalog[0]['assets'][0]['browser_download_url']='https://attacker.example/pkg'
        with patch.object(update.release,'_open',return_value=io.BytesIO(json.dumps(self.catalog).encode())) as network:
            with self.assertRaisesRegex(ValueError,'URL'): update.worker_work(self.request())
            self.assertEqual(network.call_count,1)
        self.assertFalse((self.root/'download').exists())

    def test_signature_requires_same_installer_team_trust_and_notarization(self):
        package=self.root/'update.pkg'; package.write_bytes(self.body)
        def runner(team='TESTTEAM01',trusted=True,notarized=True,identifier='io.jeezlabs.eznest.shop',version='1.1.0',status='signed by a certificate trusted by macOS'):
            def run(args,**_):
                if '--expand' in args:
                    root=Path(args[-1]);root.mkdir()
                    (root/'PackageInfo').write_text(f'<pkg-info identifier="{identifier}" version="{version}"/>')
                text=(f'Status: {status}\n 1. Developer ID Installer: Synthetic ({team})\n'
                      if '--check-signature' in args else 'source=Notarized Developer ID' if notarized else 'source=Developer ID')
                return subprocess.CompletedProcess(args,0 if trusted else 1,text,'')
            return run
        update.verify_package(package,'TESTTEAM01','1.1.0',runner=runner())
        update.verify_package(package,'TESTTEAM01','1.1.0',runner=runner(status='signed by a developer certificate issued by Apple for distribution'))
        for overrides in ({'team':'OTHERTEAM1'},{'trusted':False},{'notarized':False},{'identifier':'other.product'},{'version':'1.0.0'},
                          {'status':'unsigned'},{'status':'signed by an untrusted certificate'}):
            with self.assertRaises(ValueError): update.verify_package(package,'TESTTEAM01','1.1.0',runner=runner(**overrides))

    def test_unsigned_pilot_never_reads_release_credentials(self):
        with patch.object(update.runtime,'active',return_value=False), patch.object(update.release,'github_token') as token:
            self.assertFalse(update.start(self.root)['managedSupported'])
            token.assert_not_called()
        with self.assertRaisesRegex(ValueError,'installed'): self.real_publisher()

    def test_download_failure_leaves_no_staged_package(self):
        with patch.object(update,'enabled',return_value=True), patch.object(update,'run_worker',side_effect=self.downloaded), \
             patch.object(update,'verify_package',side_effect=ValueError('bad publisher')):
            update._perform(self.root,'download','stable')
        self.assertIsNone(update.pending(self.root))
        self.assertFalse((self.root/'macos-updates/download.partial').exists())
        self.assertFalse(update.STATE['busy']); self.assertIn('current app stays running',update.STATE['error'])

    def test_untrusted_publisher_cannot_read_credentials_or_start_network(self):
        with patch.object(update,'enabled',return_value=True),patch.object(update,'publisher',side_effect=ValueError('untrusted')), \
             patch.object(update,'run_worker') as worker:
            update._perform(self.root,'download','stable')
            worker.assert_not_called();update.release.github_token.assert_not_called()
        self.assertIsNone(update.IDENTITY)

    def test_signed_download_stages_then_preference_change_blocks_install(self):
        with patch.object(update,'enabled',return_value=True), patch.object(update,'run_worker',side_effect=self.downloaded), \
             patch.object(update,'verify_package'),patch.object(update,'publisher',return_value=self.identity):
            update._perform(self.root,'download','stable')
            path,info=update.package_path(self.root)
            self.assertEqual(path.read_bytes(),self.body); self.assertTrue(info['staged'])
        with patch.object(update,'enabled',return_value=False):
            with self.assertRaises(ValueError): update.package_path(self.root)

    def test_preference_changed_during_signature_check_does_not_stage(self):
        gate=[True]
        def verify(*_): gate[0]=False
        with patch.object(update,'enabled',side_effect=lambda _:gate[0]), patch.object(update,'run_worker',side_effect=self.downloaded), \
             patch.object(update,'verify_package',side_effect=verify):
            update._perform(self.root,'download','stable')
        self.assertIsNone(update.pending(self.root))
        self.assertFalse((self.root/'macos-updates/download.partial').exists())

    def test_download_runs_outside_server_admission_and_is_not_duplicated(self):
        entered=threading.Event(); release=threading.Event()
        def download(request):
            entered.set(); self.assertTrue(release.wait(3)); return self.downloaded(request)
        with patch.object(update,'enabled',return_value=True), patch.object(update,'publisher',return_value=self.identity), \
             patch.object(update,'run_worker',side_effect=download) as worker, patch.object(update,'verify_package'):
            try:
                self.assertTrue(update.start(self.root,'download')['busy'])
                self.assertTrue(entered.wait(3))
                self.assertTrue(update.start(self.root,'download')['busy'])
                self.assertEqual(worker.call_count,1)
            finally:
                release.set(); update.THREAD.join(3)
                self.assertFalse(update.THREAD.is_alive())

    @unittest.skipUnless(os.name=='posix','Child PID liveness check')
    def test_whole_operation_deadline_kills_and_reaps_worker(self):
        pidfile=self.root/'pid'
        script='import os,time;from pathlib import Path;Path('+repr(str(pidfile))+').write_text(str(os.getpid()));time.sleep(60)'
        with patch.object(update,'CHECK_TIMEOUT',.3),patch.object(update,'worker_command',return_value=[sys.executable,'-c',script]):
            with self.assertRaises(subprocess.TimeoutExpired):update.run_worker(self.request('check'))
        pid=int(pidfile.read_text())
        with self.assertRaises(ProcessLookupError):os.kill(pid,0)

    def test_worker_error_response_does_not_echo_input(self):
        result=subprocess.run(update.worker_command(),input='{"operation":"not allowed","token":"PRIVATE_SENTINEL"}',capture_output=True,text=True,timeout=3)
        self.assertEqual(result.returncode,1);self.assertEqual(json.loads(result.stdout),{'ok':False})
        self.assertNotIn('PRIVATE_SENTINEL',result.stdout+result.stderr)

    def test_only_exact_install_action_dispatches_to_interactive_helper(self):
        for args in (['--request-macos-update'],['eznest-update://install']):
            with patch.object(sys,'argv',['eznest',*args]),patch.object(update,'request_install',return_value=0) as install:
                self.assertEqual(launcher.main(),0);install.assert_called_once_with()
        with patch.object(sys,'argv',['eznest','eznest-update://install?file=/tmp/evil.pkg']),patch.object(update,'request_install') as install:
            with self.assertRaises(SystemExit): launcher.main()
            install.assert_not_called()

    def test_only_service_bundle_registers_mac_update_protocol(self):
        for enabled in (False,True):
            spec=build_macos.bundle_spec(Path('/source'),Path('/build'),'arm64','1.0.0',service_edition=enabled)
            self.assertEqual('CFBundleURLTypes' in spec,enabled)
            self.assertIn('argv_emulation='+repr(enabled),spec)

    @unittest.skipUnless(os.name=='posix','Mac interactive client credentials')
    def test_interactive_client_rechecks_bytes_and_publisher_before_installer(self):
        session={'app':'eznest','version':update.VERSION,'shopService':True,'token':'synthetic-session'}
        info={'platform':'macos','staged':True,'managedSupported':True,'sha256':self.digest,'stagedVersion':self.version}
        def http_open(request,**_):
            if isinstance(request,Request):
                self.assertEqual(request.full_url,'http://127.0.0.1:8765/api/macos-update/package')
                self.assertEqual(request.get_header('X-ez-token'),'synthetic-session')
                return io.BytesIO(self.body)
            return io.BytesIO(json.dumps(session if request.endswith('/api/session') else info).encode())
        http=SimpleNamespace(open=http_open)
        with patch.object(update,'publisher',return_value=self.identity),patch.object(os,'geteuid',return_value=501), \
             patch.object(os,'getuid',return_value=501),patch.object(Path,'stat',return_value=SimpleNamespace(st_uid=501)), \
             patch.object(update,'build_opener',return_value=http),patch.object(update,'verify_package') as verify, \
             patch.object(subprocess,'run') as install:
            self.assertEqual(update.request_install(),0)
            self.assertEqual(verify.call_args.args[1:],('TESTTEAM01',self.version))
            self.assertEqual(install.call_args.args[0][:5],['/usr/bin/open','-W','-n','-a','/System/Library/CoreServices/Installer.app'])
            self.assertFalse(os.path.exists(install.call_args.args[0][-1]))
            install.reset_mock();verify.reset_mock(); info['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'changed'): update.request_install()
            verify.assert_not_called();install.assert_not_called()

    @unittest.skipUnless(os.name=='posix','Mac package file descriptors')
    def test_http_download_does_not_hold_work_admission_and_package_needs_session(self):
        entered=threading.Event();release=threading.Event()
        trust_entered=threading.Event();trust_release=threading.Event()
        def trust():
            trust_entered.set();self.assertTrue(trust_release.wait(5));return self.identity
        def download(request):
            entered.set();self.assertTrue(release.wait(5));return self.downloaded(request)
        with patch.object(server,'WORK',self.root),patch.object(server,'STATE',{'status':'idle'}), \
             patch.object(server,'UPDATE_QUEUE',UpdateQueue()),patch.object(update.runtime,'active',return_value=True), \
             patch.object(update.runtime,'maintenance',return_value=False),patch.object(update,'enabled',return_value=True), \
             patch.object(update,'publisher',side_effect=trust),patch.object(update,'run_worker',side_effect=download), \
             patch.object(update,'verify_package'):
            service=server.LocalServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
            port=patch.object(server,'PORT',service.server_address[1]);port.start()
            address='http://127.0.0.1:'+str(service.server_address[1])
            def post(path):
                request=Request(address+path,data=b'{}',headers={'Content-Type':'application/json','X-EZ-Token':server.TOKEN})
                return json.load(urlopen(request,timeout=2))
            try:
                self.assertTrue(post('/api/update')['busy']);self.assertTrue(trust_entered.wait(3))
                self.assertTrue(json.load(urlopen(address+'/api/update',timeout=2))['busy'])
                post('/api/work/discard')  # Initial codesign/Gatekeeper is held.
                update.release.github_token.assert_not_called()
                trust_release.set();self.assertTrue(entered.wait(3))
                post('/api/work/discard')  # Completes while the download remains held.
                release.set();update.THREAD.join(3)
                self.assertFalse(update.THREAD.is_alive())
                info=json.load(urlopen(address+'/api/update',timeout=2));self.assertTrue(info['staged'])
                with self.assertRaises(HTTPError) as error:urlopen(address+'/api/macos-update/package',timeout=2)
                self.assertEqual(error.exception.code,403)
                request=Request(address+'/api/macos-update/package',headers={'X-EZ-Token':server.TOKEN})
                self.assertEqual(urlopen(request,timeout=2).read(),self.body)
                path,_=update.package_path(self.root);path.write_bytes(b'tampered package bytes!')
                with self.assertRaises(HTTPError) as error:urlopen(request,timeout=2)
                self.assertEqual(error.exception.code,409)
            finally:
                trust_release.set();release.set()
                if update.THREAD:update.THREAD.join(3)
                service.shutdown();thread.join(3);service.server_close();port.stop()


if __name__=='__main__': unittest.main()
