from pathlib import Path
import subprocess
import tempfile
import tarfile
import unittest
from unittest.mock import Mock

import yaml

from execution_engines.main import ExecutionEngine
from execution_engines.result import ExecutionResult
from execution_engines.settings import load_variables
from execution_engines.docker_engines.registry import deployment_parameters


class ZulipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.engine = ExecutionEngine(self.temporary.name)
        self.engine._docker_read = Mock(return_value='')
        self.engine._run_steps = Mock(return_value=ExecutionResult())
        self.variables = load_variables(Path('variables/deployment-variables.yaml'))
        menu = yaml.safe_load(Path('menus/deployment.yaml').read_text(encoding='utf-8'))
        containers = next(item for item in menu['menu'] if item['label'] == 'Containers')
        zulip = next(item for item in containers['children'] if item['label'] == 'Zulip')
        install = next(item for item in zulip['children'] if item.get('action_id') == 'deploy_zulip')
        self.parameters = self.engine._resolve(
            deployment_parameters(install['action_id'], install.get('parameters')),
            self.engine._expand_context(self.variables))
        self.parameters['data_directory'] = str(Path(self.temporary.name) / 'stack')
        self.root = Path(self.parameters['data_directory'])

    def deploy(self):
        return self.engine.execute('deploy_zulip', parameters=self.parameters)

    def test_generated_stack_is_valid_compose_and_downloads_cover_all_images(self):
        self.assertEqual(self.deploy().returncode, 0)
        config = yaml.safe_load((self.root / 'compose.yaml').read_text(encoding='utf-8'))
        self.assertEqual(len(config['services']), 5)
        self.assertEqual(config['services']['zulip']['ports'], ['127.0.0.1:8443:443'])
        self.assertEqual(config['services']['zulip']['environment']['SETTING_REALM_HOSTS'], '{"ggsec": "localhost:8443"}')
        self.assertEqual(len(config['secrets']), 5)
        menu = yaml.safe_load(Path('menus/deployment.yaml').read_text(encoding='utf-8'))
        prep = next(item for item in menu['menu'] if item['label'] == 'Prep Install')
        pull = next(item for item in prep['children'] if item.get('action_id') == 'pull_images')
        images = self.engine._resolve(pull['parameters']['images'], self.engine._expand_context(self.variables))
        for name, service in config['services'].items():
            self.assertIn(service['image'], images)
            self.assertEqual(service['pull_policy'], 'never')
            if name != 'zulip':
                self.assertNotIn('ports', service)
        validation = subprocess.run(['docker', 'compose', '-p', 'test-zulip', '-f',
                                     str(self.root / 'compose.yaml'), 'config', '--quiet'],
                                    capture_output=True, text=True)
        self.assertEqual(validation.returncode, 0, validation.stderr)

    def test_rerun_preserves_secrets(self):
        self.deploy()
        original = {path.name: path.read_bytes() for path in (self.root / 'secrets').iterdir()}
        self.deploy()
        self.assertEqual(original, {path.name: path.read_bytes() for path in (self.root / 'secrets').iterdir()})
        self.assertTrue(all(value.decode() in self.engine._sensitive_values for value in original.values()))

    def test_missing_secret_on_existing_stack_is_rejected(self):
        self.deploy()
        path = self.root / 'secrets' / 'postgres_password'
        path.chmod(0o600)  # Windows requires write permission to delete a read-only file.
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'secrets are missing'):
            self.deploy()
        self.assertFalse(path.exists())

    def test_existing_stack_requires_recreate_before_any_writes(self):
        self.engine._docker_read.return_value = 'zulip\n'
        self.assertEqual(self.deploy().returncode, 1)
        self.assertFalse(self.root.exists())
        self.engine._run_steps.assert_not_called()

    def test_unrelated_container_is_not_adopted(self):
        self.parameters['recreate'] = True
        self.engine._docker_read.side_effect = ['zulip\n', 'another-project']
        with self.assertRaisesRegex(ValueError, 'another deployment'):
            self.deploy()
        self.assertFalse(self.root.exists())

    def test_missing_image_fails_before_creating_stack(self):
        self.engine._docker_read.side_effect = ['', RuntimeError('not found')]
        with self.assertRaisesRegex(ValueError, 'Load Saved Images'):
            self.deploy()
        self.assertFalse(self.root.exists())

    def test_failed_initialization_never_starts_web_service(self):
        calls = []
        def run(commands):
            for command in commands:
                calls.append(command)
                if 'app:init' in command:
                    return ExecutionResult(returncode=9)
            return ExecutionResult()
        self.engine._run_steps = run
        self.assertEqual(self.deploy().returncode, 9)
        self.assertFalse(any('up' in command for command in calls))

    def test_menu_actions_and_shared_names_resolve(self):
        engine = ExecutionEngine()
        for menu_path in Path('menus').glob('*.yaml'):
            menu = yaml.safe_load(menu_path.read_text(encoding='utf-8'))
            variables_path = Path('variables') / menu.get('VariablesFile', 'deployment-variables.yaml')
            values = load_variables(variables_path)
            values.update({key: value for key, value in self.variables.items() if key.endswith('_CONTAINER_NAME')})
            def walk(nodes):
                for node in nodes:
                    if 'action_id' in node:
                        self.assertIn(node['action_id'], set(engine.actions) | {
                            'configure_remote_credentials', 'lock_remote_credentials'})
                    if 'restore_action_id' in node:
                        self.assertIn(node['restore_action_id'], engine.actions)
                    resolved = engine._resolve(node.get('parameters', {}), engine._expand_context(values))
                    self.assertNotIn('${ZULIP_', str(resolved))
                    walk(node.get('children', []))
            walk(menu.get('menu', []))

    def prepare_restore(self):
        self.deploy()
        (self.root / 'database').mkdir()
        (self.root / 'database' / 'PG_VERSION').write_text('14')
        (self.root / 'database' / 'saved').write_text('snapshot')
        backup_dir = Path(self.temporary.name) / 'backups'
        backup_dir.mkdir()
        with tarfile.open(backup_dir / 'zulip.tar.gz', 'w:gz') as stream:
            stream.add(self.root, arcname='.')
        (self.root / 'database' / 'newer-file').write_text('must not survive restore')
        self.engine._running_containers = Mock(return_value=[])
        self.engine._sudo_prefix = Mock(return_value=[])
        self.engine._run_steps = ExecutionEngine._run_steps.__get__(self.engine)
        return {'data_directory': str(self.root), 'backup_directory': str(backup_dir),
                'archive_name': 'zulip.tar.gz', 'containers': ['zulip']}

    def test_restore_replaces_data_and_keeps_previous_copy(self):
        params = self.prepare_restore()
        result = self.engine.execute('restore_zulip', parameters=params)
        self.assertEqual(result.returncode, 0, result.output)
        self.assertEqual((self.root / 'database' / 'saved').read_text(encoding='utf-8'), 'snapshot')
        self.assertFalse((self.root / 'database' / 'newer-file').exists())
        old = list(self.root.parent.glob('stack-previous-*'))
        self.assertEqual(len(old), 1)
        self.assertTrue((old[0] / 'database' / 'newer-file').exists())

    def test_restore_rejects_different_images_before_touching_data(self):
        params = self.prepare_restore()
        path = self.root / 'compose.yaml'
        config = yaml.safe_load(path.read_text(encoding='utf-8'))
        config['services']['database']['image'] = 'different:version'
        path.write_text(yaml.safe_dump(config))
        with self.assertRaisesRegex(ValueError, 'matching Zulip image versions'):
            self.engine.execute('restore_zulip', parameters=params)
        self.assertTrue((self.root / 'database' / 'newer-file').exists())

    def test_restore_recovers_original_if_install_rename_fails(self):
        import os
        from unittest.mock import patch

        params = self.prepare_restore()
        run = self.engine._run_steps
        rename = os.rename
        def fail_install(commands):
            if any('-restore-' in part for part in commands[0]) and 'tar' not in commands[0]:
                return ExecutionResult(['simulated rename failure'], 1)
            return run(commands)
        def fail_rename(source, destination):
            if '-restore-' in str(source):
                raise OSError('simulated rename failure')
            return rename(source, destination)
        self.engine._run_steps = fail_install
        with patch('execution_engines.docker_engines.zulip.os.rename', side_effect=fail_rename):
            result = self.engine.execute('restore_zulip', parameters=params)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / 'database' / 'newer-file').exists())


if __name__ == '__main__':
    unittest.main()
