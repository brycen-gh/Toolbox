"""Deployment, portable image archives, and container backup/restore actions."""
from __future__ import annotations

from datetime import datetime
import json
import time
import uuid
from .settings import persistent_secret
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any

from .result import ExecutionResult


class DeploymentActions:
    """Deployment, portable image archives, and container backup/restore actions."""

    def _system_info(self, _parameters: dict[str, Any]) -> ExecutionResult:
        distro = self._read_os_release()
        lines = [
            f"Operating system: {distro.get('PRETTY_NAME', 'Unknown Linux')}",
            f"Docker CLI: {shutil.which('docker') or 'not installed'}",
            f"Current directory: {self.base_dir}",
        ]
        return ExecutionResult(lines)

    def _docker_status(self, _parameters: dict[str, Any]) -> ExecutionResult:
        return self._run_steps([
            ["docker", "version", "--format", "Docker {{.Server.Version}}"],
            ["docker", "ps", "--format", "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"],
        ])

    def _install_docker(self, _parameters: dict[str, Any]) -> ExecutionResult:
        distro = self._read_os_release()
        distro_id = distro.get("ID", "").casefold()
        distro_like = distro.get("ID_LIKE", "").casefold()
        sudo = self._sudo_prefix()

        if shutil.which("docker"):
            return ExecutionResult(["Docker is already installed."])

        if distro_id in {"rocky", "rhel", "centos", "almalinux", "fedora"} or any(
            family in distro_like for family in ("rhel", "fedora")
        ):
            commands = [
                sudo + ["dnf", "install", "-y", "dnf-plugins-core"],
                sudo + [
                    "dnf", "config-manager", "--add-repo",
                    "https://download.docker.com/linux/centos/docker-ce.repo",
                ],
                sudo + [
                    "dnf", "install", "-y", "docker-ce", "docker-ce-cli",
                    "containerd.io", "docker-buildx-plugin", "docker-compose-plugin",
                ],
                sudo + ["systemctl", "enable", "--now", "docker"],
            ]
        elif distro_id in {"ubuntu", "debian", "linuxmint"} or "debian" in distro_like:
            commands = [
                sudo + ["apt-get", "update"],
                sudo + ["apt-get", "install", "-y", "docker.io", "docker-compose-plugin"],
                sudo + ["systemctl", "enable", "--now", "docker"],
            ]
        else:
            return ExecutionResult(
                [f"Unsupported distribution: {distro.get('PRETTY_NAME', distro_id or 'unknown')}"],
                2,
            )
        return self._run_steps(commands)

    def _pull_images(self, parameters: dict[str, Any]) -> ExecutionResult:
        images = parameters.get("images", [])
        if not isinstance(images, list) or not images:
            raise ValueError("pull_images requires a non-empty 'images' list")

        archive_dir = self._project_directory(
            parameters.get("directory", "./repos/containers"),
            "image archive directory",
        )
        attempts = int(parameters.get("pull_attempts", 3))
        if attempts < 1:
            raise ValueError("pull_attempts must be at least 1")

        archive_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix=".images-", dir=archive_dir))
        output: list[str] = []
        archive_names: list[str] = []
        try:
            for raw_image in images:
                image = str(raw_image).strip()
                if not image:
                    raise ValueError("Image names cannot be empty")

                pull_result = ExecutionResult(returncode=1)
                for attempt in range(1, attempts + 1):
                    pull_result = self._run_steps([["docker", "pull", image]])
                    output.extend(pull_result.output)
                    if pull_result.returncode == 130:
                        return ExecutionResult(output, 130)
                    if pull_result.returncode == 0:
                        break
                    if attempt < attempts:
                        delay = min(attempt * 2, 6)
                        output.append(
                            f"Pull attempt {attempt} failed; retrying in {delay} seconds."
                        )
                        if self.cancel_requested.wait(delay):
                            return ExecutionResult(output + ["Action cancelled."], 130)
                if pull_result.returncode:
                    return ExecutionResult(output, pull_result.returncode)

                archive_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", image).strip("_") + ".tar"
                archive_names.append(archive_name)
                save_result = self._run_steps([
                    ["docker", "image", "save", "-o", str(staging_dir / archive_name), image]
                ])
                output.extend(save_result.output)
                if save_result.returncode:
                    return ExecutionResult(output, save_result.returncode)

            expected = set(archive_names)
            for old_archive in archive_dir.glob("*.tar"):
                if old_archive.name not in expected:
                    old_archive.unlink()
            for archive_name in archive_names:
                os.replace(staging_dir / archive_name, archive_dir / archive_name)

            manifest_temp = archive_dir / "images.txt.new"
            manifest_temp.write_text(
                "".join(f"{image}\n" for image in images),
                encoding="utf-8",
            )
            os.replace(manifest_temp, archive_dir / "images.txt")
            output.append(f"Portable image archives saved in: {archive_dir}")
            return ExecutionResult(output, 0)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _load_images(self, parameters: dict[str, Any]) -> ExecutionResult:
        archive_dir = self._project_directory(
            parameters.get("directory", "./repos/containers"),
            "image archive directory",
        )
        archives = sorted(archive_dir.glob("*.tar")) if archive_dir.is_dir() else []
        if not archives:
            raise ValueError(f"No portable Docker image archives found in {archive_dir}")
        return self._run_steps([
            ["docker", "image", "load", "-i", str(archive)]
            for archive in archives
        ])

    def _local_data_directory(self, value: Any) -> Path:
        path = Path(str(value)).expanduser()
        resolved = path.resolve() if path.is_absolute() else (self.base_dir / path).resolve()
        protected = {Path("/").resolve(), Path.home().resolve(), self.base_dir}
        if resolved in protected:
            raise ValueError(f"Unsafe container data directory: {resolved}")
        return resolved

    @staticmethod
    def _container_names(parameters: dict[str, Any]) -> list[str]:
        names = []
        for value in parameters.get("containers", []):
            name = str(value).strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
                raise ValueError(f"Invalid managed container name: {name!r}")
            names.append(name)
        return names

    @staticmethod
    def _running_containers(names: list[str]) -> list[str]:
        if not names:
            return []
        if not shutil.which("docker"):
            raise RuntimeError("Cannot verify container state: Docker is not installed")
        running = []
        for name in names:
            result = subprocess.run(
                ["docker", "container", "inspect", "--format", "{{.State.Running}}", name],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if result.returncode:
                raise RuntimeError(f"Cannot inspect container {name!r}: {result.stderr.strip()}")
            state = result.stdout.strip().casefold()
            if state not in {"true", "false"}:
                raise RuntimeError(f"Unexpected running state for container {name!r}: {state!r}")
            if state == "true":
                running.append(name)
        return running

    def _with_stopped_containers(self, running, operation):
        """Always attempt recovery for every container we attempted to stop."""
        output = []
        stopped = []
        result = ExecutionResult(returncode=1)
        try:
            for name in running:
                if self.cancel_requested.is_set():
                    result = ExecutionResult(["Action cancelled."], 130)
                    break
                # A failed stop can still have stopped the container. Recover it too.
                stopped.append(name)
                self._protect_cleanup = True
                try:
                    result = self._run_steps([["docker", "stop", name]])
                finally:
                    self._protect_cleanup = False
                output.extend(result.output)
                if result.returncode:
                    break
            else:
                result = operation()
                output.extend(result.output)
        except Exception as exc:
            result = ExecutionResult(returncode=1)
            output.append(f"ERROR: {exc}")
        finally:
            self._protect_cleanup = True
            try:
                for name in stopped:
                    try:
                        restarted = self._run_steps([["docker", "start", name]])
                        output.extend(restarted.output)
                        if restarted.returncode:
                            output.append(f"ERROR: Could not restart {name!r}; manual recovery is required.")
                            result.returncode = result.returncode or restarted.returncode
                    except Exception as exc:
                        output.append(f"ERROR: Could not restart {name!r}: {exc}")
                        result.returncode = result.returncode or 1
            finally:
                self._protect_cleanup = False
        if result.returncode == 130 and "Action cancelled." not in output:
            output.append("Action cancelled.")
        return ExecutionResult(output, result.returncode)

    @staticmethod
    def _validate_backup_archive(archive: Path) -> None:
        with tarfile.open(archive, "r:*") as stream:
            for member in stream.getmembers():
                member_path = PurePosixPath(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError(f"Unsafe path in backup archive: {member.name!r}")
                if member.isdev():
                    raise ValueError(f"Device entry is not allowed in backup: {member.name!r}")
                if member.issym() or member.islnk():
                    target = PurePosixPath(member.linkname)
                    if target.is_absolute() or ".." in target.parts:
                        raise ValueError(
                            f"Unsafe link in backup archive: {member.name!r}"
                        )

    def _backup_container_data(self, parameters: dict[str, Any]) -> ExecutionResult:
        data_dir = self._local_data_directory(parameters.get("data_directory", ""))
        backup_dir = self._project_directory(
            parameters.get("backup_directory", "./backups"),
            "backup directory",
        )
        requested_name = str(parameters.get("archive_name", "")).strip()
        if requested_name:
            archive_name = Path(requested_name).name
            if archive_name != requested_name:
                raise ValueError("archive_name must be a filename, not a path")
        else:
            prefix = re.sub(
                r"[^A-Za-z0-9_.-]+",
                "_",
                str(parameters.get("archive_prefix", "container-data")),
            ).strip("_.-") or "container-data"
            archive_name = f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.tar.gz"
        if not data_dir.is_dir():
            return ExecutionResult([f"No local container data found at {data_dir}"], 2)

        backup_dir.mkdir(parents=True, exist_ok=True)
        archive = backup_dir / archive_name
        temporary = backup_dir / f".{archive_name}.new"
        temporary.unlink(missing_ok=True)
        running = self._running_containers(self._container_names(parameters))

        def create_backup():
            backup_result = self._run_steps([
                self._sudo_prefix() + [
                    "tar", "--create", "--gzip", "--file", str(temporary),
                    "--directory", str(data_dir), ".",
                ]
            ])
            if backup_result.returncode == 0:
                os.replace(temporary, archive)
                backup_result.output.append(f"Container data backup saved to: {archive}")
            return backup_result

        try:
            return self._with_stopped_containers(running, create_backup)
        finally:
            temporary.unlink(missing_ok=True)

    def _load_container_data(self, parameters: dict[str, Any]) -> ExecutionResult:
        data_dir = self._local_data_directory(parameters.get("data_directory", ""))
        backup_dir = self._project_directory(
            parameters.get("backup_directory", "./backups"),
            "backup directory",
        )
        archive_name = Path(str(parameters.get("archive_name", "container-data.tar.gz"))).name
        if archive_name != str(parameters.get("archive_name", archive_name)):
            raise ValueError("archive_name must be a filename, not a path")
        archive = backup_dir / archive_name
        if not archive.is_file():
            return ExecutionResult([f"Container data backup not found: {archive}"], 2)
        self._validate_backup_archive(archive)
        data_dir.mkdir(parents=True, exist_ok=True)

        running = self._running_containers(self._container_names(parameters))

        def restore_backup():
            load_result = self._run_steps([
                self._sudo_prefix() + [
                    "tar", "--extract", "--gzip", "--file", str(archive),
                    "--directory", str(data_dir),
                ]
            ])
            if load_result.returncode == 0:
                load_result.output.append(f"Container data loaded into: {data_dir}")
            return load_result

        return self._with_stopped_containers(running, restore_backup)

    def _volume_argument(self, value: Any) -> str:
        """Turn project-relative bind sources into absolute Docker arguments."""
        volume = str(value)
        source, separator, remainder = volume.partition(":")
        if not source.startswith(("./", "~/")):
            return volume
        if not separator or not remainder:
            raise ValueError(f"Relative volume must include a container path: {volume!r}")

        if source.startswith("~/"):
            host_path = Path(source).expanduser().resolve()
        else:
            host_path = (self.base_dir / source).resolve()
            try:
                host_path.relative_to(self.base_dir)
            except ValueError as exc:
                raise ValueError(
                    f"Relative volume escapes the project directory: {volume!r}"
                ) from exc
        host_path.mkdir(parents=True, exist_ok=True)
        return f"{host_path}:{remainder}"

    def _docker_read(self, arguments):
        result = subprocess.run(["docker", *arguments], capture_output=True, text=True,
                                check=False, timeout=30)
        if result.returncode:
            raise RuntimeError(self._redact(result.stderr.strip() or "Docker query failed"))
        return result.stdout

    def _wait_for_container(self, name, timeout=180):
        """Require healthy status, or several consecutive running observations."""
        deadline = time.monotonic() + timeout
        running_checks = 0
        while time.monotonic() < deadline:
            if self.cancel_requested.is_set():
                raise RuntimeError("Deployment cancelled")
            state = json.loads(self._docker_read([
                "container", "inspect", "--format", "{{json .State}}", name
            ]))
            if not state.get("Running"):
                raise RuntimeError(f"Replacement container {name!r} is not running")
            health = state.get("Health", {}).get("Status")
            if health == "unhealthy":
                raise RuntimeError(f"Replacement container {name!r} is unhealthy")
            running_checks += 1
            if health == "healthy" or (health is None and running_checks >= 3):
                return
            self.cancel_requested.wait(1)
        raise RuntimeError(f"Replacement container did not become healthy within {timeout} seconds")

    def _run_container(self, parameters: dict[str, Any]) -> ExecutionResult:
        name = str(parameters.get("name", "")).strip()
        image = str(parameters.get("image", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or not image or image.startswith("-"):
            raise ValueError("run_container requires a valid container name and image")
        names = self._docker_read(["container", "ls", "-a", "--format", "{{.Names}}"] ).splitlines()
        exists = name in names
        if exists and not self._as_bool(parameters.get("recreate", False), "recreate"):
            return ExecutionResult([f"Container {name!r} exists. Enable Recreate existing container to replace it."], 1)
        old = json.loads(self._docker_read(["container", "inspect", name]))[0] if exists else None
        environment = dict(parameters.get("environment", {}))
        old_environment = dict(entry.split("=", 1) for entry in (old or {}).get("Config", {}).get("Env", []) if "=" in entry)
        for key, value in environment.items():
            if "${GENERATED_SECRET}" in str(value):
                secret = persistent_secret(self.base_dir, name, key, old_environment.get(key))
                environment[key] = str(value).replace("${GENERATED_SECRET}", secret)
            if re.search(r"SECRET|PASSWORD|TOKEN|KEY", key, re.I):
                self._sensitive_values.add(str(environment[key]))
        suffix = uuid.uuid4().hex[:12]
        candidate = f"{name}-candidate-{suffix}"
        previous = f"{name}-previous-{suffix}"
        command = ["docker", "create", "--name", candidate,
                   "--restart", str(parameters.get("restart", "unless-stopped"))]
        for port in parameters.get("ports", []):
            command += ["-p", str(port)]
        for volume in parameters.get("volumes", []):
            command += ["-v", self._volume_argument(volume)]
        for key, value in environment.items():
            command += ["-e", f"{key}={value}"]
        command += [str(value) for value in parameters.get("extra_args", [])]
        command.append(image)
        command += [str(value) for value in parameters.get("command", [])]
        output = []
        candidate_attempted = False
        old_touched = False
        old_renamed = False
        active_candidate = candidate
        success = False
        code = 1

        def step(command):
            protected = self._protect_cleanup
            if self.cancel_requested.is_set() and not protected:
                raise RuntimeError("Deployment cancelled")
            # Complete short identity/state transitions before honoring cancellation.
            if command[1] in {"stop", "rename"}:
                self._protect_cleanup = True
            try:
                result = self._run_steps([command])
            finally:
                self._protect_cleanup = protected
            output.extend(result.output)
            if result.returncode:
                raise RuntimeError(f"Docker operation failed with code {result.returncode}")

        try:
            # Creation validates the image and Docker configuration before any stop.
            candidate_attempted = True
            step(command)
            if exists:
                old_touched = True
                step(["docker", "stop", name])
                step(["docker", "rename", name, previous])
                old_renamed = True
            step(["docker", "rename", candidate, name])
            active_candidate = name
            step(["docker", "start", name])
            self._wait_for_container(name)
            success = True
            code = 0
            output.append(f"Container {name!r} passed startup checks.")
        except Exception as exc:
            code = 130 if self.cancel_requested.is_set() else 1
            output.append(f"ERROR: {self._redact(str(exc))}")
        finally:
            self._protect_cleanup = True
            try:
                if success:
                    if old_renamed:
                        try:
                            step(["docker", "rm", previous])
                        except Exception as exc:
                            output.append(f"Previous container retained as {previous!r}: {exc}")
                else:
                    if candidate_attempted:
                        try:
                            step(["docker", "rm", "-f", active_candidate])
                        except Exception as exc:
                            output.append(f"Candidate cleanup requires attention: {exc}")
                    restored_name = name
                    if old_renamed:
                        try:
                            step(["docker", "rename", previous, name])
                        except Exception as exc:
                            restored_name = previous
                            output.append(f"Previous container remains named {previous!r}: {exc}")
                    if old_touched and old.get("State", {}).get("Running"):
                        try:
                            step(["docker", "start", restored_name])
                            output.append(f"Previous container restarted as {restored_name!r}.")
                        except Exception as exc:
                            output.append(f"MANUAL RECOVERY REQUIRED for {restored_name!r}: {exc}")
            finally:
                self._protect_cleanup = False
        return ExecutionResult(output, code)
