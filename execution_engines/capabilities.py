"""Fast, read-only host checks for portable Toolbox installations.

These checks locate executables; they never start a process, contact a Docker
daemon, install software, or request elevation. Individual actions still verify
their target, permissions, and service availability when they run.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
import platform
import shutil
import sys
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class Capability:
    key: str
    label: str
    available: bool
    description: str
    executable: str | None = None


def capability_snapshot() -> tuple[Capability, ...]:
    """Describe the current host without testing services or changing the host."""
    system = platform.system()
    windows = system == "Windows"
    linux = system == "Linux"
    in_wsl = linux and bool(os.environ.get("WSL_DISTRO_NAME"))
    rows = [
        Capability("windows", "Windows host", windows,
                   "Local host training runs on Windows."),
        Capability("linux", "Linux host", linux,
                   "Packet capture and replay use Linux network interfaces."),
    ]
    executables = (
        ("docker", "Docker CLI", "docker",
         "CLI detection only. Docker daemon access is checked when an action runs."),
        ("powershell", "Windows PowerShell", "powershell.exe",
         "Used for Windows host training and WSL forwarding."),
        ("wsl", "Windows Subsystem for Linux", "wsl.exe",
         "WSL forwarding uses an existing distribution with Windows interop."),
        ("tcpdump", "Packet capture", "tcpdump",
         "Captures packets on Linux; capture permissions are checked when run."),
        ("tcpreplay", "Packet replay", "tcpreplay",
         "Replays PCAPs through a Linux network interface."),
        ("bash", "Bash", "bash", "Available for shell-based companion tools."),
        ("sh", "POSIX shell", "sh", "Used by bulk Docker diagnostic actions."),
        ("tar", "Archive utility", "tar", "Used by container data backup and restore."),
        ("git", "Git", "git", "Updates a source checkout of Toolbox."),
    )
    for key, label, command, description in executables:
        executable = shutil.which(command)
        available = bool(executable) or (key == "wsl" and in_wsl)
        rows.append(Capability(key, label, available, description, executable))
    return tuple(rows)


_DOCKER_ACTIONS = frozenset({
    "deploy_nginx_proxy",
    "docker_status", "pull_images", "load_images", "run_container",
    "deploy_home", "deploy_open_project", "deploy_mattermost", "deploy_etherpad",
    "deploy_nextcloud", "deploy_guacamole", "deploy_moodle", "deploy_ctfd",
    "deploy_portainer", "deploy_zulip", "deploy_nginx", "backup_ctfd",
    "restore_ctfd", "restore_zulip", "zulip_create_organization", "zulip_organization_link",
})


def _is_remote(parameters: Mapping[str, Any]) -> bool:
    """Match the diagnostic engine's loopback and localhost target selection."""
    host = str(parameters.get("host", "")).strip().casefold()
    if not host or host.rstrip(".") == "localhost":
        return False
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True


def action_requirements(
    action_id: str,
    parameters: Mapping[str, Any] | None = None,
    snapshot: Iterable[Capability] | None = None,
) -> list[str]:
    """Explain known missing local prerequisites for resolved action parameters.

    Unknown and application-only actions remain available. Remote diagnostics
    run their commands over the bundled SSH library, so local host tools do not
    constrain those actions.
    """
    # The action explains how packaged releases are replaced. Let that message
    # reach the user even on hosts that do not have Git installed.
    if action_id == "update_tool" and getattr(sys, "frozen", False):
        return []
    parameters = parameters or {}
    available = {row.key for row in (capability_snapshot() if snapshot is None else snapshot)
                 if row.available}
    required: list[tuple[str, str]] = []
    if action_id in {"troubleshoot_docker", "troubleshoot_security_onion"}:
        if _is_remote(parameters):
            return []
        if action_id == "troubleshoot_docker":
            required.append(("docker", "Install Docker or select a remote diagnostic host."))
            if str(parameters.get("mode", "engine")).strip().casefold() in {
                "containers_stop_all", "containers_remove_all",
            }:
                required.append(("sh", "This bulk Docker action requires a POSIX shell (sh)."))
        else:
            required.append(("linux", "Local Security Onion diagnostics require a Linux host."))
            if str(parameters.get("mode", "status")).strip().casefold() in {"status", "service_logs"}:
                required.append(("docker", "Install Docker or select a remote diagnostic host."))
    elif action_id in _DOCKER_ACTIONS:
        required.append(("docker", "Install Docker on this computer to use this action."))
        if action_id in {"restore_ctfd", "restore_zulip"}:
            required.append(("tar", "Container data restore requires the tar archive utility."))
    elif action_id in {"backup_container_data", "load_container_data"}:
        required.append(("tar", "Container data backup and restore require the tar archive utility."))
        if parameters.get("containers"):
            required.append(("docker", "Docker is needed to check and pause the selected containers."))
    elif action_id == "install_docker":
        required.append(("linux", "Docker installation through Toolbox requires a supported Linux host."))
    elif action_id == "capture_packets":
        required.extend([
            ("linux", "Packet capture requires Linux; WSL exposes only its own interfaces."),
            ("tcpdump", "Install tcpdump on this computer to capture packets."),
        ])
    elif action_id == "replay_pcap":
        required.extend([
            ("linux", "Packet replay requires a Linux network interface."),
            ("tcpreplay", "Install tcpreplay on this computer to replay PCAPs."),
        ])
    elif action_id == "local_host_training":
        required.extend([
            ("windows", "Local host training must run on the Windows VM itself."),
            ("powershell", "Local host training requires Windows PowerShell 5.1 (powershell.exe)."),
        ])
    elif action_id == "wsl_forward":
        required.extend([
            ("wsl", "WSL forwarding requires an existing Windows Subsystem for Linux installation."),
            ("powershell", "WSL forwarding requires Windows PowerShell with Windows interop enabled."),
        ])
    elif action_id == "update_tool":
        required.append(("git", "Install Git to update a source checkout of Toolbox."))
    return [message for key, message in required if key not in available]
