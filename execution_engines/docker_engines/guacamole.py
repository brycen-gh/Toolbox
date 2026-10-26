"""Guacamole, PostgreSQL and guacd using locally saved images."""
import os
import re
import secrets

import yaml

from ..result import ExecutionResult
from ..proxy import attach_to_compose, canonical_url
from .moodle import _compose_literal


PARAMETERS = {
    "name": "${GUACAMOLE_CONTAINER_NAME}",
    "database_name": "${GUACAMOLE_DATABASE_CONTAINER_NAME}",
    "guacd_name": "${GUACAMOLE_GUACD_CONTAINER_NAME}",
    "image": "${GUACAMOLE_IMAGE}",
    "database_image": "${GUACAMOLE_DATABASE_IMAGE}",
    "guacd_image": "${GUACAMOLE_GUACD_IMAGE}",
    "recreate": "${GUACAMOLE_RECREATE}",
    "restart": "${GUACAMOLE_RESTART_POLICY}",
    "host_port": "${GUACAMOLE_HOST_PORT}",
    "data_directory": "${GUACAMOLE_DATA_VOLUME}",
}


def deploy(engine, parameters):
    names = {service: str(parameters[key]) for service, key in
             (("guacamole", "name"), ("database", "database_name"), ("guacd", "guacd_name"))}
    if (len(set(names.values())) != 3 or
            any(not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name) for name in names.values())):
        raise ValueError("Guacamole container names must be distinct lowercase names using letters, digits, _ or -")
    port = int(parameters["host_port"])
    if not 1 <= port <= 65535:
        raise ValueError("GUACAMOLE_HOST_PORT must be between 1 and 65535")
    public_url = canonical_url(engine, "guacamole") or f"http://<lab-server>:{port}/guacamole/"
    root = engine._local_data_directory(parameters["data_directory"])
    for directory in ("database", "init", "secrets"):
        if (root / directory).is_symlink():
            raise ValueError(f"Guacamole data directories cannot be symlinks: {root / directory}")
    compose_path = root / "compose.yaml"
    project = "toolbox-" + names["guacamole"]
    recreate = engine._as_bool(parameters.get("recreate", False), "recreate")
    existing = set(engine._docker_read(["container", "ls", "-a", "--format", "{{.Names}}"]).splitlines())
    occupied = existing.intersection(names.values())
    if occupied and not recreate:
        return ExecutionResult(["Guacamole containers already exist. Enable GUACAMOLE_RECREATE to apply changes."], 1)
    for service, name in names.items():
        if name in occupied:
            for label, expected in (("project", project), ("service", service)):
                owner = engine._docker_read([
                    "container", "inspect", "--format",
                    '{{index .Config.Labels "com.docker.compose.' + label + '"}}', name,
                ]).strip()
                if owner != expected:
                    raise ValueError(f"Container {name!r} belongs to another deployment")
    if compose_path.exists():
        previous = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        if any(previous["services"][service]["container_name"] != name for service, name in names.items()):
            raise ValueError("Keep existing Guacamole container names when reusing its data directory")
    checked = engine._run_steps([["docker", "compose", "version"]])
    if checked.returncode:
        return checked
    for key in ("image", "database_image", "guacd_image"):
        image = str(parameters[key]).strip()
        if not image or image.startswith("-"):
            raise ValueError(f"Invalid Guacamole {key}")
        try:
            engine._docker_read(["image", "inspect", image])
        except RuntimeError as exc:
            raise ValueError(f"Image {image!r} is unavailable. Use Save/Update Images or Load Saved Images first.") from exc

    secret_dir = root / "secrets"
    password_path = secret_dir / "database_password"
    if (occupied or compose_path.exists() or (root / "database").exists()) and not password_path.is_file():
        raise ValueError("Guacamole credentials are missing. Restore the original secrets directory before deploying.")
    secret_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not password_path.exists():
        with os.fdopen(os.open(password_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            stream.write(secrets.token_hex(32))
    password = password_path.read_text(encoding="utf-8").strip()
    if not password:
        raise ValueError("Guacamole database credential file is empty")
    engine._sensitive_values.add(password)

    # Generate schema within the image; SQL never passes through action output.
    init_dir = root / "init"
    init_dir.mkdir(exist_ok=True)
    if not (init_dir / "initdb.sql").is_file():
        prepared = engine._run_steps([[
            "docker", "run", "--rm", "--pull", "never", "--user", "0:0",
            "--mount", f"type=bind,source={init_dir},target=/toolbox-init",
            "--entrypoint", "sh", str(parameters["image"]), "-ec",
            "/opt/guacamole/bin/initdb.sh --postgresql > /toolbox-init/initdb.sql.new && "
            "test -s /toolbox-init/initdb.sql.new && "
            "chmod 644 /toolbox-init/initdb.sql.new && "
            "mv /toolbox-init/initdb.sql.new /toolbox-init/initdb.sql",
        ]])
        if prepared.returncode:
            return prepared

    def mount(source, target, read_only=False):
        return {"type": "bind", "source": "./" + source, "target": target, "read_only": read_only}

    shared = {"restart": str(parameters["restart"]), "pull_policy": "never"}
    document = {"services": {
        "database": {
            **shared, "image": parameters["database_image"], "container_name": names["database"],
            "environment": {"POSTGRES_DB": "guacamole", "POSTGRES_USER": "guacamole",
                            "POSTGRES_PASSWORD": password, "PGDATA": "/var/lib/postgresql/data/pgdata"},
            "volumes": [mount("database", "/var/lib/postgresql/data"),
                        mount("init", "/docker-entrypoint-initdb.d", True)],
            "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U guacamole -d guacamole"],
                            "interval": "10s", "timeout": "5s", "retries": 12},
        },
        "guacd": {
            **shared, "image": parameters["guacd_image"], "container_name": names["guacd"],
            # The image checks only every five minutes, matching our entire wait
            # timeout. Probe promptly so a ready daemon does not hold the UI busy.
            "healthcheck": {"test": ["CMD", "nc", "-z", "127.0.0.1", "4822"],
                            "interval": "5s", "timeout": "5s", "retries": 12,
                            "start_period": "10s"},
        },
        "guacamole": {
            **shared, "image": parameters["image"], "container_name": names["guacamole"],
            "environment": {"GUACD_HOSTNAME": "guacd", "GUACD_PORT": "4822",
                            "POSTGRESQL_ENABLED": "true", "POSTGRESQL_HOSTNAME": "database",
                            "POSTGRESQL_PORT": "5432", "POSTGRESQL_DATABASE": "guacamole",
                            "POSTGRESQL_USERNAME": "guacamole", "POSTGRESQL_PASSWORD": password},
            "ports": [f"{port}:8080"],
            "depends_on": {"database": {"condition": "service_healthy"},
                           "guacd": {"condition": "service_healthy"}},
        },
    }}
    attached = attach_to_compose(engine, document, "guacamole", "guacamole")
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
    options = ["--force-recreate"] if recreate else []
    engine._emit("Starting Guacamole stack and checking health (up to 5 minutes). "
                 "guacd is checked every 5 seconds. Cancel Action stops the wait; stack data is retained.\n")
    result = engine._run_steps([command + ["up", "-d", "--wait", "--wait-timeout", "300", "--pull", "never", *options]])
    if result.returncode:
        result.output.append("Guacamole setup failed. Inspect the stack logs before retrying; data is retained. Compose updates do not roll back database changes.")
    else:
        result.output.append(f"Guacamole containers started. Open {public_url}. Initial login: guacadmin / guacadmin; change the password after first sign-in. Existing accounts are not reset.")
    return result
