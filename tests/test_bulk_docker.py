from pathlib import Path
import subprocess
import tempfile
import unittest
from shell_support import shell
from unittest.mock import Mock

import yaml

from execution_engines.main import ExecutionEngine
from execution_engines.result import ExecutionResult


class BulkDockerTests(unittest.TestCase):
    def command(self, mode):
        engine = ExecutionEngine()
        engine._run_diagnostics = Mock(return_value=ExecutionResult())
        parameters = {'mode': mode, 'target': 'remote', 'host': 'lab', 'use_sudo': True}
        engine._troubleshoot_docker(parameters)
        args = engine._run_diagnostics.call_args
        self.assertEqual(args.args[0], parameters)
        self.assertTrue(args.kwargs['use_sudo'])
        self.assertTrue(args.kwargs['fail_on_error'])
        return args.args[1][0][1][2]

    def simulate(self, mode, ids='abc def', list_code=0, action_code=0):
        # The shell function intercepts every Docker call; no Docker daemon is used.
        script = self.command(mode)
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'calls'
            fake = f'''docker() {{
if [ "$2" = ls ]; then printf '%s' '{ids}'; return {list_code}; fi
printf '%s\\n' "$*" >> "$1_LOG"
return {action_code}
}}
'''.replace('"$1_LOG"', '"$CALL_LOG"')
            import os
            result = subprocess.run([shell(), '-c', fake + script],
                env=dict(os.environ, CALL_LOG=str(log)), capture_output=True, text=True)
            return result, log.read_text().splitlines() if log.exists() else []

    def test_stop_and_remove_each_container_without_volume_flags(self):
        for mode, operation in [('containers_stop_all', 'stop'), ('containers_remove_all', 'rm --force')]:
            result, calls = self.simulate(mode)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(calls, [f'container {operation} abc', f'container {operation} def'])

    def test_empty_host_is_noop_and_list_failure_never_mutates(self):
        for code in (0, 1):
            result, calls = self.simulate('containers_remove_all', ids='', list_code=code)
            self.assertEqual(result.returncode, code)
            self.assertEqual(calls, [])

    def test_action_failure_is_reported_after_attempting_remaining_containers(self):
        result, calls = self.simulate('containers_stop_all', action_code=1)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(calls), 2)

    def test_menu_nesting_and_confirmations(self):
        menu = yaml.safe_load(Path('menus/troubleshooting.yaml').read_text())
        docker = next(item for item in menu['menu'] if item['label'] == 'Docker Cleanup')
        self.assertFalse(any(item['label'] == 'Container Actions' for item in docker['children']))
        self.assertTrue(any(item['label'] == 'Container Actions' for item in menu['menu']))
        bulk = [item for item in docker['children'] if item.get('parameters', {}).get('mode') in
                {'containers_stop_all', 'containers_remove_all'}]
        self.assertEqual(len(bulk), 2)
        for item in bulk:
            self.assertTrue(item['confirm'])
            self.assertTrue(item['confirm_phrase'])
