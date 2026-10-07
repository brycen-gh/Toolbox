"""Exercise deployment decisions without requiring a Docker daemon."""
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

import yaml

from execution_engines.docker_engines import home, moodle
from execution_engines.main import ExecutionEngine
from execution_engines.result import ExecutionResult
from execution_engines.settings import load_variables, shared_container_variables


BASE = Path(__file__).resolve().parents[1]


class MoodleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.engine = ExecutionEngine(BASE)
        self.variables = load_variables(BASE / "variables/deployment-variables.yaml")
        self.variables["MOODLE_RECREATE"] = False
        self.variables["MOODLE_DATA_VOLUME"] = str(self.root / "stack")
        self.commands = []
        self.occupied = []
        self.owner = "toolbox-moodle"
        self.fail_up = False
        self.fail_config = False
        self.missing_image = False
        self.addCleanup(patch.stopall)
        patch.object(self.engine, "_docker_read", side_effect=self.docker_read).start()
        patch.object(self.engine, "_run_steps", side_effect=self.run_steps).start()

    def docker_read(self, command):
        if command[:2] == ["container", "ls"]:
            return "\n".join(self.occupied)
        if command[:2] == ["container", "inspect"]:
            if "compose.project" in command[3]:
                return self.owner
            return "database" if command[-1] == "moodle-database" else "moodle"
        if self.missing_image:
            raise RuntimeError("Image missing")
        return "[]"

    def run_steps(self, commands):
        self.commands.extend(commands)
        failed = ((self.fail_up and any("up" in c for c in commands))
                  or (self.fail_config and any("config" in c for c in commands)))
        return ExecutionResult([], 1 if failed else 0)

    def deploy(self):
        return self.engine.execute("deploy_moodle", variables=self.variables)

    def test_install_persistence_health_and_private_credentials(self):
        result = self.deploy()
        self.assertEqual(0, result.returncode)
        root = self.root / "stack"
        document = yaml.safe_load((root / "compose.yaml").read_text())
        web, db = (document["services"][key] for key in ("moodle", "database"))
        self.assertEqual("http://localhost:8082", web["environment"]["SITE_URL"])
        self.assertEqual(["8082:8080"], web["ports"])
        self.assertNotIn("ports", db)
        self.assertEqual("service_healthy", web["depends_on"]["database"]["condition"])
        self.assertEqual({"/var/www/moodledata"}, {v["target"] for v in web["volumes"]})
        password = (root / "secrets/database_password").read_text()
        self.assertEqual(password, web["environment"]["DB_PASS"])
        self.assertEqual(password, db["environment"]["POSTGRES_PASSWORD"])
        for secret in (root / "secrets").iterdir():
            self.assertNotIn(secret.read_text(), str(result.output) + str(self.commands))
        self.assertIn("--wait", self.commands[-1])
        self.assertIn("never", self.commands[-1])
        self.occupied = ["moodle", "moodle-database"]
        self.variables["MOODLE_RECREATE"] = True
        self.assertEqual(0, self.deploy().returncode)
        self.assertEqual(password, (root / "secrets/database_password").read_text())
        self.assertIn("--force-recreate", self.commands[-1])

    def test_existing_containers_require_recreate(self):
        self.occupied = ["moodle"]
        self.assertEqual(1, self.deploy().returncode)
        self.assertFalse(self.commands)
        self.assertFalse((self.root / "stack").exists())

    def test_foreign_containers_are_not_adopted(self):
        self.occupied = ["moodle"]
        self.owner = "another-project"
        self.variables["MOODLE_RECREATE"] = True
        with self.assertRaisesRegex(ValueError, "another deployment"):
            self.deploy()
        self.assertFalse(self.commands)

    def test_missing_credentials_are_not_regenerated(self):
        self.deploy()
        secret = self.root / "stack/secrets/database_password"
        secret.unlink()
        self.commands.clear()
        with self.assertRaisesRegex(ValueError, "credentials are missing"):
            self.deploy()
        self.assertFalse(secret.exists())
        self.assertFalse(any("up" in command for command in self.commands))

    def test_missing_image_does_not_initialize_data(self):
        self.missing_image = True
        with self.assertRaisesRegex(ValueError, "Save/Update Images"):
            self.deploy()
        self.assertFalse((self.root / "stack").exists())

    def test_failed_config_preserves_previous_compose(self):
        self.deploy()
        path = self.root / "stack/compose.yaml"
        previous = path.read_bytes()
        self.variables["MOODLE_SITE_NAME"] = "Changed_title"
        self.fail_config = True
        self.commands.clear()
        self.assertEqual(1, self.deploy().returncode)
        self.assertEqual(previous, path.read_bytes())
        self.assertFalse(any("up" in command for command in self.commands))

    def test_failed_start_retains_data_and_reports_failure(self):
        self.fail_up = True
        result = self.deploy()
        self.assertEqual(1, result.returncode)
        self.assertIn("did not complete", " ".join(result.output))
        self.assertTrue((self.root / "stack/secrets/admin_password").is_file())
        self.assertFalse(any("down" in command for command in self.commands))

    def test_compose_dollar_escaping(self):
        self.variables["MOODLE_SITE_NAME"] = "Course_$UNSET_${NOT_DEFINED}"
        self.deploy()
        document = yaml.safe_load((self.root / "stack/compose.yaml").read_text())
        self.assertEqual("Course_$$UNSET_$${NOT_DEFINED}", document["services"]["moodle"]["environment"]["MOODLE_SITENAME"])

    def test_site_name_with_spaces_is_rejected_before_docker(self):
        self.variables["MOODLE_SITE_NAME"] = "Training Moodle"
        with self.assertRaisesRegex(ValueError, "MOODLE_SITE_NAME.*whitespace"):
            self.deploy()
        self.assertFalse(self.commands)
        self.assertFalse((self.root / "stack").exists())

    def test_default_initial_admin_password_preserves_existing_secret(self):
        result = self.deploy()
        secret = self.root / 'stack/secrets/admin_password'
        self.assertEqual('GGpassword1!', secret.read_text())
        self.assertNotIn('GGpassword1!', str(result.output))
        secret.write_text('ExistingPassword2!')
        self.deploy()
        self.assertEqual('ExistingPassword2!', secret.read_text())

    def test_public_port_is_reported_to_php(self):
        for url, expected in [('http://localhost:8082', 8082),
                              ('http://lab.example', 80),
                              ('https://lab.example:8443', 8443)]:
            with self.subTest(url=url):
                self.variables['MOODLE_SITE_URL'] = url
                self.deploy()
                document = yaml.safe_load((self.root / 'stack/compose.yaml').read_text())
                script = document['services']['moodle']['environment']['POST_CONFIGURE_COMMANDS']
                fixture = self.root / 'fastcgi_params'
                fixture.write_text('fastcgi_param  SERVER_PORT        $server_port;\nfastcgi_param  HTTP_HOST $http_host;\n')
                script = script.replace('/etc/nginx/fastcgi_params', str(fixture))
                for _ in range(2):
                    subprocess.run(['sh', '-ec', script], check=True)
                self.assertIn(f'SERVER_PORT        {expected};', fixture.read_text())
                self.assertIn('HTTP_HOST $http_host;', fixture.read_text())

    def test_reject_invalid_public_urls_and_ports(self):
        for url in ("ftp://host", "http://user:pass@host", "http://host/?secret=x", "http://host/#fragment", "http://host/subpath", "http://host:99999", "http://bad host"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                moodle.validate_site_url(url)
        self.variables["MOODLE_HOST_PORT"] = 0
        with self.assertRaises(ValueError):
            self.deploy()

    def test_menu_variables_and_portal_wiring(self):
        context = self.engine._expand_context(self.variables)
        for filename in ("deployment.yaml", "troubleshooting.yaml"):
            menu = yaml.safe_load((BASE / "menus" / filename).read_text(encoding="utf-8"))
            combined = {**load_variables(BASE / "variables/troubleshooting-variables.yaml"), **self.variables}
            resolved = self.engine._resolve(menu, self.engine._expand_context(combined))
            self.assertNotIn("${MOODLE_", str(resolved))
        self.assertEqual("moodle-database", shared_container_variables(BASE)["MOODLE_DATABASE_CONTAINER_NAME"])
        parameters = self.engine._resolve(home.PARAMETERS, context)
        entry = next(item for item in parameters["services"] if item["name"] == "Moodle")
        self.assertEqual("http://localhost:8082", entry["url"])
        self.assertEqual({"name", "url", "description"}, set(entry))


if __name__ == "__main__":
    unittest.main()
