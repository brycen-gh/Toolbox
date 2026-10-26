import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml
from execution_engines.main import ExecutionEngine
from execution_engines.result import ExecutionResult
from execution_engines.settings import persistent_secret


class DesignSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.engine = ExecutionEngine(self.directory.name)

    def prepare_deployment(self, running=True):
        self.engine._docker_read = Mock(side_effect=lambda args:
            'app\n' if args[1] == 'ls' else json.dumps([{
                'State': {'Running': running}, 'Config': {'Env': ['SECRET_KEY=existing-key']}
            }]))
        self.engine._wait_for_container = Mock()
        calls = []
        self.engine._run_steps = lambda commands: (calls.extend(commands) or ExecutionResult())
        return calls

    def test_replacement_prepared_before_old_stops_and_removed_after_health_check(self):
        calls = self.prepare_deployment()
        self.engine._wait_for_container.side_effect = lambda name: self.assertFalse(
            any(command[1] == 'rm' for command in calls))
        result = self.engine.execute('run_container', parameters={'name': 'app', 'image': 'image', 'recreate': True})
        self.assertEqual(result.returncode, 0)
        self.assertEqual([c[1] for c in calls], ['create', 'stop', 'rename', 'rename', 'start', 'rm'])
        self.assertNotIn('-f', calls[-1])

    def test_failed_startup_restores_previous_container(self):
        calls = self.prepare_deployment()
        self.engine._wait_for_container.side_effect = RuntimeError('bad startup')
        result = self.engine.execute('run_container', parameters={'name': 'app', 'image': 'image', 'recreate': True})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls[-1], ['docker', 'start', 'app'])
        self.assertEqual(calls[-2][1], 'rename')
        self.assertIn('-previous-', calls[-2][2])
        self.assertEqual(calls[-3], ['docker', 'rm', '-f', 'app'])

    def test_create_failure_leaves_old_untouched(self):
        calls = self.prepare_deployment()
        def run(commands):
            calls.extend(commands)
            return ExecutionResult(returncode=1 if commands[0][1] == 'create' else 0)
        self.engine._run_steps = run
        result = self.engine.execute('run_container', parameters={'name': 'app', 'image': 'bad', 'recreate': True})
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('stop', [c[1] for c in calls])
        self.assertNotIn('rename', [c[1] for c in calls])

    def test_cancellation_recovers_old_container(self):
        calls = self.prepare_deployment()
        def cancel(name):
            self.engine.cancel_requested.set()
            raise RuntimeError('cancelled')
        self.engine._wait_for_container.side_effect = cancel
        result = self.engine.execute('run_container', parameters={'name': 'app', 'image': 'image', 'recreate': True})
        self.assertEqual(result.returncode, 130)
        self.assertEqual(calls[-1], ['docker', 'start', 'app'])

    def test_secret_persists_and_adopts_existing_key(self):
        value = persistent_secret(self.directory.name, 'app', 'SECRET_KEY', 'existing-key')
        self.assertEqual(value, 'existing-key')
        self.assertEqual(persistent_secret(self.directory.name, 'app', 'SECRET_KEY'), value)
        other = persistent_secret(self.directory.name, 'other', 'SECRET_KEY')
        self.assertNotEqual(other, value)

    def test_existing_secret_is_used_for_replacement(self):
        calls = self.prepare_deployment()
        self.engine.execute('run_container', parameters={
            'name': 'app', 'image': 'image', 'recreate': True,
            'environment': {'SECRET_KEY': '${GENERATED_SECRET}'},
        })
        self.assertIn('SECRET_KEY=existing-key', calls[0])

    def test_target_change_locks_credentials(self):
        target = ('host-a', 22, 'training')
        self.engine.set_remote_credentials('user', 'password', target)
        self.engine.bind_remote_target(target)
        self.assertTrue(self.engine.has_remote_credentials())
        self.engine.bind_remote_target(('host-b', 22, 'training'))
        self.assertFalse(self.engine.has_remote_credentials())

    def test_shared_names_override_stale_menu_values(self):
        path = Path(self.directory.name) / 'variables' / 'deployment-variables.yaml'
        path.parent.mkdir()
        path.write_text(yaml.safe_dump({'Variables': {'ETHERPAD_CONTAINER_NAME': 'canonical'}}))
        handler = Mock(return_value=ExecutionResult())
        self.engine.actions['troubleshoot_docker'] = handler
        self.engine.execute('troubleshoot_docker', variables={'ETHERPAD_CONTAINER_NAME': 'stale'},
                            parameters={'container': '${ETHERPAD_CONTAINER_NAME}'})
        self.assertEqual(handler.call_args.args[0]['container'], 'canonical')

    def test_command_and_output_redact_secrets(self):
        text = self.engine._display_command(['docker', 'create', '-e', 'SECRET_KEY=private-value', 'image'])
        self.assertNotIn('private-value', text)
        self.assertEqual(self.engine._redact('key is private-value'), 'key is [REDACTED]')

    def test_streamed_command_output_is_delivered_once(self):
        events = []
        self.engine.output_callback = events.append
        self.engine.actions['sample'] = lambda p: self.engine._run_steps([
            [sys.executable, '-u', '-c', 'print("repeated"); print("repeated")']])
        result = self.engine.execute('sample')
        lines = ''.join(events).splitlines()
        self.assertEqual(lines.count('repeated'), 2)
        self.assertEqual(result.output, [])

    def test_host_actions_menu_contains_all_local_scenarios(self):
        menu = yaml.safe_load(Path('menus/training.yaml').read_text())
        host = next(item for item in menu['menu'] if item['label'] == 'Host Actions')
        scenario_items = [item for item in host['children'] if item.get('children')]
        found = set()
        for item in scenario_items:
            self.assertEqual(
                [child['label'] for child in item['children']],
                ['Run Exercise', 'Analyze Local Logs', 'Show Instructor Record', 'Clean Up Latest Run'],
            )
            found.add(item['children'][0]['parameters']['scenario'])
            self.assertTrue(all(child['action_id'] == 'local_host_training' for child in item['children']))
        self.assertEqual(found, self.engine.HOST_SCENARIOS)

    def test_local_host_action_explains_non_windows_requirement(self):
        with patch('execution_engines.training.platform.system', return_value='Linux'):
            result = self.engine.execute('local_host_training', parameters={
                'mode': 'run', 'scenario': 'process_creation'
            })
        self.assertEqual(result.returncode, 2)
        self.assertIn('Windows VM', result.output[0])


if __name__ == '__main__':
    unittest.main()
