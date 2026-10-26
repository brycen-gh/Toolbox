"""Locations that remain valid when Toolbox moves to another drive or machine."""
from __future__ import annotations

from pathlib import Path
import sys


PORTABLE_MARKER = "portable.mode"


def application_dir() -> Path:
    """Return the writable application folder, independent of the working directory.

    PyInstaller's internal bundle folder contains imported libraries. Editable
    menus, settings, and user data belong beside the executable instead.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundled_resource_dir() -> Path:
    """Locate immutable bundled resources, with the source tree as a fallback."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return application_dir()


def is_portable(base_dir: str | Path | None = None) -> bool:
    """A packaged release or an explicit marker opts into USB-local storage."""
    root = application_dir() if base_dir is None else Path(base_dir)
    return bool(getattr(sys, "frozen", False) or (root / PORTABLE_MARKER).is_file())


def known_hosts_path(base_dir: str | Path | None = None) -> Path:
    """Resolve the SSH trust store without creating or changing any files."""
    root = application_dir() if base_dir is None else Path(base_dir).resolve()
    if is_portable(root):
        return root / "variables" / "known_hosts"
    return Path.home() / ".ssh" / "known_hosts"


def restart_command(base_dir: str | Path | None = None) -> list[str]:
    """Reopen the current executable or source entry point with its arguments."""
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        root = application_dir() if base_dir is None else Path(base_dir).resolve()
        command.append(str(root / "main.py"))
    return [*command, *sys.argv[1:]]
