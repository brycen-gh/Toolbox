"""Selector polling must not redraw idle views or launch during a view transition."""
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from main import YamlMenuApp


class ImageSelectorTests(unittest.TestCase):
    def build(self):
        events = queue.Queue()
        widgets = []
        def widget(*args, **kwargs):
            result = Mock()
            result.options = kwargs
            result.winfo_exists.return_value = True
            result.winfo_manager.return_value = 'grid'
            widgets.append(result)
            return result
        variables = []
        def variable(**kwargs):
            value = SimpleNamespace(value=kwargs['value'])
            value.get = lambda: value.value
            value.set = lambda new: setattr(value, 'value', new)
            variables.append(value)
            return value
        app = SimpleNamespace(
            execution_engine=SimpleNamespace(_expand_context=lambda values: values,
                                             _resolve=lambda params, context: params),
            variables={}, content_frame=Mock(), normal_view=Mock(), variables_view=Mock(),
            show_normal_view=Mock(), set_play_button_enabled=Mock(), after=Mock(),
            after_idle=Mock(), on_play_clicked=Mock(), action_running=False,
            copy_output_button=Mock(), show_yaml_home=Mock(),
        )
        app.on_item_click = lambda item: setattr(app, 'current_item', item)
        with patch.multiple('main.ctk', CTkFrame=widget, CTkLabel=widget,
                            CTkScrollableFrame=widget, CTkCheckBox=widget,
                            CTkButton=widget, CTkFont=Mock(), BooleanVar=variable), \
                patch('main.queue.Queue', return_value=events), patch('main.threading.Thread'):
            YamlMenuApp.show_image_selector(app, {'action_id': 'pull_images',
                                                'special': 'image_selector',
                                                'parameters': {'images': ['nginx:stable']}})
        return app, widgets, variables, events

    def test_idle_poll_does_not_redraw_and_hidden_view_stops_polling(self):
        app, widgets, _, events = self.build()
        poll = app.after.call_args.args[1]
        poll()
        self.assertTrue(all(not item.configure.called for item in widgets))
        events.put(('nginx:stable', (1024, 'test')))
        poll()
        changed = sum(item.configure.call_count for item in widgets)
        self.assertEqual(changed, 2)  # One image label and the total.
        poll()
        self.assertEqual(sum(item.configure.call_count for item in widgets), changed)
        app.images_view.winfo_manager.return_value = ''
        app.after.reset_mock()
        poll()
        app.after.assert_not_called()

    def test_download_waits_for_idle_and_ignores_navigation(self):
        app, widgets, variables, _ = self.build()
        variables[0].set(True)
        download = next(item.options['command'] for item in widgets
                        if item.options.get('text') == 'Download Selected')
        download()
        app.on_play_clicked.assert_not_called()
        action = app.current_item
        self.assertNotIn('special', action)
        self.assertEqual(action['parameters']['images'], ['nginx:stable'])
        callback = app.after_idle.call_args.args[0]
        callback()
        app.on_play_clicked.assert_called_once()
        app.on_play_clicked.reset_mock()
        app.current_item = {}
        callback()
        app.on_play_clicked.assert_not_called()


if __name__ == '__main__':
    unittest.main()
