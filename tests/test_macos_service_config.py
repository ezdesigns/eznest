import opt_out
import os
from pathlib import Path
import plistlib
import stat
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import macos_service_config as service


class MacServiceConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=Path(self.tmp.name)/'eznest.app'
        (self.app/'Contents/MacOS').mkdir(parents=True)
        (self.app/'Contents/MacOS/eznest').write_bytes(b'\xcf\xfa\xed\xfe'+struct.pack('<I',0x0100000C)+b'\0'*32)
        self.info={'CFBundleIdentifier':service.LABEL,'CFBundleExecutable':'eznest','CFBundleShortVersionString':'1.0.0','EzNestVersion':'1.0.0-rc.5'}
        (self.app/'Contents/Info.plist').write_bytes(plistlib.dumps(self.info))

    def runner(self, *, team='TESTTEAM01', runtime=True, verified=True, notarized=True):
        calls=[]
        def run(args,**kwargs):
            calls.append(args)
            if '--display' in args:
                text=f'flags=0x{0x10000 if runtime else 0:x}\nAuthority=Developer ID Application: Synthetic Publisher\nTeamIdentifier={team}\n'
                return subprocess.CompletedProcess(args,0,'',text)
            if '--verify' in args:
                return subprocess.CompletedProcess(args,0 if verified else 1,'','')
            return subprocess.CompletedProcess(args,0,'','source=Notarized Developer ID' if notarized else 'source=Developer ID')
        return run,calls

    def test_signed_candidate_requires_both_signature_and_notarized_assessment(self):
        run,calls=self.runner()
        result=service.verify_publisher(self.app,expected_team='TESTTEAM01',runner=run)
        self.assertEqual(result,{'version':'1.0.0-rc.5','architecture':'arm64','teamId':'TESTTEAM01'})
        self.assertEqual(len(calls),3)
        self.assertIn('-R=anchor apple generic and certificate leaf[subject.OU] = "TESTTEAM01"',calls[1])
        self.assertIn('--all-architectures',calls[1])
        for overrides in ({'team':'OTHERTEAM1'},{'runtime':False},{'verified':False},{'notarized':False}):
            run,_=self.runner(**overrides)
            with self.assertRaises(ValueError):service.verify_publisher(self.app,expected_team='TESTTEAM01',runner=run)

    def test_adhoc_bundle_is_rejected_before_network_assessment(self):
        calls=[]
        def run(args,**_):
            calls.append(args)
            return subprocess.CompletedProcess(args,0,'','Signature=adhoc\nTeamIdentifier=not set\n')
        with self.assertRaisesRegex(ValueError,'Developer ID'):
            service.verify_publisher(self.app,runner=run)
        self.assertEqual(len(calls),1)

    def test_metadata_rejects_wrong_app_version_architecture_and_links(self):
        self.assertEqual(service.metadata(self.app)['architecture'],'arm64')
        for field,value in [('CFBundleIdentifier','another.app'),('CFBundleExecutable','../../bin/sh'),('EzNestVersion','not-a-version'),('CFBundleShortVersionString','2.0.0')]:
            (self.app/'Contents/Info.plist').write_bytes(plistlib.dumps({**self.info,field:value}))
            with self.assertRaises(ValueError):service.metadata(self.app)
        (self.app/'Contents/Info.plist').write_bytes(plistlib.dumps(self.info))
        executable=self.app/'Contents/MacOS/eznest'
        executable.write_bytes(b'\xca\xfe\xba\xbe'+b'\0'*4)
        with self.assertRaises(ValueError):service.metadata(self.app)
        linked=Path(self.tmp.name)/'linked.app';linked.symlink_to(self.app,target_is_directory=True)
        with self.assertRaises(ValueError):service.metadata(linked)

    def test_update_cannot_switch_publisher_arch_or_downgrade(self):
        current={'teamId':'TESTTEAM01','architecture':'arm64','version':'1.0.0-rc.5'}
        service.upgrade_candidate(current,{**current,'version':'1.0.0'})
        for candidate in (current,{**current,'version':'1.0.0-beta.9'},{**current,'version':'1.1.0','teamId':'OTHERTEAM1'},{**current,'version':'1.1.0','architecture':'x86_64'}):
            with self.assertRaises(ValueError):service.upgrade_candidate(current,candidate)

    def test_launchd_uses_limited_user_fixed_data_and_explicit_lan(self):
        loopback=service.launch_configuration()
        self.assertEqual(loopback['UserName'],'_eznest')
        self.assertIs(loopback['InitGroups'],False)
        self.assertNotIn('--lan',loopback['ProgramArguments'])
        self.assertNotIn('EnvironmentVariables',loopback)
        self.assertEqual(loopback['ProgramArguments'][0],'/Applications/eznest.app/Contents/MacOS/eznest')
        self.assertIn('/Library/Application Support/eznest',loopback['ProgramArguments'])
        self.assertIn('--shop-service',loopback['ProgramArguments'])
        self.assertTrue(loopback['RunAtLoad'])
        self.assertEqual(service.launch_configuration(lan=True)['ProgramArguments'][-1],'--lan')
        self.assertEqual(plistlib.loads(plistlib.dumps(loopback)),loopback)
        for environment in ({'DYLD_INSERT_LIBRARIES':'evil.dylib'},{'EZ_NEST_OUTPUT_TOKEN':'not-a-token'},{'EZ_NEST_OUTPUT_UPLOADS':'yes'}):
            with self.assertRaises(ValueError):service.launch_configuration(environment=environment)

    def test_private_root_plist_rejects_changed_identity_and_arguments(self):
        path=Path(self.tmp.name)/'service.plist'
        config=service.launch_configuration(lan=True,environment={'EZ_NEST_OUTPUT_TOKEN':'osa_'+'A'*43,'EZ_NEST_OUTPUT_UPLOADS':'0'})
        path.write_bytes(plistlib.dumps(config))
        mode=stat.S_IFREG|0o600
        def stat_result(permission=mode,uid=0):return os.stat_result((permission,0,0,1,uid,0,path.stat().st_size,0,0,0))
        with patch.object(Path,'lstat',return_value=stat_result()):
            self.assertEqual(service.read_launch_configuration(path),config)
        for permission,uid in ((stat.S_IFREG|0o644,0),(mode,501),(stat.S_IFLNK|0o600,0)):
            with patch.object(Path,'lstat',return_value=stat_result(permission,uid)):
                with self.assertRaises(ValueError):service.read_launch_configuration(path)
        for changed in ({**config,'UserName':'root'},{**config,'ProgramArguments':['/bin/sh','-c','anything']},{**config,'EnvironmentVariables':{'HOME':'/root'}}):
            path.write_bytes(plistlib.dumps(changed))
            with patch.object(Path,'lstat',return_value=stat_result()):
                with self.assertRaises(ValueError):service.read_launch_configuration(path)


if __name__=='__main__':unittest.main()
