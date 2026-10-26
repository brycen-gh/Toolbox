"""Local and remote Docker and Security Onion diagnostics."""
from __future__ import annotations

import os
import base64
import hashlib
import ipaddress
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any

try:
    import paramiko
except ImportError:
    paramiko = None

from .result import ExecutionResult
from .runtime import is_portable, known_hosts_path


class TroubleshootingActions:
    """Local and remote Docker and Security Onion diagnostics."""

    def _update_tool(self, parameters: dict[str, Any]) -> ExecutionResult:
        """Update only this checkout, preserving local edits and branch history."""
        if getattr(sys, "frozen", False):
            return ExecutionResult([
                "This packaged Toolbox release cannot be updated with Git. Close Toolbox "
                "and replace the application files from a new portable release, keeping "
                "your settings and data."
            ], 1)
        prefix = ["git", "-C", str(self.base_dir)]
        try:
            root = self._run_process(prefix + ["rev-parse", "--show-toplevel"], capture_output=True)
            if root.returncode:
                return ExecutionResult(["Tool update requires a Git checkout. Clone Toolbox first."], 1)
            if Path(root.stdout.strip()).resolve() != self.base_dir:
                return ExecutionResult(["Toolbox must be the root of its own Git checkout."], 1)
            status = self._run_process(prefix + ["status", "--porcelain", "--untracked-files=no"], capture_output=True)
            if status.returncode:
                return ExecutionResult([status.stdout or status.stderr or "Could not check local changes."], status.returncode)
            if status.stdout.strip():
                return ExecutionResult(["Save and commit or stash tracked local changes before updating Toolbox. No update was pulled."], 1)
            return self._run_steps([prefix + ["-c", f"core.hooksPath={os.devnull}", "pull", "--ff-only", "--no-rebase"]])
        except FileNotFoundError:
            return ExecutionResult(["Install Git using your preferred package manager before updating Toolbox."], 127)

    @staticmethod
    def _diagnostic_target(parameters: dict[str, Any]) -> str:
        host = str(parameters.get("host", "")).strip().casefold()
        if not host or host.rstrip(".") == "localhost":
            return "local"
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return "remote"
        return "local" if address.is_loopback else "remote"

    # Validate the requested diagnostic log length against supported limits.
    @staticmethod
    def _diagnostic_line_count(value: Any) -> int:
        try:
            lines = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("LOG_LINES must be an integer") from exc
        if not 10 <= lines <= 5000:
            raise ValueError("LOG_LINES must be between 10 and 5000")
        return lines

    # Reject malformed Docker names and image references before command construction.
    @staticmethod
    def _safe_docker_reference(value: Any, field_name: str) -> str:
        reference = str(value).strip()
        if not reference or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]*", reference):
            raise ValueError(f"{field_name} contains an invalid Docker name or reference")
        return reference

    # Connect to the selected SSH host using unlocked credentials and host-key policy.
    def _open_remote_client(self, parameters: dict[str, Any]):
        if paramiko is None:
            raise RuntimeError(
                "Remote troubleshooting requires Paramiko. Run ./run-once/run-once again "
                "after updating requirements.txt."
            )
        if not self.has_remote_credentials():
            raise RuntimeError("Remote credentials have not been unlocked for this session")

        host = str(parameters.get("host", "")).strip()
        if not host or len(host) > 253 or any(character.isspace() for character in host):
            raise ValueError("REMOTE_HOST must be a hostname or IP address without spaces")
        try:
            port = int(parameters.get("port", 22))
        except (TypeError, ValueError) as exc:
            raise ValueError("REMOTE_PORT must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ValueError("REMOTE_PORT must be between 1 and 65535")
        if not self._credential_target or self._credential_target[:2] != (host.lower(), port):
            raise RuntimeError("Unlock credentials for this specific remote target first")

        known_hosts = known_hosts_path(self.base_dir)
        known_hosts.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        known_hosts.touch(mode=0o600, exist_ok=True)
        os.chmod(known_hosts, 0o600)

        client = paramiko.SSHClient()
        if not is_portable(self.base_dir):
            client.load_system_host_keys()
        client.load_host_keys(str(known_hosts))
        if self._as_bool(parameters.get("accept_new_host_key", True), "accept_new_host_key"):
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            class ExplainUnknownHost(paramiko.MissingHostKeyPolicy):
                def missing_host_key(self, ssh_client, hostname, key):
                    fingerprint = base64.b64encode(
                        hashlib.sha256(key.asbytes()).digest()
                    ).decode("ascii").rstrip("=")
                    raise RuntimeError(
                        f"SSH host {hostname!r} is not trusted in {known_hosts}. "
                        f"Presented {key.get_name()} fingerprint: SHA256:{fingerprint}. "
                        "Verify this fingerprint with the server administrator. Then open "
                        "Training > SecOnion > Variable Settings and set "
                        "SECURITY_ONION_ACCEPT_NEW_HOST_KEY to true, or, for the "
                        "Troubleshooting menu, set REMOTE_ACCEPT_NEW_HOST_KEY to true "
                        "in Variable Settings. Retry to save the key, then return the "
                        "setting to false."
                    )

            client.set_missing_host_key_policy(ExplainUnknownHost())
        try:
            client.connect(
                hostname=host,
                port=port,
                username=self._remote_username,
                password=self._remote_password,
                allow_agent=False,
                look_for_keys=False,
                timeout=15,
                banner_timeout=15,
                auth_timeout=15,
            )
        except Exception:
            client.close()
            raise
        return client, host

    # Run every diagnostic even if an earlier check fails.
    def _run_diagnostics(
        self,
        parameters: dict[str, Any],
        commands: list[tuple[str, list[str]]],
        *,
        use_sudo: bool = False,
        timeout: int = 180,
        fail_on_error: bool = False,
    ) -> ExecutionResult:
        target = self._diagnostic_target(parameters)

        output: list[str] = []
        destination = "this computer" if target == "local" else str(parameters.get("host", ""))
        heading = f"Diagnostic target: {destination} ({target})"
        if self.output_callback:
            self._emit(heading + "\n")
        else:
            output.append(heading)
        failures = 0
        if target == "local":
            for label, command in commands:
                if self.cancel_requested.is_set():
                    return ExecutionResult(output + ["Action cancelled."], 130)
                actual = command
                input_text = None
                if use_sudo and not self._is_root():
                    if self._local_sudo_password:
                        actual = ["sudo", "-S", "-p", "", "--", *command]
                        input_text = self._local_sudo_password + "\n"
                    else:
                        actual = ["sudo", "-n", "--", *command]
                heading = f"\n=== {label} ===\n$ {self._display_command(actual)}"
                if self.output_callback:
                    self._emit(heading + "\n")
                else:
                    output.append(heading)
                try:
                    completed = self._run_process(actual, input_text=input_text, timeout=timeout)
                    if completed.stdout.strip():
                        output.append(completed.stdout.rstrip())
                    if completed.stderr.strip():
                        output.append("STDERR:\n" + completed.stderr.rstrip())
                    if completed.returncode == 130:
                        return ExecutionResult(output, 130)
                    if completed.returncode:
                        failures += 1
                        output.append(f"[Check exited with code {completed.returncode}]")
                except FileNotFoundError as exc:
                    failures += 1
                    output.append(f"ERROR: {exc}")
                except subprocess.TimeoutExpired:
                    failures += 1
                    output.append(f"ERROR: Check timed out after {timeout} seconds")
        else:
            client, host = self._open_remote_client(parameters)
            try:
                for label, command in commands:
                    if self.cancel_requested.is_set():
                        return ExecutionResult(output + ["Action cancelled before the next remote command."], 130)
                    remote_command = shlex.join(command)
                    if use_sudo:
                        remote_command = "sudo -S -p '' -- " + remote_command
                    heading = f"\n=== {label} ===\n$ [{host}] {remote_command}"
                    if self.output_callback:
                        self._emit(heading + "\n")
                    else:
                        output.append(heading)
                    try:
                        stdin, stdout, stderr = client.exec_command(
                            remote_command,
                            get_pty=use_sudo,
                            timeout=timeout,
                        )
                        if use_sudo:
                            stdin.write((self._remote_password or "") + "\n")
                            stdin.flush()
                        stdout_text = stdout.read().decode("utf-8", errors="replace").rstrip()
                        stderr_text = stderr.read().decode("utf-8", errors="replace").rstrip()
                        returncode = stdout.channel.recv_exit_status()
                        if stdout_text:
                            if self.output_callback:
                                self._emit(stdout_text + "\n")
                            else:
                                output.append(stdout_text)
                        if stderr_text:
                            if self.output_callback:
                                self._emit("STDERR:\n" + stderr_text + "\n")
                            else:
                                output.append("STDERR:\n" + stderr_text)
                        if returncode:
                            failures += 1
                            output.append(f"[Check exited with code {returncode}]")
                    except Exception as exc:
                        failures += 1
                        output.append(f"ERROR: {exc}")
            finally:
                client.close()

        if self.cancel_requested.is_set():
            return ExecutionResult(output + ["Cancellation requested; the current command has finished."], 130)
        if failures:
            output.append(
                f"\nCompleted with {failures} failed check(s); remaining diagnostics still ran."
            )
        else:
            output.append("\nAll diagnostic commands completed successfully.")
        return ExecutionResult(output, 1 if failures and fail_on_error else 0)

    # Build and run the selected Docker inspection or restart operation.
    def _troubleshoot_docker(self, parameters: dict[str, Any]) -> ExecutionResult:
        mode = str(parameters.get("mode", "engine")).strip().casefold()
        lines = self._diagnostic_line_count(parameters.get("log_lines", 200))
        commands: list[tuple[str, list[str]]]

        if mode == "engine":
            commands = [
                ("Docker version", ["docker", "version"]),
                ("Docker daemon information", ["docker", "info"]),
                ("Docker disk usage", ["docker", "system", "df", "-v"]),
            ]
        elif mode == "images":
            commands = [
                ("Docker image inventory", ["docker", "image", "ls", "--digests", "--no-trunc"]),
                ("Dangling images", ["docker", "image", "ls", "--filter", "dangling=true"]),
            ]
            selected = str(parameters.get("image", "")).strip()
            if selected:
                image = self._safe_docker_reference(selected, "DOCKER_IMAGE")
                commands.extend([
                    (f"Inspect image {image}", ["docker", "image", "inspect", "--format",
                        "ID={{.Id}} Created={{.Created}} OS={{.Os}} Architecture={{.Architecture}} Size={{.Size}}", image]),
                    (f"Image history {image}", ["docker", "history", "--no-trunc", image]),
                ])
        elif mode == "containers":
            commands = [
                (
                    "All containers",
                    [
                        "docker", "ps", "-a", "--no-trunc", "--format",
                        "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}",
                    ],
                ),
                ("Recent Docker events", ["docker", "events", "--since", "30m", "--until", "0s"]),
            ]
        elif mode in {"containers_stop_all", "containers_remove_all"}:
            # Enumerate on the selected host; an empty list is a successful no-op.
            remove = mode == "containers_remove_all"
            listing = "docker container ls --all --quiet" if remove else "docker container ls --quiet"
            operation = "docker container rm --force" if remove else "docker container stop"
            script = (
                f'ids=$({listing}) || exit $?\n'
                'if [ -z "$ids" ]; then echo "No matching containers."; exit 0; fi\n'
                'status=0\n'
                f'for id in $ids; do {operation} "$id" || status=1; done\n'
                'exit "$status"'
            )
            commands = [("Remove all containers" if remove else "Stop all running containers",
                         ["sh", "-c", script])]
        elif mode == "container_logs":
            container = self._safe_docker_reference(
                parameters.get("container", ""), "DOCKER_CONTAINER"
            )
            commands = [
                (f"Inspect container {container} (state, image, ports, mounts)", ["docker", "container", "inspect", "--format",
                    "State={{json .State}} Image={{json .Config.Image}} Ports={{json .HostConfig.PortBindings}} Mounts={{json .Mounts}}", container]),
                (f"Logs for {container}", ["docker", "logs", "--tail", str(lines), "--timestamps", container]),
            ]
        elif mode == "container_remove":
            container = self._safe_docker_reference(
                parameters.get("container", ""), "DOCKER_CONTAINER"
            )
            commands = [(f"Remove container {container}",
                         ["docker", "container", "rm", "--force", container])]
        elif mode == "container_restart":
            container = self._safe_docker_reference(
                parameters.get("container", ""), "DOCKER_CONTAINER"
            )
            commands = [
                (f"Restart container {container}", ["docker", "container", "restart", container]),
                (
                    f"Status for {container}",
                    [
                        "docker", "container", "inspect", "--format",
                        "{{.Name}}: {{.State.Status}} (started {{.State.StartedAt}})",
                        container,
                    ],
                ),
            ]
        else:
            raise ValueError(f"Unsupported Docker troubleshooting mode: {mode!r}")

        return self._run_diagnostics(
            parameters,
            commands,
            use_sudo=self._as_bool(parameters.get("use_sudo", False), "DOCKER_USE_SUDO"),
            fail_on_error=mode in {"container_remove", "container_restart", "containers_stop_all", "containers_remove_all"},
        )

    # Build and run the selected Security Onion diagnostic or reset operation.
    def _troubleshoot_security_onion(self, parameters: dict[str, Any]) -> ExecutionResult:
        mode = str(parameters.get("mode", "status")).strip().casefold()
        lines = self._diagnostic_line_count(parameters.get("log_lines", 200))

        if mode == "status":
            commands = [
                ("Security Onion service status", ["so-status"]),
                (
                    "Security Onion containers",
                    [
                        "docker", "ps", "-a", "--no-trunc", "--format",
                        "table {{.Names}}\t{{.Image}}\t{{.Status}}",
                    ],
                ),
            ]
        elif mode == "health":
            commands = [
                ("Uptime and load", ["uptime"]),
                ("Memory usage", ["free", "-h"]),
                ("Filesystem usage", ["df", "-h"]),
                ("Docker service", ["systemctl", "status", "docker", "--no-pager"]),
                ("Failed system services", ["systemctl", "--failed", "--no-pager"]),
            ]
        elif mode == "logs":
            commands = [
                (
                    "Docker journal",
                    ["journalctl", "-u", "docker", "--no-pager", "-n", str(lines)],
                ),
                (
                    "Salt minion journal",
                    ["journalctl", "-u", "salt-minion", "--no-pager", "-n", str(lines)],
                ),
                ("Suricata log", ["tail", "-n", str(lines), "/opt/so/log/suricata/suricata.log"]),
                ("Kibana log", ["tail", "-n", str(lines), "/opt/so/log/kibana/kibana.log"]),
            ]
        elif mode == "service_logs":
            service = self._safe_docker_reference(
                parameters.get("service", ""), "SECURITY_ONION_SERVICE"
            )
            if not service.startswith("so-"):
                raise ValueError("SECURITY_ONION_SERVICE must begin with 'so-'")
            commands = [
                (f"Inspect {service}", ["docker", "container", "inspect", "--format", "{{json .State}}", service]),
                (f"Docker logs for {service}", ["docker", "logs", "--tail", str(lines), "--timestamps", service]),
            ]
        elif mode == "checkin":
            commands = [("Security Onion full Salt check-in", ["so-checkin"])]
        elif mode == "clear":
            commands = [
                (
                    "Permanently clear all Security Onion Elasticsearch documents and indices",
                    ["so-elastic-clear"],
                )
            ]
        else:
            raise ValueError(f"Unsupported Security Onion troubleshooting mode: {mode!r}")

        return self._run_diagnostics(
            parameters,
            commands,
            use_sudo=True,
            timeout=900,
            fail_on_error=mode == "clear",
        )
