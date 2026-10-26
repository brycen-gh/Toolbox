"""Nextcloud deployment recipe."""
from copy import deepcopy
import uuid
from urllib.parse import urlsplit

from ..proxy import canonical_url
from ..result import ExecutionResult


_CONFIG_FILENAME = "zz-toolbox-hostname.config.php"


def build_hostname_config(engine, parameters, url):
    """Add an independent, read-only config without replacing trusted domains.

    Nextcloud merges supplementary config files recursively. A named array key
    adds the lab hostname while preserving the existing numeric domain entries.
    """
    hostname = urlsplit(url).hostname
    source = parameters["volumes"][0].rsplit(":", 1)[0]
    data_root = engine._local_data_directory(source)
    directory = data_root.parent / (data_root.name + "-proxy-config")
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = directory / ("hostname-" + uuid.uuid4().hex + ".php")
    # hostname is derived from validated DNS labels, so PHP quoting is literal.
    snapshot.write_text(
        "<?php\n// Toolbox hostname routing; original config.php stays untouched.\n"
        "$CONFIG = [\n"
        f"  'trusted_domains' => ['toolbox_lab' => '{hostname}'],\n"
        f"  'overwritehost' => '{hostname}',\n"
        "  'overwriteprotocol' => 'http',\n"
        f"  'overwrite.cli.url' => 'http://{hostname}',\n"
        "];\n", encoding="utf-8",
    )
    snapshot.chmod(0o644)
    return snapshot


PARAMETERS = {
    "name": "${NEXTCLOUD_CONTAINER_NAME}",
    "image": "${NEXTCLOUD_IMAGE}",
    "recreate": "${NEXTCLOUD_RECREATE}",
    "restart": "${NEXTCLOUD_RESTART_POLICY}",
    "ports": ["${NEXTCLOUD_HOST_PORT}:${NEXTCLOUD_CONTAINER_PORT}"],
    "volumes": ["${NEXTCLOUD_DATA_VOLUME}:${NEXTCLOUD_DATA_PATH}"],
}


# Deploy nextcloud using the resolved service recipe and shared engine.
def deploy(engine, parameters):
    url = canonical_url(engine, "nextcloud")
    if not url:
        return engine._run_container(parameters)
    names = engine._docker_read(["container", "ls", "-a", "--format", "{{.Names}}"] ).splitlines()
    if parameters["name"] in names and not engine._as_bool(parameters.get("recreate", False), "recreate"):
        return ExecutionResult([f"Container {parameters['name']!r} exists. Enable Recreate existing container to apply hostname routing."], 1)
    volume = engine._volume_argument(parameters["volumes"][0])
    # A nested bind makes a fresh config directory nonempty. Seed only missing
    # image templates first, so Nextcloud's first-run setup remains functional.
    prepared = engine._run_steps([[
        "docker", "run", "--rm", "--pull", "never", "--user", "0:0",
        "--entrypoint", "sh", "-v", volume, parameters["image"], "-ec",
        "set -eu; "
        "if [ ! -d /var/www/html/config ]; then mkdir -p /var/www/html/config; chown www-data:www-data /var/www/html/config; fi; "
        f"if [ -L /var/www/html/config/{_CONFIG_FILENAME} ] || [ -s /var/www/html/config/{_CONFIG_FILENAME} ]; then echo 'Refusing to hide an existing Nextcloud hostname config' >&2; exit 1; fi; "
        "cp -an /usr/src/nextcloud/config/. /var/www/html/config/",
    ]])
    if prepared.returncode:
        return prepared
    snapshot = build_hostname_config(engine, parameters, url)
    recipe = deepcopy(parameters)
    recipe["volumes"].append(f"{snapshot}:/var/www/html/config/{_CONFIG_FILENAME}:ro")
    result = engine._run_container(recipe)
    result.output = prepared.output + result.output
    result.output.append(f"Nextcloud hostname configuration: {snapshot}. Existing trusted domains are retained.")
    return result
