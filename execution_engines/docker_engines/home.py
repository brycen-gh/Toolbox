"""Generate the public Home portal without exporting private variables."""
import json
from pathlib import Path
import re
import shutil
import uuid

PARAMETERS = {
    "name": "${HOME_CONTAINER_NAME}", "image": "${HOME_IMAGE}",
    "recreate": "${HOME_RECREATE}", "restart": "${HOME_RESTART_POLICY}",
    "ports": ["${HOME_HOST_PORT}:80"],
    "directory": "${HOME_DATA_VOLUME}", "public_host": "${HOME_PUBLIC_HOST}",
    "services": [
        {"name": "OpenProject", "port": "${OPENPROJECT_HOST_PORT}", "scheme": "http", "description": "Plan projects, assign work, and track your team's progress."},
        {"name": "Etherpad", "port": "${ETHERPAD_HOST_PORT}", "scheme": "http", "description": "Write together. Share notes and collaborate in real time."},
        {"name": "Nextcloud", "port": "${NEXTCLOUD_HOST_PORT}", "scheme": "http", "description": "Keep your lab files and shared resources in one place."},
        {"name": "CTFd", "port": "${CTFD_HOST_PORT}", "scheme": "http", "description": "Explore challenges, submit flags, and follow the scoreboard."},
        {"name": "Portainer", "port": "${PORTAINER_HTTPS_HOST_PORT}", "scheme": "https", "description": "Instructor tools for managing the lab's containers."},
        {"name": "Zulip", "port": "${ZULIP_HTTPS_HOST_PORT}", "scheme": "https", "description": "Keep conversations organized with channels and topics."},
    ],
}


# Validate public fields and build an independent snapshot for safe recreation.
def build_portal(base_dir, parameters):
    host = str(parameters["public_host"]).strip()
    if host != "auto" and not re.fullmatch(r"[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\]", host):
        raise ValueError("HOME_PUBLIC_HOST must be auto, a hostname, IPv4 address, or bracketed IPv6 address; omit scheme and port.")
    services = []
    for item in parameters["services"]:
        port = int(item["port"])
        if not 1 <= port <= 65535 or item["scheme"] not in {"http", "https"}:
            raise ValueError("Invalid Home service URL settings")
        services.append({"name": item["name"], "description": item["description"], "port": port, "scheme": item["scheme"]})
    root = Path(parameters["directory"]).expanduser()
    if not root.is_absolute():
        root = Path(base_dir) / root
    root = root.resolve()
    if ":" in str(root):
        raise ValueError("Home requires a Linux data path without colons.")
    destination = root / ("site-" + uuid.uuid4().hex)
    shutil.copytree(Path(base_dir) / "assets" / "home", destination)
    (destination / "services.json").write_text(json.dumps({"host": host, "services": services}), encoding="utf-8")
    return destination


# Use the common guarded deployment with a read-only public content mount.
def deploy(engine, parameters):
    destination = build_portal(engine.base_dir, parameters)
    recipe = {key: parameters[key] for key in ("name", "image", "recreate", "restart", "ports")}
    recipe["volumes"] = [f"{destination}:/usr/share/nginx/html:ro"]
    result = engine._run_container(recipe)
    result.output.append(f"Home content snapshot: {destination}. Open http://<lab-server>:{parameters['ports'][0].split(':')[0]}")
    return result
