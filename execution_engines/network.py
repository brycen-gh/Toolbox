"""Choose a local address for sharing lab service links."""
import ipaddress
import os
import socket
import subprocess


def usable_address(value):
    try:
        address = ipaddress.ip_address(value.strip())
        return address.version == 4 and not (address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast)
    except ValueError:
        return False


def detect_host_address():
    # WSL's NAT address is usually not accessible from the LAN. Prefer the
    # Windows adapter with a default route when Windows interop is available.
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        try:
            result = subprocess.run([
                "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                "Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } | "
                "ForEach-Object { $_.IPv4Address.IPAddress }",
            ], capture_output=True, text=True, timeout=5)
            for line in result.stdout.splitlines():
                if usable_address(line):
                    return line.strip(), "Windows LAN adapter (WSL host)"
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            # UDP connect chooses a route without sending traffic.
            connection.connect(("192.0.2.1", 9))
            address = connection.getsockname()[0]
            if usable_address(address):
                return address, "Default-route adapter"
    except OSError:
        pass
    return None, "No usable IPv4 address found"
