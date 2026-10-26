from pathlib import Path
import tempfile
import unittest
import yaml

from main import save_container_settings
from execution_engines.settings import CONTAINER_VARIABLE_FILES


class ContainerSettingsTests(unittest.TestCase):
    def test_save_preserves_other_services_and_rejects_stale_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.yaml'
            path.write_text(yaml.safe_dump({'Variables': {
                'ETHERPAD_IMAGE': 'old', 'NEXTCLOUD_IMAGE': 'unchanged',
            }}))
            original = {'ETHERPAD_IMAGE': 'old'}
            save_container_settings(path, 'ETHERPAD', original, {'ETHERPAD_IMAGE': 'new'})
            saved = yaml.safe_load(path.read_text())['Variables']
            self.assertEqual(saved, {'ETHERPAD_IMAGE': 'new', 'NEXTCLOUD_IMAGE': 'unchanged'})
            with self.assertRaisesRegex(ValueError, 'changed on disk'):
                save_container_settings(path, 'ETHERPAD', original, {'ETHERPAD_IMAGE': 'stale'})
            self.assertEqual(yaml.safe_load(path.read_text())['Variables'], saved)

    def test_every_troubleshooting_container_has_matching_editor(self):
        menu = yaml.safe_load(Path('menus/troubleshooting.yaml').read_text())
        containers = next(item for item in menu['menu'] if item['label'] == 'Container Actions')
        self.assertEqual({editor['service'] for item in containers['children'] for editor in item['children'] if editor.get('special') == 'container_settings'},
                         set(CONTAINER_VARIABLE_FILES))
        for container in containers['children']:
            editors = [item for item in container['children'] if item.get('special') == 'container_settings']
            self.assertEqual(len(editors), 1)
            self.assertIn(editors[0]['service'], CONTAINER_VARIABLE_FILES)


if __name__ == '__main__':
    unittest.main()
