"""Offline release verification without creating a window or running actions."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import sys

import customtkinter
import tkinter
import yaml

from .main import ExecutionEngine
from .runtime import is_portable
from .settings import load_variables


def check_application(base_dir):
    base_dir = Path(base_dir).resolve()
    report = {"ok": True, "application_dir": str(base_dir),
              "portable": is_portable(base_dir), "python": sys.version.split()[0],
              "tk": tkinter.TkVersion, "errors": [], "menus": 0, "variable_files": 0}
    for name in ("menus", "variables", "assets/icons", "scripts"):
        if not (base_dir / name).is_dir():
            report["errors"].append(f"Missing application directory: {name}")
    menu_paths = sorted((base_dir / "menus").glob("*.yaml"))
    if not menu_paths:
        report["errors"].append("No menu files found")
    for path in menu_paths:
        try:
            if not isinstance(yaml.safe_load(path.read_text(encoding="utf-8")), dict):
                raise ValueError("Expected a mapping")
            report["menus"] += 1
        except (OSError, ValueError, yaml.YAMLError) as exc:
            report["errors"].append(f"Menu {path.name}: {exc}")
    for path in sorted((base_dir / "variables").glob("*-variables.yaml")):
        try:
            load_variables(path)
            report["variable_files"] += 1
        except (OSError, ValueError, yaml.YAMLError) as exc:
            report["errors"].append(f"Variables {path.name}: {exc}")
    theme = Path(customtkinter.__file__).parent / "assets" / "themes" / "blue.json"
    if not theme.is_file():
        report["errors"].append("Missing bundled CustomTkinter themes")
    engine = ExecutionEngine(base_dir)
    report["actions"] = len(engine.actions)
    if not engine.actions or not all(callable(handler) for handler in engine.actions.values()):
        report["errors"].append("Execution engine registration failed")
    report["dependencies"] = {}
    for name in ("customtkinter", "PyYAML", "Pillow", "cryptography", "paramiko"):
        try:
            report["dependencies"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report["errors"].append(f"Missing dependency metadata: {name}")
    report["ok"] = not report["errors"]
    return report


def run_self_check(base_dir, argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--report", type=Path, help="Write the verification report as JSON")
    args = parser.parse_args(argv)
    report = check_application(base_dir)
    encoded = json.dumps(report, indent=2)
    if args.report:
        args.report.write_text(encoded + "\n", encoding="utf-8")
    if sys.stdout is not None:
        print(encoded)
    return 0 if report["ok"] else 1
