"""Etherpad deployment recipe."""
from pathlib import Path

PARAMETERS = {
    "name": "${ETHERPAD_CONTAINER_NAME}",
    "image": "${ETHERPAD_IMAGE}",
    "recreate": "${ETHERPAD_RECREATE}",
    "restart": "${ETHERPAD_RESTART_POLICY}",
    "ports": ["${ETHERPAD_HOST_PORT}:${ETHERPAD_CONTAINER_PORT}"],
    "volumes": ["${ETHERPAD_DATA_VOLUME}:${ETHERPAD_DATA_PATH}"],
}


# Deploy etherpad using the resolved service recipe and shared engine.
def deploy(engine, parameters):
    # Prepare only the dedicated data directory and Etherpad's known writable files.
    source = parameters["volumes"][0].split(":", 1)[0]
    directory = Path(source).expanduser()
    if not directory.is_absolute():
        directory = engine.base_dir / directory
    directory = directory.resolve()
    if directory in {Path("/"), Path.home(), engine.base_dir.resolve()}:
        raise ValueError("Etherpad requires a dedicated data directory")
    directory.mkdir(parents=True, exist_ok=True)
    prepared = engine._run_steps([[
        "docker", "run", "--rm", "--user", "0:0", "--entrypoint", "sh",
        "-v", f"{directory}:/toolbox-data", parameters["image"], "-c",
        'set -eu; owner="$(id -u etherpad):$(id -g etherpad)"; '
        'chown "$owner" /toolbox-data; '
        'for file in dirty.db installed_plugins.json; do '
        'if [ -L "/toolbox-data/$file" ]; then echo "Refusing data-file symlink" >&2; exit 1; fi; '
        'if [ -f "/toolbox-data/$file" ]; then chown "$owner" "/toolbox-data/$file"; fi; done',
    ]])
    if prepared.returncode:
        return prepared
    return engine._run_container(parameters)
