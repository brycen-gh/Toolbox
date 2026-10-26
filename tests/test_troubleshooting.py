import base64
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from execution_engines.main import ExecutionEngine
from execution_engines import troubleshooting


class DiagnosticTargetTests(unittest.TestCase):
    def test_address_selects_target_even_with_stale_mode(self):
        for host in ("", "localhost", " LOCALHOST ", "localhost.", "127.0.0.1", "127.0.0.2", "::1"):
            with self.subTest(host=host):
                self.assertEqual(troubleshooting.TroubleshootingActions._diagnostic_target(
                    {"host": host, "target": "remote"}), "local")
        for host in ("192.168.137.53", "example.org", "10.0.0.1", "2001:db8::1"):
            with self.subTest(host=host):
                self.assertEqual(troubleshooting.TroubleshootingActions._diagnostic_target(
                    {"host": host, "target": "local"}), "remote")


@unittest.skipIf(troubleshooting.paramiko is None, "Paramiko is not installed")
class RemoteHostKeyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.engine = ExecutionEngine(self.directory.name)
        self.engine.set_remote_credentials("user", "password", ("192.168.137.53", 22))
        self.parameters = {"host": "192.168.137.53"}
        self.client = Mock()
        self.key = Mock()
        self.key.asbytes.return_value = b"server public key"
        self.key.get_name.return_value = "ssh-ed25519"

    def open_client(self):
        with patch.object(troubleshooting.Path, "home", return_value=Path(self.directory.name)), \
                patch.object(troubleshooting.paramiko, "SSHClient", return_value=self.client):
            return self.engine._open_remote_client(self.parameters)

    def test_unknown_key_explains_recovery_and_closes_connection(self):
        self.parameters["accept_new_host_key"] = False
        def connect(**kwargs):
            policy = self.client.set_missing_host_key_policy.call_args.args[0]
            policy.missing_host_key(self.client, kwargs["hostname"], self.key)

        self.client.connect.side_effect = connect
        with self.assertRaises(RuntimeError) as error:
            self.open_client()
        message = str(error.exception)
        fingerprint = base64.b64encode(hashlib.sha256(self.key.asbytes()).digest()).decode().rstrip("=")
        self.assertIn("SHA256:" + fingerprint, message)
        self.assertIn("SECURITY_ONION_ACCEPT_NEW_HOST_KEY", message)
        self.assertIn("REMOTE_ACCEPT_NEW_HOST_KEY", message)
        self.client.close.assert_called_once()

    def test_explicit_accept_uses_persistent_auto_add_policy(self):
        self.parameters["accept_new_host_key"] = True
        client, host = self.open_client()
        self.assertIs(client, self.client)
        self.assertEqual(host, self.parameters["host"])
        self.assertIsInstance(self.client.set_missing_host_key_policy.call_args.args[0],
                              troubleshooting.paramiko.AutoAddPolicy)
        self.client.load_host_keys.assert_called_once_with(
            str(Path(self.directory.name) / ".ssh" / "known_hosts"))
        self.client.close.assert_not_called()

    def test_remote_defaults_to_accepting_new_keys(self):
        self.open_client()
        self.assertIsInstance(self.client.set_missing_host_key_policy.call_args.args[0],
                              troubleshooting.paramiko.AutoAddPolicy)

    def test_changed_key_failure_is_preserved(self):
        error = troubleshooting.paramiko.BadHostKeyException(
            self.parameters["host"], self.key, Mock())
        self.client.connect.side_effect = error
        with self.assertRaises(troubleshooting.paramiko.BadHostKeyException) as raised:
            self.open_client()
        self.assertIs(raised.exception, error)
        self.client.close.assert_called_once()

    def test_local_diagnostics_do_not_open_ssh(self):
        self.engine._run_process = Mock(return_value=Mock(
            stdout="healthy", stderr="", returncode=0))
        with patch.object(self.engine, "_open_remote_client") as open_remote:
            result = self.engine._run_diagnostics(
                {"target": "local"}, [("Status", ["so-status"])])
        self.assertEqual(result.returncode, 0)
        open_remote.assert_not_called()

    def test_connection_errors_are_preserved_and_closed(self):
        self.client.connect.side_effect = OSError("connection refused")
        with self.assertRaisesRegex(OSError, "connection refused"):
            self.open_client()
        self.client.close.assert_called_once()
