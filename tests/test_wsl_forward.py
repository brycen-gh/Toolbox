"""Validate forwarding dispatch and safe PowerShell argument construction."""
import base64
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from execution_engines.main import ExecutionEngine
from execution_engines.result import ExecutionResult


class WslForwardTests(unittest.TestCase):
    def setUp(self):
        self.engine = ExecutionEngine(Path(__file__).resolve().parents[1])
        self.engine._run_steps = Mock(return_value=ExecutionResult())

    def run_action(self, **parameters):
        with patch('execution_engines.deployment.os', SimpleNamespace(name='nt', environ={})):
            self.engine.execute('wsl_forward', parameters=dict(distro="Ubuntu's Lab", **parameters))
        command = self.engine._run_steps.call_args.args[0][0]
        self.assertEqual(command[0], 'powershell.exe')
        return base64.b64decode(command[-1]).decode('utf-16-le')

    def test_preview_quotes_distro_and_passes_normalized_ports_without_elevation(self):
        body = self.run_action(mode='preview', ports='80, 443')
        self.assertIn("-Distro 'Ubuntu''s Lab'", body)
        self.assertIn("-PortList '80,443'", body)
        self.assertNotIn('RunAs', body)

    def test_changes_elevate_helper_and_remove_is_explicit(self):
        for mode in ('apply', 'remove'):
            body = self.run_action(mode=mode)
            self.assertIn('-Verb RunAs', body)
            self.assertIn('-WindowStyle Hidden', body)
            self.assertIn('-Apply', body)
            self.assertEqual('-Remove' in body, mode == 'remove')
            self.assertIn('Get-Content -LiteralPath $log', body)

    def test_invalid_ports_and_modes_do_not_launch(self):
        for ports in ('80;whoami', '0', '65536', '80,', '-1'):
            with self.assertRaises(ValueError):
                self.run_action(mode='apply', ports=ports)
        with self.assertRaises(ValueError):
            self.run_action(mode='invalid')
        self.engine._run_steps.assert_not_called()

    def test_auto_distro_from_wsl_converts_script_path(self):
        with patch('execution_engines.deployment.os', SimpleNamespace(name='posix', environ={'WSL_DISTRO_NAME': 'Ubuntu'})), patch('execution_engines.deployment.subprocess.run', return_value=SimpleNamespace(stdout='C:\\lab\\share.ps1\n')) as convert:
            self.engine.execute('wsl_forward', parameters={'distro': 'auto'})
        self.assertEqual(convert.call_args.args[0][0], 'wslpath')
        body = base64.b64decode(self.engine._run_steps.call_args.args[0][0][-1]).decode('utf-16-le')
        self.assertIn("-Distro 'Ubuntu'", body)
        self.assertIn("& 'C:\\lab\\share.ps1'", body)


if __name__ == '__main__':
    unittest.main()
