from pathlib import Path
import unittest
import tempfile
from unittest.mock import Mock, patch
from contextlib import ExitStack

import yaml

from execution_engines.main import ExecutionEngine
from execution_engines.result import ExecutionResult
from execution_engines.settings import load_variables
from execution_engines.docker_engines.registry import DEPLOYMENTS, deployment_parameters


class DockerEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = ExecutionEngine()
        self.variables = load_variables(Path('variables/deployment-variables.yaml'))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.variables['HOME_DATA_VOLUME'] = directory.name
        self.variables['ETHERPAD_DATA_VOLUME'] = directory.name + '/etherpad'
        self.variables['CTFD_DATA_VOLUME'] = directory.name + '/ctfd'
        self.engine._run_steps = Mock(return_value=ExecutionResult())
        self.engine._run_container = Mock(return_value=ExecutionResult())
        self.engine._deploy_zulip = Mock(return_value=ExecutionResult())

    def test_install_menus_dispatch_to_service_recipes(self):
        menu = yaml.safe_load(Path('menus/deployment.yaml').read_text())
        def walk(items):
            for item in items:
                yield item
                yield from walk(item.get('children', []))
        installs = [item for item in walk(menu['menu'])
                    if item.get('action_id') in DEPLOYMENTS]
        self.assertEqual({item['action_id'] for item in installs}, set(DEPLOYMENTS))
        with ExitStack() as stack:
            handlers = {action: stack.enter_context(patch.object(module, 'deploy', return_value=ExecutionResult()))
                        for action, module in DEPLOYMENTS.items()}
            engine = ExecutionEngine()
            for item in installs:
                with self.subTest(service=item['label']):
                    self.assertNotIn('parameters', item)
                    result = engine.execute(item['action_id'], variables=self.variables)
                    self.assertEqual(result.returncode, 0)
                    handler = handlers[item['action_id']]
                    handler.assert_called_once()
                    self.assertIs(handler.call_args.args[0], engine)
                    params = handler.call_args.args[1]
                    self.assertNotIn('${', str(params).replace('${GENERATED_SECRET}', 'secret'))
                    self.assertIn('name', params)

    def test_saved_settings_expand_in_service_specific_ports_and_environment(self):
        self.variables['OPENPROJECT_HOST_PORT'] = 8181
        self.engine.execute('deploy_open_project', variables=self.variables)
        params = self.engine._run_container.call_args.args[0]
        self.assertEqual(params['ports'], ['8181:80'])
        self.assertEqual(params['environment']['OPENPROJECT_HOST__NAME'], 'localhost:8181')
        self.assertEqual(params['environment']['SECRET_KEY_BASE'], '${GENERATED_SECRET}')
        self.engine.execute('deploy_portainer', variables=self.variables)
        params = self.engine._run_container.call_args.args[0]
        self.assertEqual(len(params['ports']), 2)
        self.assertIn('/var/run/docker.sock:/var/run/docker.sock', params['volumes'])

    def test_overrides_and_handler_mutations_do_not_modify_recipes(self):
        overrides = {'ports': ['9999:80']}
        params = deployment_parameters('deploy_open_project', overrides)
        params['ports'].append('1234:1234')
        params['environment']['SECRET_KEY_BASE'] = 'changed'
        self.assertEqual(overrides, {'ports': ['9999:80']})
        original = deployment_parameters('deploy_open_project')
        self.assertEqual(original['ports'], ['${OPENPROJECT_HOST_PORT}:${OPENPROJECT_CONTAINER_PORT}'])
        self.assertEqual(original['environment']['SECRET_KEY_BASE'], '${OPENPROJECT_SECRET_KEY_BASE}')


if __name__ == '__main__':
    unittest.main()
