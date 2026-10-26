import unittest
import shlex
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from execution_engines.main import ExecutionEngine
from execution_engines.result import ExecutionResult


class DockerInstallTests(unittest.TestCase):
    @patch('execution_engines.deployment.shutil.which', return_value=None)
    def test_apt_install_configures_matching_repository_before_packages(self, _which):
        for distro, family, repository in (
            ('ubuntu', 'debian', 'ubuntu'),
            ('debian', '', 'debian'),
            ('linuxmint', 'ubuntu debian', 'ubuntu'),
        ):
            with self.subTest(distro=distro):
                engine = ExecutionEngine()
                engine._read_os_release = Mock(return_value={'ID': distro, 'ID_LIKE': family})
                engine._sudo_prefix = Mock(return_value=['sudo'])
                engine._run_steps = Mock(return_value=ExecutionResult())
                engine._configure_docker_access = Mock(return_value=ExecutionResult())
                result = engine._install_docker({})
                self.assertEqual(result.returncode, 0)
                engine._configure_docker_access.assert_called_once()
                commands = engine._run_steps.call_args.args[0]
                self.assertTrue(all(command[0] == 'sudo' for command in commands))
                key = next(command for command in commands if command[1] == 'curl')
                self.assertIn(f'https://download.docker.com/linux/{repository}/gpg', key)
                setup = next(command for command in commands if command[1] == 'sh')
                self.assertIn(f'URIs: https://download.docker.com/linux/{repository}', setup[-1])
                self.assertIn('UBUNTU_CODENAME', setup[-1])
                self.assertIn('VERSION_CODENAME', setup[-1])
                self.assertIn('dpkg --print-architecture', setup[-1])
                packages = next(command for command in commands if 'docker-ce' in command)
                self.assertIn('docker-compose-plugin', packages)
                self.assertNotIn('docker.io', packages)
                self.assertLess(commands.index(setup), commands.index(packages) - 1)
                self.assertEqual(commands[commands.index(packages) - 1], ['sudo', 'apt-get', 'update'])
                self.assertEqual(commands[-1], ['sudo', 'systemctl', 'enable', '--now', 'docker'])

    @patch('execution_engines.deployment.shutil.which', return_value='/usr/bin/docker')
    def test_existing_docker_repairs_access_without_reinstalling(self, _which):
        engine = ExecutionEngine()
        engine._run_steps = Mock()
        engine._configure_docker_access = Mock(return_value=ExecutionResult())
        self.assertEqual(engine._install_docker({}).returncode, 0)
        engine._configure_docker_access.assert_called_once()
        engine._run_steps.assert_not_called()

    def test_access_repair_adds_user_without_replacing_existing_groups(self):
        engine = ExecutionEngine()
        engine._sudo_prefix = Mock(return_value=['sudo'])
        engine._run_steps = Mock(return_value=ExecutionResult())
        pwd = Mock()
        pwd.getpwuid.return_value.pw_name = 'vmuser'
        with patch.dict(sys.modules, {'pwd': pwd}), \
                patch('execution_engines.deployment.os.name', 'posix'), \
                patch('execution_engines.deployment.os.getuid', return_value=1000, create=True), \
                patch('execution_engines.deployment.os.geteuid', return_value=1000, create=True):
            result = engine._configure_docker_access()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(engine._run_steps.call_args.args[0], [
            ['sudo', 'groupadd', '--force', 'docker'],
            ['sudo', 'usermod', '-aG', 'docker', '--', 'vmuser'],
        ])

    def test_stale_session_uses_group_and_preserves_argument_quoting(self):
        pwd = Mock()
        pwd.getpwuid.return_value = SimpleNamespace(pw_name='vmuser', pw_gid=1000)
        grp = Mock()
        grp.getgrnam.return_value = SimpleNamespace(gr_mem=['vmuser'], gr_gid=999)
        command = ['docker', 'create', '-e', 'VALUE=spaces; $(literal)', 'image']
        with patch.dict(sys.modules, {'pwd': pwd, 'grp': grp}), \
                patch.dict('os.environ', {}, clear=True), \
                patch('execution_engines.main.os.name', 'posix'), \
                patch('execution_engines.main.os.getuid', return_value=1000, create=True), \
                patch('execution_engines.main.os.geteuid', return_value=1000, create=True), \
                patch('execution_engines.main.os.access', return_value=False), \
                patch('execution_engines.main.shutil.which', return_value='/usr/bin/sg'), \
                patch('execution_engines.main.Path') as path:
            path.return_value.exists.return_value = True
            actual = ExecutionEngine._docker_access_command(command)
            self.assertEqual(actual[:3], ['sg', 'docker', '-c'])
            self.assertEqual(shlex.split(actual[3]), command)
            with patch('execution_engines.main.shutil.which', return_value=None):
                self.assertEqual(ExecutionEngine._docker_access_command(command), ['sudo', *command])
            grp.getgrnam.return_value.gr_mem = []
            self.assertEqual(ExecutionEngine._docker_access_command(command), command)
            with patch.dict('os.environ', {'DOCKER_HOST': 'tcp://remote:2376'}):
                self.assertEqual(ExecutionEngine._docker_access_command(command), command)

    def test_read_query_fallback_passes_sudo_password_on_stdin(self):
        engine = ExecutionEngine()
        engine.set_local_sudo_password('test-password')
        engine._docker_access_command = Mock(return_value=['sudo', 'docker', 'info'])
        with patch('execution_engines.deployment.subprocess.run') as run:
            run.return_value = SimpleNamespace(returncode=0, stdout='docker info', stderr='')
            self.assertEqual(engine._docker_read(['info']), 'docker info')
            self.assertEqual(run.call_args.args[0], ['sudo', '-S', '-p', '', '--', 'docker', 'info'])
            self.assertEqual(run.call_args.kwargs['input'], 'test-password\n')
            engine._local_sudo_password = None
            engine._docker_read(['info'])
            self.assertEqual(run.call_args.args[0], ['sudo', '-n', '--', 'docker', 'info'])
            self.assertIsNone(run.call_args.kwargs['input'])


if __name__ == '__main__':
    unittest.main()
