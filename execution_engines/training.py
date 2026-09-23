"""PCAP training actions using the shared command runner."""
from __future__ import annotations

from pathlib import Path
import json
import os
import uuid
import re
import shutil
from typing import Any

from .result import ExecutionResult


class TrainingActions:
    """PCAP training actions using the shared command runner."""

    HOST_SCENARIOS = {
        "successful_login", "failed_login", "process_creation", "parent_child",
        "file_activity", "powershell_activity", "service_activity", "scheduled_task",
        "registry_activity", "account_activity", "process_chain",
    }

    def _local_host_training(self, parameters: dict[str, Any]) -> ExecutionResult:
        """Execute fixed Windows lab scenarios or inspect local event logs."""
        if os.name != "nt":
            return ExecutionResult([
                "Local Host Actions require the toolbox to run on the Windows VM itself. "
                "Linux/WSL does not target its Windows host automatically."
            ], 2)
        mode = str(parameters.get("mode", "readiness"))
        scenario = str(parameters.get("scenario", "process_creation"))
        if mode not in {"readiness", "run", "analyze", "results", "cleanup"}:
            raise ValueError("Unknown local host training mode")
        if scenario not in self.HOST_SCENARIOS:
            raise ValueError("Unknown host training scenario")
        root = Path(os.environ["LOCALAPPDATA"]) / "ToolboxTraining" / "Runs"
        run_id = str(parameters.get("run_id", "latest")).strip()
        if mode == "run":
            run_id = uuid.uuid4().hex
        elif mode != "readiness" and run_id == "latest":
            runs = []
            for path in root.glob("*/run.json"):
                if not re.fullmatch(r"[0-9a-f]{32}", path.parent.name):
                    continue
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                if data.get("Scenario") == scenario:
                    runs.append(path)
            if not runs:
                return ExecutionResult([f"No saved local run for {scenario}."], 2)
            run_id = max(runs, key=lambda path: path.stat().st_mtime_ns).parent.name
        if mode != "readiness" and not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise ValueError("Run ID must be 32 lowercase hexadecimal characters or latest")
        powershell = shutil.which("powershell.exe")
        if not powershell:
            return ExecutionResult(["Windows PowerShell 5.1 is required."], 127)
        script = self.base_dir / "scripts" / "windows" / "host_training.ps1"
        if not script.is_file():
            raise FileNotFoundError(script)
        command = [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                   str(script), "-Mode", mode, "-Scenario", scenario]
        if mode != "readiness":
            command += ["-RunId", run_id]
        # Mutating lab steps finish or fail before cancellation, so the journal
        # and cleanup instructions survive a cancelled UI operation.
        protected = self._protect_cleanup
        if mode in {"run", "cleanup"}:
            self._protect_cleanup = True
        try:
            return self._run_steps([command])
        finally:
            self._protect_cleanup = protected

    def _replay_pcap(self, parameters: dict[str, Any]) -> ExecutionResult:
        interface = str(parameters.get("interface", "")).strip()
        pcap_name = str(parameters.get("pcap_name", "")).strip()
        if not interface or not re.fullmatch(r"[A-Za-z0-9_.:-]+", interface):
            raise ValueError("replay_pcap requires a valid target interface name")
        if not pcap_name or Path(pcap_name).name != pcap_name:
            raise ValueError("replay_pcap requires a PCAP filename without directory traversal")

        interface_path = Path("/sys/class/net") / interface
        if not interface_path.exists():
            return ExecutionResult([
                f"Target interface {interface!r} was not found.",
                "Available interfaces: " + ", ".join(
                    sorted(path.name for path in Path("/sys/class/net").iterdir())
                ),
            ], 2)

        pcap_dir = self._project_directory(
            parameters.get("directory", "./repos/pcap"),
            "PCAP directory",
        )
        requested = Path(pcap_name)
        candidates = [pcap_dir / requested]
        if not requested.suffix:
            candidates.extend([
                pcap_dir / f"{pcap_name}.pcap",
                pcap_dir / f"{pcap_name}.pcapng",
            ])
        pcap_path = next((path for path in candidates if path.is_file()), None)
        if pcap_path is None:
            checked = ", ".join(path.name for path in candidates)
            return ExecutionResult([
                f"PCAP {pcap_name!r} was not found in {pcap_dir}.",
                f"Checked: {checked}",
            ], 2)

        if not shutil.which("tcpreplay"):
            return ExecutionResult([
                "tcpreplay is not installed.",
                "Run ./run-once/run-once again to install required training dependencies.",
            ], 127)

        return self._run_steps([
            self._sudo_prefix() + [
                "tcpreplay",
                f"--intf1={interface}",
                str(pcap_path),
            ]
        ])
