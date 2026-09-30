"""Shared dispatch, credentials, variable expansion, and command execution."""
from __future__ import annotations

import os
import queue
import re
import shlex
import signal
import subprocess
import threading
import time
from pathlib import Path
from string import Template
from typing import Any, Callable
from .deployment import DeploymentActions
from .training import TrainingActions
from .capture import CaptureActions
from .troubleshooting import TroubleshootingActions
from .docker_engines.zulip import ZulipActions
from .docker_engines.registry import deployment_actions, deployment_parameters

from .result import ExecutionResult
from .settings import shared_container_variables, stored_secret_values


class ExecutionEngine(DeploymentActions, TrainingActions, TroubleshootingActions, ZulipActions, CaptureActions):
    """Shared dispatch, credentials, variable expansion, and command execution."""

    # Initialize command execution state and register supported actions.
    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir or Path.cwd()).resolve()
        self._remote_username: str | None = None
        self._remote_password: str | None = None
        self._local_sudo_password: str | None = None
        self.cancel_requested = threading.Event()
        self.output_callback: Callable[[str], None] | None = None
        self._protect_cleanup = False
        self._credential_target = None
        self._sensitive_values = set()
        self.actions: dict[str, Callable[[dict[str, Any]], ExecutionResult]] = {
            "system_info": self._system_info,
            "docker_status": self._docker_status,
            "install_docker": self._install_docker,
            "pull_images": self._pull_images,
            "load_images": self._load_images,
            "backup_container_data": self._backup_container_data,
            "load_container_data": self._load_container_data,
            "replay_pcap": self._replay_pcap,
            "capture_packets": self._capture_packets,
            "test_action": self._test_action,
            "local_host_training": self._local_host_training,
            "run_container": self._run_container,
            "zulip_organization_link": self._zulip_organization_link,
            "restore_zulip": self._restore_zulip,
            "troubleshoot_docker": self._troubleshoot_docker,
            "troubleshoot_security_onion": self._troubleshoot_security_onion,
        }
        self.actions.update(deployment_actions(self))

    # Keep decrypted SSH credentials in memory for this application session.
    def set_remote_credentials(self, username: str, password: str, target=None) -> None:
        if not username.strip() or "\n" in username or "\n" in password:
            raise ValueError("Remote credentials cannot be empty or contain newlines")
        self._remote_username = username.strip()
        self._remote_password = password
        self._credential_target = target

    # Discard unlocked credentials when the selected remote target changes.
    def bind_remote_target(self, target):
        if self._credential_target != target:
            self._remote_username = None
            self._remote_password = None
            self._credential_target = target

    # Backward-compatible alias that locks every session credential.
    def clear_remote_credentials(self) -> None:
        self.clear_session_credentials()

    # Keep the local sudo password in memory for this application session.
    def set_local_sudo_password(self, password: str) -> None:
        if not password or "\n" in password:
            raise ValueError("The local sudo password cannot be empty or contain newlines")
        self._local_sudo_password = password

    # Forget both local sudo and remote SSH session credentials.
    def clear_session_credentials(self) -> None:
        self._remote_username = None
        self._remote_password = None
        self._local_sudo_password = None
        self._credential_target = None

    # Report whether SSH credentials are unlocked in memory.
    def has_remote_credentials(self) -> bool:
        return bool(self._remote_username and self._remote_password)

    # Report whether a local sudo password is cached for this session.
    def has_local_sudo_password(self) -> bool:
        return bool(self._local_sudo_password)

    # Resolve action variables, dispatch an allowed handler, and redact its output.
    def execute(
        self,
        action_id: str,
        *,
        variables: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        handler = self.actions.get(action_id)
        if handler is None:
            available = ", ".join(sorted(self.actions))
            raise ValueError(f"Unknown action_id {action_id!r}. Available actions: {available}")

        context = dict(variables or {})
        if action_id == "troubleshoot_docker":
            context.update(shared_container_variables(self.base_dir))
        context = self._expand_context(context)
        resolved = self._resolve(deployment_parameters(action_id, parameters), context)
        if not isinstance(resolved, dict):
            raise TypeError("Action parameters must be a mapping")
        self._sensitive_values = stored_secret_values(self.base_dir)
        result = handler(resolved)
        result.output = [self._redact(text) for text in result.output]
        if self.output_callback:
            for text in result.output:
                self._emit(text + "\n")
            result.output = []
        return result

    # Convert YAML values to strings suitable for variable substitution.
    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return ""
        return str(value)

    # Resolve variables that reference other variables, including generated secrets.
    def _expand_context(self, context: dict[str, Any]) -> dict[str, str]:
        expanded = {key: self._stringify(value) for key, value in context.items()}
        for _ in range(len(expanded) + 1):
            updated = {
                key: Template(value).safe_substitute(expanded)
                for key, value in expanded.items()
            }
            if updated == expanded:
                break
            expanded = updated
        return expanded

    # Expand variable references recursively in action parameter structures.
    def _resolve(self, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return Template(value).safe_substitute(context)
        if isinstance(value, list):
            return [self._resolve(item, context) for item in value]
        if isinstance(value, dict):
            return {key: self._resolve(item, context) for key, item in value.items()}
        return value

    # Parse supported boolean spellings and reject ambiguous values.
    @staticmethod
    def _as_bool(value: Any, field_name: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        normalized = str(value).strip().casefold()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0", ""}:
            return False
        raise ValueError(f"{field_name} must be true or false, not {value!r}")

    # Read Linux distribution identifiers from /etc/os-release.
    @staticmethod
    def _read_os_release() -> dict[str, str]:
        values: dict[str, str] = {}
        path = Path("/etc/os-release")
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    values[key] = value.strip().strip('"')
        return values

    # Run commands sequentially and stop on failure or cancellation.
    def _run_steps(self, commands: list[list[str]]) -> ExecutionResult:
        output: list[str] = []
        for command in commands:
            if self.cancel_requested.is_set() and not self._protect_cleanup:
                return ExecutionResult(output + ["Action cancelled."], 130)
            message = "$ " + self._display_command(command)
            if self.output_callback:
                self._emit(message + "\n")
            else:
                output.append(message)
            try:
                actual = command
                input_text = None
                if command[0] == "sudo":
                    if self._local_sudo_password:
                        actual = ["sudo", "-S", "-p", "", "--", *command[1:]]
                        input_text = self._local_sudo_password + "\n"
                    else:
                        actual = ["sudo", "-n", "--", *command[1:]]
                completed = self._run_process(actual, input_text=input_text)
            except FileNotFoundError as exc:
                output.append(f"ERROR: {exc}")
                return ExecutionResult(output, 127)

            if completed.stdout.strip():
                output.append(completed.stdout.rstrip())
            if completed.stderr.strip():
                output.append("STDERR:\n" + completed.stderr.rstrip())
            if completed.returncode:
                return ExecutionResult(output, completed.returncode)
        return ExecutionResult(output, 0)

    # Forward redacted text to the active output callback.
    def _emit(self, text: str) -> None:
        if self.output_callback:
            self.output_callback(self._redact(text))

    # Mask known secrets and session passwords in displayed text.
    def _redact(self, text):
        values = self._sensitive_values | {self._remote_password, self._local_sudo_password}
        for value in sorted((v for v in values if v), key=len, reverse=True):
            text = text.replace(value, "[REDACTED]")
        return text

    # Format a command for display while hiding environment secrets.
    def _display_command(self, command):
        visible = list(command)
        for index, value in enumerate(visible):
            if index and visible[index - 1] in {"-e", "--env"} and "=" in value:
                key, secret = value.split("=", 1)
                visible[index] = key + "=[REDACTED]"
                if re.search(r"SECRET|PASSWORD|TOKEN|KEY", key, re.I) and secret:
                    self._sensitive_values.add(secret)
        return self._redact(shlex.join(visible))

    # Stream local command output while allowing cancellation and timeouts.
    def _run_process(self, command, *, input_text=None, timeout=None):
        if self.cancel_requested.is_set() and not self._protect_cleanup:
            return subprocess.CompletedProcess(command, 130, "Action cancelled.\n", "")
        chunks = queue.Queue()
        output = []
        with subprocess.Popen(
            command, cwd=self.base_dir, stdin=subprocess.PIPE if input_text else None,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            errors="replace", start_new_session=(os.name == "posix"),
        ) as process:
            def read_output():
                try:
                    for line in process.stdout:
                        chunks.put(line)
                finally:
                    chunks.put(None)

            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            if input_text:
                try:
                    process.stdin.write(input_text)
                    process.stdin.flush()
                except BrokenPipeError:
                    pass
                finally:
                    process.stdin.close()
            started = time.monotonic()
            stopped_at = None
            reason = None
            eof = False
            while not eof or process.poll() is None:
                now = time.monotonic()
                cancelled = self.cancel_requested.is_set() and not self._protect_cleanup
                expired = timeout is not None and now - started >= timeout
                if stopped_at is None and (cancelled or expired):
                    reason = "Action cancelled." if cancelled else f"Command timed out after {timeout} seconds."
                    stopped_at = now
                    self._signal_process(process, signal.SIGTERM)
                elif stopped_at is not None and now - stopped_at >= 2:
                    self._signal_process(process, getattr(signal, "SIGKILL", signal.SIGTERM), force=True)
                try:
                    chunk = chunks.get(timeout=0.1)
                except queue.Empty:
                    continue
                if chunk is None:
                    eof = True
                else:
                    if not self.output_callback:
                        output.append(self._redact(chunk))
                    self._emit(chunk)
            reader.join()
            returncode = process.wait()
            if reason:
                if not self.output_callback:
                    output.append(reason + "\n")
                self._emit(reason + "\n")
                returncode = 130 if cancelled else 124
        return subprocess.CompletedProcess(command, returncode, "".join(output), "")

    # Signal a process or process group using the platform's available controls.
    @staticmethod
    def _signal_process(process, sig, force=False):
        try:
            if os.name == "posix":
                os.killpg(process.pid, sig)
            elif force:
                process.kill()
            else:
                process.terminate()
        except ProcessLookupError:
            pass

    # Return whether elevation is available on POSIX; Windows actions do not use sudo.
    @staticmethod
    def _is_root() -> bool:
        return os.name != "posix" or os.geteuid() == 0

    # Return the privilege-elevation prefix required by this account.
    @staticmethod
    def _sudo_prefix() -> list[str]:
        return [] if ExecutionEngine._is_root() else ["sudo"]

    # Display the parent section label and number without executing a script.
    def _test_action(self, parameters: dict[str, Any]) -> ExecutionResult:
        label = str(parameters.get("label", "")).strip()
        script_number = str(parameters.get("script_number", "")).strip()
        if not label or not script_number:
            raise ValueError("test_action requires label and script_number")
        return ExecutionResult([f"{label} {script_number}"])

    # Resolve a directory, rejecting traversal in relative paths but allowing absolute paths.
    def _project_directory(self, value: Any, field_name: str) -> Path:
        path = Path(str(value)).expanduser()
        resolved = path.resolve() if path.is_absolute() else (self.base_dir / path).resolve()
        if not path.is_absolute():
            try:
                resolved.relative_to(self.base_dir)
            except ValueError as exc:
                raise ValueError(f"{field_name} escapes the project directory: {value!r}") from exc
        return resolved
