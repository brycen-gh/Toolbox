from pathlib import Path
import shutil
import tempfile
import types
import unittest

import yaml

from execution_engines.settings import (
    CONTAINER_VARIABLE_FILES, container_variables_path, load_variables,
    save_variables, shared_container_variables,
)
from main import YamlMenuApp, save_container_settings


class VariableFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        shutil.copytree('variables', self.base / 'variables',
                        ignore=shutil.ignore_patterns('.service-secrets.json'))
        self.path = self.base / 'variables' / 'deployment-variables.yaml'

    def test_all_services_load_with_shared_values_and_cross_file_references(self):
        values = load_variables(self.path)
        self.assertIn('CONTAINER_DATA_ROOT', values)
        for service in CONTAINER_VARIABLE_FILES:
            self.assertIn(service + '_CONTAINER_NAME', values)
            self.assertIn(service + '_IMAGE', values)
        self.assertEqual(values['ZULIP_EXTERNAL_HOST'], 'localhost:${ZULIP_HTTPS_HOST_PORT}')

    def test_general_editor_saves_to_owners_without_flattening_or_touching_other_services(self):
        values = load_variables(self.path)
        other = container_variables_path(self.base, 'NEXTCLOUD')
        unchanged = other.read_bytes()
        values['ZULIP_HTTPS_HOST_PORT'] = 8444
        values['CONTAINER_IMAGE_PULL_ATTEMPTS'] = 5
        values['ZULIP_NEW_SETTING'] = 'example'
        app = types.SimpleNamespace(current_variables_file=self.path, variables=values)
        YamlMenuApp._persist_current_variables(app)
        root = yaml.safe_load(self.path.read_text())
        self.assertEqual(set(root['Includes']),
                         {'docker_variables/' + name for name in CONTAINER_VARIABLE_FILES.values()})
        self.assertNotIn('ZULIP_IMAGE', root['Variables'])
        self.assertEqual(root['Variables']['CONTAINER_IMAGE_PULL_ATTEMPTS'], 5)
        zulip = load_variables(container_variables_path(self.base, 'ZULIP'))
        self.assertEqual(zulip['ZULIP_HTTPS_HOST_PORT'], 8444)
        self.assertEqual(zulip['ZULIP_NEW_SETTING'], 'example')
        self.assertEqual(other.read_bytes(), unchanged)
        self.assertEqual(load_variables(self.path), values)

    def test_service_editor_updates_troubleshooting_names(self):
        path = container_variables_path(self.base, 'ETHERPAD')
        original = load_variables(path)
        updates = dict(original, ETHERPAD_CONTAINER_NAME='class-etherpad')
        save_container_settings(path, 'ETHERPAD', original, updates)
        self.assertEqual(shared_container_variables(self.base)['ETHERPAD_CONTAINER_NAME'], 'class-etherpad')
        with self.assertRaisesRegex(ValueError, 'changed on disk'):
            save_container_settings(path, 'ETHERPAD', original, updates)

    def test_single_file_training_settings_still_round_trip(self):
        path = self.base / 'variables' / 'training-variables.yaml'
        values = load_variables(path)
        values['TARGET_DEVICE'] = 'training0'
        save_variables(path, values)
        self.assertEqual(load_variables(path), values)
        self.assertNotIn('Includes', yaml.safe_load(path.read_text()))

    def test_missing_include_and_duplicate_keys_fail_before_saving(self):
        root_before = self.path.read_bytes()
        zulip = container_variables_path(self.base, 'ZULIP')
        document = yaml.safe_load(zulip.read_text())
        document['Variables']['CONTAINER_DATA_ROOT'] = 'duplicate'
        zulip.write_text(yaml.safe_dump(document))
        with self.assertRaisesRegex(ValueError, 'Duplicate variable'):
            save_variables(self.path, {})
        self.assertEqual(self.path.read_bytes(), root_before)
        zulip.unlink()
        with self.assertRaises(FileNotFoundError):
            load_variables(self.path)

    def test_includes_cannot_escape_variable_directory(self):
        self.path.write_text('Variables: {}\nIncludes: [../outside.yaml]\n')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            load_variables(self.path)


if __name__ == '__main__':
    unittest.main()
