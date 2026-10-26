"""Real install acceptance must refuse developer and self-hosted machines."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


class TesterAcceptanceGuardTests(unittest.TestCase):
    def denied(self, command):
        for actions,runner in [('false','github-hosted'),('true','self-hosted')]:
            with self.subTest(actions=actions,runner=runner):
                env=dict(os.environ,GITHUB_ACTIONS=actions,RUNNER_ENVIRONMENT=runner)
                result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=15)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('restricted to disposable GitHub-hosted runners',result.stdout+result.stderr)

    def test_installed_app_entry_point_refuses_local_and_self_hosted(self):
        self.denied([sys.executable,str(Path(__file__).with_name('installed_tester_smoke.py'))])

    @unittest.skipUnless(os.name=='nt','Windows installer guard')
    def test_installer_entry_point_refuses_local_and_self_hosted(self):
        powershell=shutil.which('pwsh') or shutil.which('powershell')
        self.assertIsNotNone(powershell)
        self.denied([powershell,'-NoProfile','-File',str(Path(__file__).with_name('test_installed_tester.ps1'))])


if __name__=='__main__':unittest.main()
