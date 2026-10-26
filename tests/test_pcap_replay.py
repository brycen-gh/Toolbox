from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from execution_engines.main import ExecutionEngine
from execution_engines.result import ExecutionResult


class ReplayTests(unittest.TestCase):
    def test_background_replay_returns_and_can_be_stopped_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sample.pcap').write_bytes(b'pcap')
            (root / 'interface').mkdir()
            engine = ExecutionEngine(root)
            started = threading.Event()

            def run(worker, commands):
                started.set()
                worker.cancel_requested.wait(5)
                return ExecutionResult(['replay stopped'], 130)

            def resolve_path(value):
                return root / 'interface' if value == '/sys/class/net' else Path(value)

            with patch('execution_engines.training.Path', side_effect=resolve_path), \
                    patch('execution_engines.training.shutil.which', return_value='/usr/bin/tcpreplay'), \
                    patch.object(ExecutionEngine, '_sudo_prefix', return_value=[]), \
                    patch.object(ExecutionEngine, '_run_steps', run):
                # Interface lookup appends its name to /sys/class/net.
                (root / 'interface' / 'eth0').mkdir()
                parameters = {'pcap_name': 'sample', 'directory': directory,
                              'interface': 'eth0', 'background': True}
                try:
                    self.assertEqual(engine._replay_pcap(parameters).returncode, 0)
                    self.assertTrue(started.wait(1))
                    self.assertIn('running', engine._replay_status({}).output[0])
                    self.assertEqual(engine._replay_pcap(parameters).returncode, 1)
                    self.assertEqual(engine._stop_replay({}).returncode, 0)
                    self.assertFalse(engine.cancel_requested.is_set())
                    self.assertEqual(engine._replay_status({}).returncode, 130)
                    self.assertIn('replay stopped', engine._replay_status({}).output)
                finally:
                    engine._stop_replay({})


if __name__ == '__main__':
    unittest.main()
