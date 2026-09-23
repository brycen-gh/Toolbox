"""Local and remote Docker and Security Onion diagnostics."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any

try:
    import paramiko
except ImportError:
    paramiko = None

from .result import ExecutionResult


class TroubleshootingActions:
    """Local and remote Docker and Security Onion diagnostics."""

    @staticmethod
    def _diagnostic_line_count(value: Any) -> int:
        try:
            lines = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("LOG_LINES must be an integer") from exc
        if not 10 <= lines <= 5000:
            raise ValueError("LOG_LINES must be between 10 and 5000")
        return lines

    @staticmethod
    def _safe_docker_reference(value: Any, field_name: str) -> str:
        reference = str(value).strip()
        if not reference or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]*", reference):
            raise ValueError(f"{field_name} contains an invalid Docker name or reference")
        return reference

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

        known_hosts = Path.home() / ".ssh" / "known_hosts"
        known_hosts.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        known_hosts.touch(mode=0o600, exist_ok=True)
        os.chmod(known_hosts.parent, 0o700)
        os.chmod(known_hosts, 0o600)

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.load_host_keys(str(known_hosts))
        if self._as_bool(parameters.get("accept_new_host_key", False), "accept_new_host_key"):
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
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
        return client, host

    def _run_diagnostics(
        self,
        parameters: dict[str, Any],
        commands: list[tuple[str, list[str]]],
        *,
        use_sudo: bool = False,
        timeout: int = 180,
        fail_on_error: bool = False,
    ) -> ExecutionResult:
        """Run every diagnostic even if an earlier check fails."""
        target = str(parameters.get("target", "local")).strip().casefold()
        if target not in {"local", "remote"}:
            raise ValueError("TARGET_MODE must be either local or remote")

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
        elif mode == "container_logs":
            container = self._safe_docker_reference(
                parameters.get("container", ""), "DOCKER_CONTAINER"
            )
            commands = [
                (f"Inspect container {container} (state, image, ports, mounts)", ["docker", "container", "inspect", "--format",
                    "State={{json .State}} Image={{json .Config.Image}} Ports={{json .HostConfig.PortBindings}} Mounts={{json .Mounts}}", container]),
                (f"Logs for {container}", ["docker", "logs", "--tail", str(lines), "--timestamps", container]),
            ]
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
            fail_on_error=mode == "container_restart",
        )

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
