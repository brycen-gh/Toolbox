"""Nginx registration, variable resolution and persistent deployment contract."""
from pathlib import Path
import unittest
from unittest.mock import Mock

import yaml

from execution_engines.main import ExecutionEngine
from execution_engines.settings import load_variables, container_variables_path
from execution_engines.result import ExecutionResult


ROOT = Path(__file__).resolve().parents[1]


class NginxTests(unittest.TestCase):
    def test_registered_deployment_resolves_ports_and_keeps_both_state_mounts(self):
        engine = ExecutionEngine(ROOT)
        engine._run_container = Mock(return_value=ExecutionResult())
        values = load_variables(ROOT / 'variables/deployment-variables.yaml')
        values['CONTAINER_DATA_ROOT'] = '/tmp/toolbox-test'
        result = engine.execute('deploy_nginx', variables=values)
        self.assertEqual(result.returncode, 0)
        params = engine._run_container.call_args.args[0]
        self.assertEqual(params['ports'], ['80:80', '81:81', '443:443'])
        self.assertEqual(params['volumes'], ['/tmp/toolbox-test/nginx/data:/data',
                                          '/tmp/toolbox-test/nginx/letsencrypt:/etc/letsencrypt'])
        self.assertEqual(params['extra_args'], ['--add-host', 'host.docker.internal:host-gateway'])
        self.assertEqual(params['recreate'], 'false')
        self.assertNotIn('${', repr(params))
        self.assertTrue(container_variables_path(ROOT, 'NGINX').is_file())

    def test_menu_exposes_deploy_download_and_matching_backup_restore(self):
        menu = yaml.safe_load((ROOT / 'menus/deployment.yaml').read_text(encoding='utf-8'))
        def flatten(items):
            for item in items:
                yield item
                yield from flatten(item.get('children', []))
        items = list(flatten(menu['menu']))
        self.assertTrue(any(item.get('action_id') == 'deploy_nginx' for item in items))
        download = next(item for item in items if item.get('special') == 'image_selector')
        self.assertIn('${NGINX_IMAGE}', download['parameters']['images'])
        backups = [item for item in items if item.get('parameters', {}).get('data_directory') == '${NGINX_DATA_VOLUME}']
        self.assertEqual(len(backups), 2)
        self.assertEqual({item['parameters']['backup_directory'] for item in backups}, {'${BACKUP_DIRECTORY}/nginx'})
        troubleshooting = yaml.safe_load((ROOT / 'menus/troubleshooting.yaml').read_text(encoding='utf-8'))
        actions = [item for item in flatten(troubleshooting['menu'])
                   if item.get('parameters', {}).get('container') == '${NGINX_CONTAINER_NAME}']
        self.assertEqual({item['parameters']['mode'] for item in actions},
                         {'container_logs', 'container_restart', 'container_remove'})


if __name__ == '__main__':
    unittest.main()
