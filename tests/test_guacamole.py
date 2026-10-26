"""Validate the Guacamole stack without contacting Docker."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

from execution_engines.docker_engines import guacamole
from execution_engines.result import ExecutionResult
from execution_engines.main import ExecutionEngine
from execution_engines.settings import load_variables


class GuacamoleTests(unittest.TestCase):
    def test_troubleshooting_targets_all_three_saved_container_names(self):
        from execution_engines.settings import shared_container_variables
        base = Path(__file__).resolve().parents[1]
        menu = yaml.safe_load((base / "menus/troubleshooting.yaml").read_text(encoding="utf-8"))
        containers = next(item for item in menu["menu"] if item["label"] == "Container Actions")
        section = next(item for item in containers["children"] if item["label"] == "Guacamole")
        variables = load_variables(base / "variables/troubleshooting-variables.yaml")
        names = shared_container_variables(base)
        names.update(GUACAMOLE_CONTAINER_NAME="custom-guac",
                     GUACAMOLE_DATABASE_CONTAINER_NAME="custom-postgres",
                     GUACAMOLE_GUACD_CONTAINER_NAME="custom-guacd")
        modes = {}
        def check(items):
            for item in items:
                if "action_id" in item:
                    parameters = item["parameters"]
                    key = parameters["container"][2:-1]
                    modes.setdefault(names[key], set()).add(parameters["mode"])
                    for value in parameters.values():
                        if isinstance(value, str) and value.startswith("${"):
                            self.assertIn(value[2:-1], {**variables, **names})
                    if parameters["mode"] == "container_remove":
                        self.assertTrue(item["confirm"])
                        self.assertEqual("REMOVE CONTAINER", item["confirm_phrase"])
                check(item.get("children", []))
        check(section["children"])
        self.assertEqual({name: {"container_logs", "container_restart", "container_remove"}
                          for name in ("custom-guac", "custom-postgres", "custom-guacd")}, modes)

    def test_menu_dispatch_and_variable_expansion(self):
        base = Path(__file__).resolve().parents[1]
        variables = load_variables(base / "variables/deployment-variables.yaml")
        menu = yaml.safe_load((base / "menus/deployment.yaml").read_text(encoding="utf-8"))
        containers = next(item for item in menu["menu"] if item["label"] == "Containers")
        section = next(item for item in containers["children"] if item["label"] == "Guacamole")
        action = next(item for item in section["children"] if "action_id" in item)
        with patch.object(guacamole, "deploy", return_value=ExecutionResult([], 0)) as deploy:
            engine = ExecutionEngine(base)
            self.assertEqual(0, engine.execute(action["action_id"], variables=variables).returncode)
            parameters = deploy.call_args.args[1]
            self.assertNotIn("${", str(parameters))
            self.assertEqual("guacd", parameters["guacd_name"])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "stack"
        self.engine = Mock()
        self.engine._local_data_directory.return_value = self.root
        self.engine._as_bool.side_effect = lambda value, key: value
        self.engine._docker_read.return_value = ""
        self.engine._run_steps.return_value = ExecutionResult([], 0)
        self.engine._sensitive_values = set()
        self.parameters = dict(name="guacamole", database_name="guacamole-database",
                               guacd_name="guacd", image="guacamole/guacamole:1.6.0",
                               database_image="postgres:17-alpine", guacd_image="guacamole/guacd:1.6.0",
                               recreate=False, restart="unless-stopped", host_port=8085,
                               data_directory=str(self.root))

    def test_stack_initialization_and_password_persistence(self):
        self.assertEqual(0, guacamole.deploy(self.engine, self.parameters).returncode)
        services = yaml.safe_load((self.root / "compose.yaml").read_text())["services"]
        self.assertEqual(["8085:8080"], services["guacamole"]["ports"])
        self.assertNotIn("ports", services["database"])
        self.assertNotIn("ports", services["guacd"])
        self.assertEqual("5s", services["guacd"]["healthcheck"]["interval"])
        self.assertEqual(["CMD", "nc", "-z", "127.0.0.1", "4822"],
                         services["guacd"]["healthcheck"]["test"])
        self.assertEqual("service_healthy", services["guacamole"]["depends_on"]["guacd"]["condition"])
        password = (self.root / "secrets/database_password").read_text()
        self.assertEqual(password, services["database"]["environment"]["POSTGRES_PASSWORD"])
        self.assertEqual(password, services["guacamole"]["environment"]["POSTGRESQL_PASSWORD"])
        commands = self.engine._run_steps.call_args_list
        self.assertTrue(any("initdb.sh --postgresql" in str(call) for call in commands))
        self.assertNotIn(password, str(commands))
        self.assertEqual(0, guacamole.deploy(self.engine, self.parameters).returncode)
        self.assertEqual(password, (self.root / "secrets/database_password").read_text())

    def test_existing_container_requires_recreate(self):
        self.engine._docker_read.return_value = "guacamole"
        self.assertEqual(1, guacamole.deploy(self.engine, self.parameters).returncode)
        self.engine._run_steps.assert_not_called()

    def test_foreign_container_is_rejected(self):
        self.parameters["recreate"] = True
        self.engine._docker_read.side_effect = ["guacamole", "another-project"]
        with self.assertRaisesRegex(ValueError, "another deployment"):
            guacamole.deploy(self.engine, self.parameters)
        self.engine._run_steps.assert_not_called()

    def test_missing_saved_password_is_rejected(self):
        guacamole.deploy(self.engine, self.parameters)
        (self.root / "secrets/database_password").unlink()
        self.engine._run_steps.reset_mock()
        with self.assertRaisesRegex(ValueError, "credentials are missing"):
            guacamole.deploy(self.engine, self.parameters)
        self.engine._run_steps.assert_called_once_with([["docker", "compose", "version"]])

    def test_missing_image_does_not_create_data(self):
        self.engine._docker_read.side_effect = ["", RuntimeError("missing")]
        with self.assertRaisesRegex(ValueError, "unavailable"):
            guacamole.deploy(self.engine, self.parameters)
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
