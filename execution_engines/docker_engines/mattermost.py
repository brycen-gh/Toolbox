"""Mattermost and PostgreSQL deployment using locally saved images."""
import os
import re
import secrets

import yaml

from ..result import ExecutionResult
from ..proxy import attach_to_compose, canonical_url
from .moodle import _compose_literal, validate_site_url

PARAMETERS = {
    "name": "${MATTERMOST_CONTAINER_NAME}",
    "database_name": "${MATTERMOST_DATABASE_CONTAINER_NAME}",
    "image": "${MATTERMOST_IMAGE}",
    "database_image": "${MATTERMOST_DATABASE_IMAGE}",
    "recreate": "${MATTERMOST_RECREATE}",
    "restart": "${MATTERMOST_RESTART_POLICY}",
    "host_port": "${MATTERMOST_HOST_PORT}",
    "site_url": "${MATTERMOST_SITE_URL}",
    "data_directory": "${MATTERMOST_DATA_VOLUME}",
}


def deploy(engine, parameters):
    names = {"mattermost": str(parameters["name"]), "database": str(parameters["database_name"])}
    if len(set(names.values())) != 2 or any(not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name) for name in names.values()):
        raise ValueError("Mattermost container names must be distinct lowercase names using letters, digits, _ or -")
    port = int(parameters["host_port"])
    if not 1 <= port <= 65535:
        raise ValueError("MATTERMOST_HOST_PORT must be between 1 and 65535")
    try:
        site_url = validate_site_url(canonical_url(engine, "mattermost") or str(parameters["site_url"]))
    except ValueError as exc:
        raise ValueError(str(exc).replace("MOODLE_SITE_URL", "MATTERMOST_SITE_URL")) from exc
    root = engine._local_data_directory(parameters["data_directory"])
    folders = ("database", "secrets", "config", "data", "logs", "plugins", "client-plugins", "bleve-indexes")
    for folder in folders:
        if (root / folder).is_symlink():
            raise ValueError(f"Mattermost data directories cannot be symlinks: {root / folder}")
    compose_path = root / "compose.yaml"
    project = "toolbox-" + names["mattermost"]
    recreate = engine._as_bool(parameters.get("recreate", False), "recreate")
    existing = set(engine._docker_read(["container", "ls", "-a", "--format", "{{.Names}}"]).splitlines())
    occupied = existing.intersection(names.values())
    if occupied and not recreate:
        return ExecutionResult(["Mattermost containers already exist. Enable MATTERMOST_RECREATE to apply changes."], 1)
    for service, name in names.items():
        if name in occupied:
            for label, expected in (("project", project), ("service", service)):
                owner = engine._docker_read(["container", "inspect", "--format",
                    '{{index .Config.Labels "com.docker.compose.' + label + '"}}', name]).strip()
                if owner != expected:
                    raise ValueError(f"Container {name!r} belongs to another deployment")
    if compose_path.exists():
        previous = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        if any(previous["services"][service]["container_name"] != name for service, name in names.items()):
            raise ValueError("Keep existing Mattermost container names when reusing its data directory")
    checked = engine._run_steps([["docker", "compose", "version"]])
    if checked.returncode:
        return checked
    for key in ("image", "database_image"):
        image = str(parameters[key]).strip()
        if not image or image.startswith("-"):
            raise ValueError(f"Invalid Mattermost {key}")
        try:
            engine._docker_read(["image", "inspect", image])
        except RuntimeError as exc:
            raise ValueError(f"Image {image!r} is unavailable. Use Save/Update Images or Load Saved Images first.") from exc
    secret_dir = root / "secrets"
    password_path = secret_dir / "database_password"
    if (occupied or compose_path.exists() or (root / "database").exists()) and not password_path.is_file():
        raise ValueError("Mattermost credentials are missing. Restore the original secrets directory before deploying.")
    secret_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not password_path.exists():
        with os.fdopen(os.open(password_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            stream.write(secrets.token_hex(32))
    password = password_path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[a-f0-9]{64}", password):
        raise ValueError("Mattermost database credential file is invalid")
    engine._sensitive_values.add(password)
    app_folders = {folder: ("client/plugins" if folder == "client-plugins" else folder)
                   for folder in folders if folder not in ("database", "secrets")}
    for folder in app_folders:
        (root / folder).mkdir(exist_ok=True)
    # Mattermost's minimal image has no shell. Reuse the saved PostgreSQL
    # image for preparation, without starting its database entrypoint.
    # Prepare only mount roots; never recursively change existing user data.
    mounts = [argument for folder in app_folders for argument in
              ("--mount", f"type=bind,source={root / folder},target=/prepare/{folder}")]
    prepared = engine._run_steps([["docker", "run", "--rm", "--pull", "never", "--user", "0:0",
        *mounts, "--entrypoint", "/bin/sh", str(parameters["database_image"]), "-ec", "chown 2000:2000 /prepare/*"]])
    if prepared.returncode:
        return prepared
    def mount(source, target):
        return {"type": "bind", "source": "./" + source, "target": target}
    shared = {"restart": str(parameters["restart"]), "pull_policy": "never"}
    document = {"services": {
        "database": {
            **shared, "image": parameters["database_image"], "container_name": names["database"],
            "environment": {"POSTGRES_DB": "mattermost", "POSTGRES_USER": "mmuser", "POSTGRES_PASSWORD": password},
            "volumes": [mount("database", "/var/lib/postgresql")],
            "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U mmuser -d mattermost"],
                            "interval": "5s", "timeout": "5s", "retries": 30},
        },
        "mattermost": {
            **shared, "image": parameters["image"], "container_name": names["mattermost"],
            "environment": {"MM_SQLSETTINGS_DRIVERNAME": "postgres",
                "MM_SQLSETTINGS_DATASOURCE": f"postgres://mmuser:{password}@database:5432/mattermost?sslmode=disable&connect_timeout=10",
                "MM_SERVICESETTINGS_SITEURL": site_url, "MM_BLEVESETTINGS_INDEXDIR": "/mattermost/bleve-indexes"},
            "volumes": [mount(folder, "/mattermost/" + target) for folder, target in app_folders.items()],
            "ports": [f"{port}:8065"],
            "depends_on": {"database": {"condition": "service_healthy"}},
        },
    }}
    attached = attach_to_compose(engine, document, "mattermost", "mattermost")
    if attached.returncode:
        return attached
    temporary = root / "compose.yaml.new"
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            yaml.safe_dump(_compose_literal(document), stream, sort_keys=False)
        command = ["docker", "compose", "--project-name", project, "-f", str(temporary)]
        validated = engine._run_steps([command + ["config", "--quiet"]])
        if validated.returncode:
            return validated
        os.replace(temporary, compose_path)
    finally:
        temporary.unlink(missing_ok=True)
    command = ["docker", "compose", "--project-name", project, "-f", str(compose_path)]
    result = engine._run_steps([command + ["up", "-d", "--wait", "--wait-timeout", "300", "--pull", "never",
                                          *(["--force-recreate"] if recreate else [])]])
    result.output.append("Mattermost setup failed; data is retained. Inspect container logs before retrying." if result.returncode else
                         f"Mattermost started. Open {site_url} and create the initial administrator account on a fresh installation.")
    return result
