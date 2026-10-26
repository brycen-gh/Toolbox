"""CTFd backups must include SQLite data from legacy containers."""
import json
from pathlib import Path
import tarfile
import tempfile
import subprocess
import unittest
from unittest.mock import Mock

from execution_engines.main import ExecutionEngine
from execution_engines.result import ExecutionResult
from execution_engines.docker_engines import ctfd


class CtfdTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = ExecutionEngine(self.temp.name)
        self.engine._docker_read = Mock(return_value=json.dumps([
            {'Config': {'Env': [], 'Image': 'ctfd/ctfd:test'}}]))
        self.engine._running_containers = Mock(return_value=['ctfd'])
        self.params = {'containers': ['ctfd'], 'backup_directory': './backups/ctfd',
                       'data_directory': str(Path(self.temp.name) / 'data'), 'archive_prefix': 'ctfd'}

    def test_legacy_database_and_uploads_captured_while_stopped(self):
        commands = []
        def steps(items):
            for command in items:
                commands.append(command)
                if command[:2] == ['docker', 'cp']:
                    target = Path(command[-1])
                    if 'CTFd/.' in command[-2]:
                        (target / 'ctfd.db').write_bytes(b'site database')
                        (target / 'ctfd.db-wal').write_bytes(b'pending data')
                    else:
                        (target / 'challenge.txt').write_text('upload')
            return ExecutionResult()
        self.engine._run_steps = steps
        def copy(command, **kwargs):
            steps([command])
            return subprocess.CompletedProcess(command, 0, '', '')
        self.engine._run_process = copy
        def archive(params):
            self.assertEqual(params['containers'], [])
            root = Path(params['data_directory'])
            self.assertEqual((root / 'database/ctfd.db').read_bytes(), b'site database')
            self.assertTrue((root / 'database/ctfd.db-wal').exists())
            self.assertTrue((root / 'uploads/challenge.txt').exists())
            self.assertTrue((root / 'ctfd-backup.json').exists())
            return ExecutionResult()
        self.engine._backup_container_data = archive
        result = ctfd.backup(self.engine, self.params)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(commands[0], ['docker', 'stop', 'ctfd'])
        self.assertEqual(commands[-1], ['docker', 'start', 'ctfd'])

    def test_copy_failure_restarts_container_and_never_archives(self):
        self.engine._run_steps = Mock(side_effect=[ExecutionResult(), ExecutionResult([], 1), ExecutionResult()])
        self.engine._backup_container_data = Mock()
        self.assertEqual(ctfd.backup(self.engine, self.params).returncode, 1)
        self.engine._backup_container_data.assert_not_called()
        self.assertEqual(self.engine._run_steps.call_args.args[0], [['docker', 'start', 'ctfd']])

    def test_empty_old_archive_rejected_before_docker_or_restore(self):
        folder = Path(self.temp.name) / 'backups/ctfd'
        folder.mkdir(parents=True)
        with tarfile.open(folder / 'old.tar.gz', 'w:gz'):
            pass
        self.engine._load_container_data = Mock()
        result = ctfd.restore(self.engine, dict(self.params, archive_name='old.tar.gz'))
        self.assertEqual(result.returncode, 2)
        self.engine._docker_read.assert_not_called()
        self.engine._load_container_data.assert_not_called()

    def test_preset_persists_database_and_uploads(self):
        self.assertIn('DATABASE_URL', ctfd.PARAMETERS['environment'])
        self.assertEqual(ctfd.PARAMETERS['environment']['UPLOAD_FOLDER'], '/var/ctfd-data/uploads')

    def test_fresh_restore_uses_staging_and_recorded_image(self):
        folder = Path(self.temp.name) / 'backups/ctfd'
        folder.mkdir(parents=True)
        source = Path(self.temp.name) / 'source'
        (source / 'database').mkdir(parents=True)
        (source / 'database/ctfd.db').write_bytes(b'database')
        (source / 'ctfd-backup.json').write_text(json.dumps({'format': 1, 'image': 'ctfd/ctfd:test'}))
        with tarfile.open(folder / 'complete.tar.gz', 'w:gz') as archive:
            archive.add(source, arcname='.')
        self.engine._docker_read.return_value = ''
        self.engine._run_steps = Mock(return_value=ExecutionResult())
        result = ctfd.restore(self.engine, dict(self.params, archive_name='complete.tar.gz'))
        self.assertEqual(result.returncode, 0)
        calls = [call.args[0][0] for call in self.engine._run_steps.call_args_list]
        self.assertIn('ctfd/ctfd:test', calls[1])
        self.assertIn('--pull', calls[1])
        self.assertIn('.restore-', calls[0][-1])
        self.assertEqual(calls[-1][-1], self.params['data_directory'])
        self.engine._running_containers.assert_not_called()

    def test_legacy_recreation_blocked(self):
        self.engine._docker_read.side_effect = ['ctfd\n', json.dumps([{'Config': {'Env': []}}])]
        self.engine._run_container = Mock()
        result = ctfd.deploy(self.engine, {'name': 'ctfd', 'recreate': True})
        self.assertEqual(result.returncode, 2)
        self.engine._run_container.assert_not_called()

    def test_absent_default_uploads_still_archives_database(self):
        def steps(commands):
            for command in commands:
                if command[:2] == ['docker', 'cp']:
                    (Path(command[-1]) / 'ctfd.db').write_bytes(b'database')
            return ExecutionResult()
        self.engine._run_steps = steps
        self.engine._run_process = Mock(return_value=subprocess.CompletedProcess([], 1,
            'Error response from daemon: Could not find the file /opt/CTFd/CTFd/uploads/. in container ctfd\n', ''))
        self.engine._backup_container_data = Mock(return_value=ExecutionResult())
        self.assertEqual(ctfd.backup(self.engine, self.params).returncode, 0)
        self.engine._backup_container_data.assert_called_once()

    def test_upload_copy_daemon_error_is_fatal(self):
        def steps(commands):
            for command in commands:
                if command[:2] == ['docker', 'cp']:
                    (Path(command[-1]) / 'ctfd.db').write_bytes(b'database')
            return ExecutionResult()
        self.engine._run_steps = steps
        self.engine._run_process = Mock(return_value=subprocess.CompletedProcess([], 1, 'permission denied', ''))
        self.engine._backup_container_data = Mock()
        self.assertEqual(ctfd.backup(self.engine, self.params).returncode, 1)
        self.engine._backup_container_data.assert_not_called()
