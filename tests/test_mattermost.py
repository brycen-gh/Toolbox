"""Mattermost stack generation and safety checks without a Docker daemon."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

from execution_engines.docker_engines import mattermost
from execution_engines.main import ExecutionEngine
from execution_engines.result import ExecutionResult
from execution_engines.settings import load_variables


class MattermostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "stack"
        self.engine = Mock()
        self.engine._local_data_directory.return_value = self.root
        self.engine._as_bool.side_effect = lambda value, key: value
        self.engine._docker_read.return_value = ""
        self.engine._run_steps.return_value = ExecutionResult()
        self.engine._sensitive_values = set()
        self.parameters = dict(name="mattermost", database_name="mattermost-database",
            image="mattermost/mattermost-enterprise-edition:11.7.0", database_image="postgres:18-alpine",
            recreate=False, restart="unless-stopped", host_port=8065,
            site_url="http://chat.example.test:8065", data_directory=str(self.root))

    def test_stack_and_persistent_credentials(self):
        self.assertEqual(0, mattermost.deploy(self.engine, self.parameters).returncode)
        services = yaml.safe_load((self.root / "compose.yaml").read_text())["services"]
        self.assertEqual(["8065:8065"], services["mattermost"]["ports"])
        self.assertNotIn("ports", services["database"])
        self.assertEqual("/var/lib/postgresql", services["database"]["volumes"][0]["target"])
        self.assertEqual("service_healthy", services["mattermost"]["depends_on"]["database"]["condition"])
        self.assertEqual(6, len(services["mattermost"]["volumes"]))
        password = (self.root / "secrets/database_password").read_text()
        self.assertIn(password, services["mattermost"]["environment"]["MM_SQLSETTINGS_DATASOURCE"])
        self.assertNotIn(password, str(self.engine._run_steps.call_args_list))
        self.assertEqual(0, mattermost.deploy(self.engine, self.parameters).returncode)
        self.assertEqual(password, (self.root / "secrets/database_password").read_text())

    def test_existing_container_requires_recreate(self):
        self.engine._docker_read.return_value = "mattermost"
        self.assertEqual(1, mattermost.deploy(self.engine, self.parameters).returncode)
        self.engine._run_steps.assert_not_called()

    def test_permission_setup_uses_database_helper_not_shellless_app(self):
        mattermost.deploy(self.engine, self.parameters)
        command = next(call.args[0][0] for call in self.engine._run_steps.call_args_list
                       if call.args[0][0][:2] == ['docker', 'run'])
        entrypoint = command.index('--entrypoint')
        self.assertEqual(command[entrypoint + 1:entrypoint + 3],
                         ['/bin/sh', self.parameters['database_image']])
        self.assertNotIn(self.parameters['image'], command)
        self.assertEqual(command[-1], 'chown 2000:2000 /prepare/*')
        self.assertEqual(command.count('--mount'), 6)
        self.assertEqual(command[command.index('--pull') + 1], 'never')

    def test_foreign_container_is_rejected(self):
        self.parameters["recreate"] = True
        self.engine._docker_read.side_effect = ["mattermost", "other-project"]
        with self.assertRaisesRegex(ValueError, "another deployment"):
            mattermost.deploy(self.engine, self.parameters)

    def test_missing_credentials_are_not_regenerated(self):
        mattermost.deploy(self.engine, self.parameters)
        (self.root / "secrets/database_password").unlink()
        with self.assertRaisesRegex(ValueError, "credentials are missing"):
            mattermost.deploy(self.engine, self.parameters)

    def test_dispatch_expands_variables(self):
        base = Path(__file__).resolve().parents[1]
        variables = load_variables(base / "variables/deployment-variables.yaml")
        with patch.object(mattermost, "deploy", return_value=ExecutionResult()) as deploy:
            ExecutionEngine(base).execute("deploy_mattermost", variables=variables)
            self.assertNotIn("${", str(deploy.call_args.args[1]))

    def test_invalid_site_url(self):
        self.parameters["site_url"] = "bad-url"
        with self.assertRaisesRegex(ValueError, "MATTERMOST_SITE_URL"):
            mattermost.deploy(self.engine, self.parameters)
