#!/usr/bin/env python3
"""Build a fresh, native portable folder without copying private working data.

Python modules, tracked menus and assets come from this checkout. Variable
defaults come from committed HEAD plus explicit new service schemas, with
credential fields and local UI state reset.
Existing release directories are never overwritten or removed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import uuid
from zipfile import ZipFile

import yaml


SOURCE_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOTS = ("assets", "menus", "variables", "scripts")
DATA_DIRECTORIES = ("data/containers", "backups", "repos/containers", "repos/pcap", "share")
ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".html", ".css", ".js", ".json", ".md", ".txt", ".ttf", ".otf", ".woff", ".woff2"}
SAFE_UI = {"theme": "Green", "appearance": "Dark", "home_background": ""}
PRIVATE_FIELD = re.compile(r"PASSWORD|TOKEN|SECRET|PRIVATE_KEY|CREDENTIAL_SALT|USERNAME_ENCRYPTED", re.I)
PLACEHOLDER = re.compile(r"\$\{[A-Z_][A-Z0-9_]*\}")

USB_README = """TOOLBOX / PORTABLE

Open Toolbox.exe on Windows, or ./Toolbox on Linux. Keep this entire folder
together, including _internal. Python does not need to be installed.

Settings, menus, assets and helper scripts remain editable beside the app.
Data locations: data/containers, backups, repos/containers, repos/pcap, share.
The portable.mode file enables portable defaults. Keep it with the application.

Docker, WSL, PowerShell, packet tools and administrator access belong to the
host. Check Home > On this computer before an exercise. Container bind mounts must
be reachable by the Docker daemon; a remote daemon cannot read this USB.

Optional hostnames: set the domain in Home > Options, install nginx-proxy,
then recreate the desired services and Home. Client hosts-file entries are
available from Home Options. See HOSTNAMES.md for the complete lab setup.

Credential fields are blank in fresh releases. Configure your own credentials
and Portainer setup token before use. Store the drive securely.

To update, close Toolbox and stop its share/capture/replay jobs. Back up first.
Extract the new release alongside the old folder. Copy your variables, menus,
data, backups, repos and share into the new folder only after reviewing the
new defaults. Copy a custom background too, if used. Keep the new executable,
_internal, portable.mode and helper scripts together. Do not overwrite the old
release or unplug the drive while jobs, writes or mounted containers use it.

Windows and Linux builds are separate. Linux requires a graphical session and
compatible system libraries. exFAT is useful for file exchange, but Linux
container databases can require a Linux filesystem's permissions and links.
Use host-local container storage plus USB backups when necessary. FAT32 has
a 4 GiB file limit. A USB SSD is recommended for large archives and databases.
"""


class BuildError(RuntimeError):
    """A build stopped without replacing an existing release."""


def _git(source: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(["git", "-C", str(source), *arguments],
                                   check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BuildError("Build from a Git checkout with a committed HEAD and Git installed.") from exc
    return completed.stdout


def _resource_allowed(path: PurePosixPath) -> bool:
    if len(path.parts) < 2 or path.parts[0] not in RESOURCE_ROOTS:
        return False
    if path.is_absolute() or ".." in path.parts or any(part.startswith(".") for part in path.parts):
        return False
    suffix = path.suffix.lower()
    if path.parts[0] in {"menus", "variables"}:
        return suffix in {".yaml", ".yml"}
    if path.parts[0] == "scripts":
        return suffix in {".ps1", ".sh"}
    return suffix in ASSET_EXTENSIONS


def sanitize_variables(document):
    """Drop stored credentials while preserving declarative secret placeholders."""
    if isinstance(document, list):
        return [sanitize_variables(value) for value in document]
    if not isinstance(document, dict):
        return document
    safe = {}
    for key, value in document.items():
        if PRIVATE_FIELD.search(str(key)) and not (
                isinstance(value, str) and PLACEHOLDER.fullmatch(value)):
            safe[key] = ""
        else:
            safe[key] = sanitize_variables(value)
    return safe


def prepare_resources(source: Path, destination: Path) -> dict:
    """Stage current UI resources and sanitized default settings, never user data."""
    source = source.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise BuildError(f"Destination already exists; choose a new folder: {destination}")
    revision = _git(source, "rev-parse", "HEAD").decode("ascii").strip()
    archive = _git(source, "archive", "--format=zip", "HEAD", *RESOURCE_ROOTS)
    resources = {}
    with ZipFile(BytesIO(archive)) as files:
        for member in files.infolist():
            path = PurePosixPath(member.filename)
            if member.is_dir() or not _resource_allowed(path):
                continue
            if stat.S_ISLNK(member.external_attr >> 16):
                raise BuildError(f"Resource symlinks cannot be distributed: {path}")
            content = files.read(member)
            if path.parts[0] != "variables":
                current = source.joinpath(*path.parts)
                if not current.is_file():
                    continue
                if current.is_symlink() or not current.resolve().is_relative_to(source):
                    raise BuildError(f"Resource leaves the source directory: {path}")
                content = current.read_bytes()
            if path.parts[0] == "variables":
                if path.as_posix() == "variables/ui.yaml":
                    document = dict(SAFE_UI)
                else:
                    document = sanitize_variables(yaml.safe_load(content))
                    if not isinstance(document, dict):
                        raise BuildError(f"Variable file must contain a mapping: {path}")
                    if path.as_posix() == "variables/deployment-variables.yaml":
                        document.setdefault("Variables", {})["CONTAINER_DATA_ROOT"] = "./data/containers"
                content = yaml.safe_dump(document, sort_keys=False, allow_unicode=True).encode("utf-8")
            resources[path.as_posix()] = content
    # A newly introduced service may not be committed yet. Include only this
    # explicit public schema; arbitrary working YAML and credential stores stay out.
    proxy_name = "variables/docker_variables/nginx_proxy.yaml"
    proxy_path = source / proxy_name
    if proxy_name not in resources and proxy_path.is_file():
        if proxy_path.is_symlink() or not proxy_path.resolve().is_relative_to(source):
            raise BuildError("Proxy defaults leave the source directory")
        defaults = sanitize_variables(yaml.safe_load(proxy_path.read_text(encoding="utf-8")))
        resources[proxy_name] = yaml.safe_dump(defaults, sort_keys=False, allow_unicode=True).encode("utf-8")
    deployment_name = "variables/deployment-variables.yaml"
    if proxy_name in resources and deployment_name in resources:
        deployment = yaml.safe_load(resources[deployment_name])
        deployment.setdefault("Variables", {})["LAB_DOMAIN"] = ""
        includes = deployment.setdefault("Includes", [])
        if "docker_variables/nginx_proxy.yaml" not in includes:
            includes.append("docker_variables/nginx_proxy.yaml")
        resources[deployment_name] = yaml.safe_dump(deployment, sort_keys=False, allow_unicode=True).encode("utf-8")
    guide = source / "docs" / "hostname-routing.md"
    if guide.is_file() and not guide.is_symlink() and guide.resolve().is_relative_to(source):
        resources["HOSTNAMES.md"] = guide.read_bytes()
    for folder in RESOURCE_ROOTS:
        if not any(path.startswith(folder + "/") for path in resources):
            raise BuildError(f"Committed resources are missing: {folder}/")
    if "variables/deployment-variables.yaml" not in resources:
        raise BuildError("Committed deployment defaults are missing.")
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in resources.items():
        target = destination.joinpath(*PurePosixPath(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        if target.suffix == ".sh":
            target.chmod(target.stat().st_mode | stat.S_IXUSR)
    for directory in DATA_DIRECTORIES:
        (destination / directory).mkdir(parents=True, exist_ok=True)
    (destination / "portable.mode").write_text("Toolbox portable folder v1\n", encoding="utf-8")
    (destination / "README-USB.txt").write_text(USB_README, encoding="utf-8")
    manifest = {
        "format": 1,
        "defaults_revision": revision,
        "defaults_source": "sanitized Git HEAD settings plus explicit new proxy schema; current tracked menus/assets/scripts; user data excluded",
        "platform": platform.system(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "prepared_only": True,
        "resources_sha256": {name: hashlib.sha256(content).hexdigest()
                             for name, content in sorted(resources.items())},
    }
    (destination / "build-info.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def pyinstaller_command(source: Path, work: Path, *, system: str | None = None) -> list[str]:
    system = system or platform.system()
    command = [sys.executable, "-m", "PyInstaller", "--onedir", "--name", "Toolbox",
               "--contents-directory", "_internal", "--noupx",
               "--distpath", str(work / "dist"), "--workpath", str(work / "analysis"),
               "--specpath", str(work), "--paths", str(source),
               "--collect-data", "customtkinter", "--collect-submodules", "execution_engines"]
    for distribution in ("customtkinter", "PyYAML", "Pillow", "cryptography", "paramiko"):
        command.extend(["--copy-metadata", distribution])
    if system == "Windows":
        command.append("--windowed")
        icon = source / "assets" / "icons" / "default.png"
        if icon.is_file():
            command.extend(["--icon", str(icon)])
    command.append(str(source / "main.py"))
    return command


def verify_bundle(bundle: Path) -> dict:
    """Check frozen imports and external resources without creating a Tk window."""
    executable = bundle / ("Toolbox.exe" if platform.system() == "Windows" else "Toolbox")
    report = bundle / ".build-check.json"
    try:
        subprocess.run([str(executable), "--self-check", "--report", str(report)],
                       cwd=bundle.parent, check=True, timeout=120, capture_output=True)
        result = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise BuildError("Frozen self-check failed; inspect the retained build folder before distributing.") from exc
    finally:
        report.unlink(missing_ok=True)
    if result.get("ok") is not True:
        raise BuildError("Frozen self-check did not report success.")
    if result.get("portable") is not True or Path(result.get("application_dir", "")).resolve() != bundle.resolve():
        raise BuildError("Frozen self-check did not use the portable application directory.")
    return result


def validate_tk() -> None:
    # This creates a Tcl interpreter, never a window or a display connection.
    # Fail before freezing if the builder cannot read its Tcl installation.
    try:
        import tkinter
    except ImportError as exc:
        raise BuildError("Tkinter is missing. Install Python's Tk support before building.") from exc
    try:
        tkinter.Tcl().eval("info library")
    except (OSError, tkinter.TclError) as exc:
        raise BuildError("Tcl/Tk cannot initialize. Build with Python's Tk support installed and its Tcl files readable.") from exc


def build(source: Path, output: Path, *, prepare_only: bool = False) -> Path:
    source = source.resolve()
    output = output.resolve()
    if output.exists():
        raise BuildError(f"Destination already exists; choose a new folder: {output}")
    if not prepare_only and platform.system() not in {"Windows", "Linux"}:
        raise BuildError("Portable builds currently support Windows and Linux only; build on the target OS.")
    if not prepare_only and importlib.util.find_spec("PyInstaller") is None:
        raise BuildError("Install build tooling first: python -m pip install -r requirements-build.txt")
    if not prepare_only:
        validate_tk()
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    # Every build gets its own folder. No cleanup removes earlier builds or releases.
    work = source / "build" / "portable" / identifier
    work.mkdir(parents=True, exist_ok=False)
    resources = work / "resources"
    manifest = prepare_resources(source, resources)
    if prepare_only:
        release = resources
    else:
        print(f"Building native {platform.system()} bundle; work files: {work}", flush=True)
        subprocess.run(pyinstaller_command(source, work), cwd=source, check=True)
        release = work / "dist" / "Toolbox"
        for child in resources.iterdir():
            target = release / child.name
            if target.exists():
                raise BuildError(f"Unexpected bundled resource collision: {target}")
            if child.is_dir():
                shutil.copytree(child, target)
            else:
                shutil.copy2(child, target)
        manifest["prepared_only"] = False
        manifest["pyinstaller"] = importlib.metadata.version("PyInstaller")
        # Keep the verification result without publishing the builder's local path.
        manifest["self_check"] = {key: value for key, value in verify_bundle(release).items()
                                  if key != "application_dir"}
        (release / "build-info.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    # copytree refuses an existing destination, including one created during the build.
    # This never upgrades in place, deletes a release, or copies working private data.
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(release, output)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true",
                        help="stage sanitized committed resources only; no executable is built")
    parser.add_argument("--output", type=Path,
                        help="new destination directory; existing paths are always refused")
    arguments = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = "prepared" if arguments.prepare_only else platform.system().lower()
    output = arguments.output or SOURCE_ROOT / "dist" / f"Toolbox-{label}-{platform.machine().lower()}-{stamp}"
    try:
        result = build(SOURCE_ROOT, output, prepare_only=arguments.prepare_only)
    except (BuildError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Build stopped: {exc}", file=sys.stderr)
        return 1
    print(f"{'Prepared resources (no executable)' if arguments.prepare_only else 'Portable release'}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
