"""Moodle and PostgreSQL deployment using locally available container images."""
import os
import re
import secrets
from urllib.parse import urlsplit

import yaml

from ..result import ExecutionResult


PARAMETERS = {
    "name": "${MOODLE_CONTAINER_NAME}",
    "database_name": "${MOODLE_DATABASE_CONTAINER_NAME}",
    "image": "${MOODLE_IMAGE}",
    "database_image": "${MOODLE_DATABASE_IMAGE}",
    "recreate": "${MOODLE_RECREATE}",
    "restart": "${MOODLE_RESTART_POLICY}",
    "host_port": "${MOODLE_HOST_PORT}",
    "site_url": "${MOODLE_SITE_URL}",
    "site_name": "${MOODLE_SITE_NAME}",
    "admin_username": "${MOODLE_ADMIN_USERNAME}",
    "admin_email": "${MOODLE_ADMIN_EMAIL}",
    "data_directory": "${MOODLE_DATA_VOLUME}",
}


def validate_site_url(value):
    """Moodle's canonical address must be public and contain no credentials."""
    value = str(value).strip().rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path
            or any(c.isspace() for c in value) or "\\" in value):
        raise ValueError("MOODLE_SITE_URL must be an HTTP(S) site URL without credentials, path, query or fragment")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid MOODLE_SITE_URL port")
    return value


def _compose_literal(value):
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [_compose_literal(item) for item in value]
    if isinstance(value, dict):
        return {key: _compose_literal(item) for key, item in value.items()}
    return value


def deploy(engine, parameters):
    name, database_name = (str(parameters[key]) for key in ("name", "database_name"))
    if (name == database_name or any(not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", item)
                                     for item in (name, database_name))):
        raise ValueError("Moodle container names must be distinct lowercase names using letters, digits, _ or -")
    site_url = validate_site_url(parameters["site_url"])
    public_url = urlsplit(site_url)
    public_port = public_url.port or (443 if public_url.scheme == "https" else 80)
    site_name = str(parameters["site_name"])
    # alpine-moodle expands the site name unquoted in its installer CLI.
    if not site_name or any(character.isspace() for character in site_name):
        raise ValueError("MOODLE_SITE_NAME must not contain whitespace for this image's startup script. Use Training_Moodle instead of Training Moodle.")
    port = int(parameters["host_port"])
    if not 1 <= port <= 65535:
        raise ValueError("MOODLE_HOST_PORT must be between 1 and 65535")
    if not str(parameters["admin_username"]).strip() or "@" not in str(parameters["admin_email"]):
        raise ValueError("Set MOODLE_ADMIN_USERNAME and a valid MOODLE_ADMIN_EMAIL")
    root = engine._local_data_directory(parameters["data_directory"])
    compose_path = root / "compose.yaml"
    project = "toolbox-" + name
    recreate = engine._as_bool(parameters.get("recreate", False), "recreate")
    existing = set(engine._docker_read(["container", "ls", "-a", "--format", "{{.Names}}"]).splitlines())
    occupied = existing.intersection((name, database_name))
    if occupied and not recreate:
        return ExecutionResult(["Moodle containers already exist. Enable MOODLE_RECREATE to apply changes."], 1)
    for container, service in ((name, "moodle"), (database_name, "database")):
        if container in occupied:
            for label, expected in (("project", project), ("service", service)):
                owner = engine._docker_read([
                    "container", "inspect", "--format",
                    '{{index .Config.Labels "com.docker.compose.' + label + '"}}', container,
                ]).strip()
                if owner != expected:
                    raise ValueError(f"Container {container!r} belongs to another deployment")
    if compose_path.exists():
        previous = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        if any(previous["services"][service]["container_name"] != container
               for service, container in (("moodle", name), ("database", database_name))):
            raise ValueError("Keep the existing Moodle container names when reusing its data directory")
    checked = engine._run_steps([["docker", "compose", "version"]])
    if checked.returncode:
        return checked
    for key in ("image", "database_image"):
        image = str(parameters[key]).strip()
        if not image or image.startswith("-"):
            raise ValueError(f"Invalid Moodle {key}")
        try:
            engine._docker_read(["image", "inspect", image])
        except RuntimeError as exc:
            raise ValueError(f"Image {image!r} is unavailable. Use Save/Update Images or Load Saved Images first.") from exc

    secret_dir = root / "secrets"
    keys = ("database_password", "admin_password")
    initialized = occupied or compose_path.exists() or any((root / path).exists() for path in ("database", "moodledata"))
    if initialized and any(not (secret_dir / key).is_file() for key in keys):
        raise ValueError("Moodle credentials are missing. Restore the original secrets directory before deploying.")
    secret_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    passwords = {}
    for key in keys:
        path = secret_dir / key
        if not path.exists():
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
                stream.write("GGpassword1!" if key == "admin_password"
                             else "Aa1!" + secrets.token_hex(24))
        passwords[key] = path.read_text(encoding="utf-8").strip()
        if not passwords[key]:
            raise ValueError(f"Moodle credential file is empty: {path}")
        engine._sensitive_values.add(passwords[key])

    def mount(directory, target):
        return {"type": "bind", "source": "./" + directory, "target": target}

    shared = {"restart": str(parameters["restart"]), "pull_policy": "never"}
    document = {"services": {
        "database": {
            **shared, "image": parameters["database_image"], "container_name": database_name,
            "environment": {"POSTGRES_DB": "moodle", "POSTGRES_USER": "moodle",
                            "POSTGRES_PASSWORD": passwords["database_password"],
                            "PGDATA": "/var/lib/postgresql/data/pgdata"},
            "volumes": [mount("database", "/var/lib/postgresql/data")],
            "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U moodle -d moodle"],
                            "interval": "10s", "timeout": "5s", "retries": 12},
        },
        "moodle": {
            **shared, "image": parameters["image"], "container_name": name,
            "environment": {
                "SITE_URL": site_url, "DB_TYPE": "pgsql", "DB_HOST": "database",
                "DB_PORT": "5432", "DB_NAME": "moodle", "DB_USER": "moodle",
                "DB_PASS": passwords["database_password"], "REDIS_HOST": "",
                "MOODLE_SITENAME": site_name,
                "MOODLE_USERNAME": str(parameters["admin_username"]),
                "MOODLE_EMAIL": str(parameters["admin_email"]),
                "MOODLE_PASSWORD": passwords["admin_password"],
                "SMTP_HOST": "", "SMTP_USER": "", "SMTP_PASSWORD": "",
                "SSLPROXY": "true" if site_url.startswith("https:") else "false",
                # Moodle compares SERVER_PORT with its canonical URL, even behind
                # Docker's port forwarding. nginx otherwise reports internal 8080.
                "POST_CONFIGURE_COMMANDS": (
                    "sed -i -E 's/^(fastcgi_param[[:space:]]+SERVER_PORT[[:space:]]+)[^;]+;/"
                    f"\\1{public_port};/' /etc/nginx/fastcgi_params"
                ),
            },
            "ports": [f"{port}:8080"],
            "volumes": [mount("moodledata", "/var/www/moodledata")],
            "depends_on": {"database": {"condition": "service_healthy"}},
            "healthcheck": {"test": ["CMD", "curl", "--silent", "--fail", "http://127.0.0.1:8080/fpm-ping"],
                            "interval": "15s", "timeout": "10s", "retries": 40, "start_period": "60s"},
        },
    }}
    # Only prepare the dedicated application directories, never recursively chown existing data.
    mounts = []
    for directory in ("moodledata",):
        path = root / directory
        if path.is_symlink():
            raise ValueError(f"Moodle data directories cannot be symlinks: {path}")
        path.mkdir(exist_ok=True)
        mounts += ["--mount", f"type=bind,source={path},target=/toolbox-{directory}"]
    prepared = engine._run_steps([[
        "docker", "run", "--rm", "--pull", "never", "--user", "0:0", "--entrypoint", "sh",
        *mounts, str(parameters["image"]), "-ec",
        "chown 65534:65534 /toolbox-moodledata",
    ]])
    if prepared.returncode:
        return prepared
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
    result = engine._run_steps([command + ["up", "-d", "--wait", "--wait-timeout", "900", "--pull", "never", *options]])
    if result.returncode:
        result.output.append("Moodle setup did not complete. Inspect Moodle and database logs before retrying; data is retained. Compose updates do not roll back database changes.")
    else:
        result.output.append(f"Moodle is available at {site_url}. Initial admin: {parameters['admin_username']}. Read the initial password locally from {secret_dir / 'admin_password'}. Existing accounts are not reset.")
    return result
