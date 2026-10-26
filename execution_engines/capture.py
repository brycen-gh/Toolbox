"""Local Linux packet capture with user-owned output files."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from .result import ExecutionResult


# List adapters visible to Linux without changing their configuration.
def capture_interfaces():
    if not sys.platform.startswith("linux"):
        raise ValueError("Capture currently requires Linux. WSL can only capture adapters visible inside WSL.")
    root = Path("/sys/class/net")
    return sorted(p.name for p in root.iterdir())


class CaptureActions:
    # Stream binary packets to an exclusively created file and stop gracefully.
    def _capture_packets(self, parameters):
        interface = str(parameters.get("interface", ""))
        if interface not in capture_interfaces():
            raise ValueError("Select an available network interface.")
        executable = shutil.which("tcpdump")
        if not executable:
            raise ValueError("tcpdump is missing. Rerun Linux run-once setup to install capture support.")
        destination = Path(str(parameters.get("output", ""))).expanduser()
        if not destination.is_absolute() or destination.suffix.lower() != ".pcap":
            raise ValueError("Choose an absolute output filename ending in .pcap.")
        if self.cancel_requested.is_set():
            return ExecutionResult(["Capture cancelled before starting."])
        command = [executable, "-i", interface, "-p", "-n", "-s", "0", "-U", "-w", "-"]
        password = None
        if not self._is_root():
            if self._local_sudo_password:
                command = ["sudo", "-S", "-p", "", "--", *command]
                password = (self._local_sudo_password + "\n").encode()
            else:
                command = ["sudo", "-n", "--", *command]
        # Exclusive creation prevents overwrites and following existing symlinks.
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as capture, tempfile.TemporaryFile() as diagnostics:
            with subprocess.Popen(command, stdin=subprocess.PIPE if password else subprocess.DEVNULL,
                                  stdout=capture, stderr=diagnostics, start_new_session=True) as process:
                if password:
                    try:
                        process.stdin.write(password)
                        process.stdin.flush()
                    except BrokenPipeError:
                        pass
                    finally:
                        process.stdin.close()
                self._emit(f"Starting capture on {interface}. Saving to {destination}\nUse Stop Capture to finish.\n")
                stopped_at = None
                forced = False
                try:
                    while process.poll() is None:
                        if self.cancel_requested.is_set() and stopped_at is None:
                            self._signal_process(process, signal.SIGTERM)
                            stopped_at = time.monotonic()
                        elif stopped_at is not None and time.monotonic() - stopped_at > 5:
                            self._signal_process(process, signal.SIGKILL, force=True)
                            forced = True
                        time.sleep(0.1)
                finally:
                    if process.poll() is None:
                        self._signal_process(process, signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            self._signal_process(process, signal.SIGKILL, force=True)
                            process.wait()
                code = process.wait()
            diagnostics.seek(0)
            details = diagnostics.read().decode(errors="replace").strip()
        size = destination.stat().st_size
        success = not forced and size >= 24 and (code == 0 or (stopped_at is not None and code in {-15, 143}))
        message = (f"Capture saved: {destination} ({size:,} bytes)." if success else
                   f"Capture failed or was interrupted; output may be incomplete: {destination} ({size:,} bytes).")
        return ExecutionResult([details, message], 0 if success else (code or 1))
