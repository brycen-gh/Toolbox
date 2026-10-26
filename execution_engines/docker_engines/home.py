"""Generate the public Home portal without exporting private variables."""
import json
from pathlib import Path
import re
import shutil
import uuid
from urllib.parse import urlsplit
from .moodle import validate_site_url
from ..domains import load_domain, normalize_domain, service_url
from ..network import detect_host_address

PARAMETERS = {
    "name": "${HOME_CONTAINER_NAME}", "image": "${HOME_IMAGE}",
    "recreate": "${HOME_RECREATE}", "restart": "${HOME_RESTART_POLICY}",
    "ports": ["${HOME_HOST_PORT}:80"],
    "directory": "${HOME_DATA_VOLUME}", "public_host": "${HOME_PUBLIC_HOST}",
    "services": [
        {"name": "Mattermost", "url": "${MATTERMOST_SITE_URL}", "description": "Chat with your team in shared channels."},
        {"name": "OpenProject", "port": "${OPENPROJECT_HOST_PORT}", "scheme": "http", "description": "Plan projects, assign work, and track your team's progress."},
        {"name": "Etherpad", "port": "${ETHERPAD_HOST_PORT}", "scheme": "http", "description": "Write together. Share notes and collaborate in real time."},
        {"name": "Nextcloud", "port": "${NEXTCLOUD_HOST_PORT}", "scheme": "http", "description": "Keep your lab files and shared resources in one place."},
        {"name": "Guacamole", "port": "${GUACAMOLE_HOST_PORT}", "scheme": "http", "path": "/guacamole/", "description": "Connect to the lab's remote desktops and terminals in your browser."},
        {"name": "Moodle", "url": "${MOODLE_SITE_URL}", "description": "Open courses, complete activities, and follow your training progress."},
        {"name": "CTFd", "port": "${CTFD_HOST_PORT}", "scheme": "http", "description": "Explore challenges, submit flags, and follow the scoreboard."},
        {"name": "Portainer", "port": "${PORTAINER_HTTPS_HOST_PORT}", "scheme": "https", "description": "Instructor tools for managing the lab's containers."},
        {"name": "Zulip", "port": "${ZULIP_HTTPS_HOST_PORT}", "scheme": "https", "description": "Keep conversations organized with channels and topics."},
    ],
}


def public_services(parameters, domain=""):
    """Publish an allowlisted snapshot of addresses, without deployment settings."""
    domain = normalize_domain(domain)
    services = []
    for item in parameters["services"]:
        if domain and item["name"].casefold() != "zulip":
            services.append({"name": item["name"], "description": item["description"],
                             "url": service_url(item["name"], domain)})
            continue
        if "url" in item:
            url = validate_site_url(item["url"])
            parsed = urlsplit(url)
            if parsed.hostname.casefold() in {"localhost", "localhost.", "127.0.0.1", "::1"}:
                services.append({"name": item["name"], "description": item["description"],
                                 "scheme": parsed.scheme, "port": parsed.port or (443 if parsed.scheme == "https" else 80)})
            else:
                services.append({"name": item["name"], "description": item["description"], "url": url})
            continue
        port = int(item["port"])
        if not 1 <= port <= 65535 or item["scheme"] not in {"http", "https"}:
            raise ValueError("Invalid Home service URL settings")
        service = {"name": item["name"], "description": item["description"], "port": port, "scheme": item["scheme"]}
        if item.get("path"):
            if not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*", item["path"]):
                raise ValueError("Invalid Home service path")
            service["path"] = item["path"]
        services.append(service)
    return services


# Validate public fields and build an independent snapshot for safe recreation.
def build_portal(base_dir, parameters):
    host = str(parameters["public_host"]).strip()
    if host.casefold() in {"localhost", "localhost.", "127.0.0.1", "::1", "[::1]"}:
        host = "auto"
    if host != "auto" and not re.fullmatch(r"[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\]", host):
        raise ValueError("HOME_PUBLIC_HOST must be auto, a hostname, IPv4 address, or bracketed IPv6 address; omit scheme and port.")
    domain = normalize_domain(parameters["domain"]) if "domain" in parameters else load_domain(base_dir)
    services = public_services(parameters, domain)
    root = Path(parameters["directory"]).expanduser()
    if not root.is_absolute():
        root = Path(base_dir) / root
    root = root.resolve()
    if ":" in str(root):
        raise ValueError("Home requires a Linux data path without colons.")
    destination = root / ("site-" + uuid.uuid4().hex)
    shutil.copytree(Path(base_dir) / "assets" / "home", destination)
    address, _ = detect_host_address() if host == "auto" else (None, None)
    (destination / "services.json").write_text(json.dumps({"host": host, "detected_host": address, "services": services}), encoding="utf-8")
    return destination


# Use the common guarded deployment with a read-only public content mount.
def deploy(engine, parameters):
    from ..proxy import proxy_settings

    parameters = {**parameters, "domain": proxy_settings(engine)["domain"]}
    destination = build_portal(engine.base_dir, parameters)
    recipe = {key: parameters[key] for key in ("name", "image", "recreate", "restart", "ports")}
    recipe["_toolbox_service"] = "home"
    recipe["volumes"] = [f"{destination}:/usr/share/nginx/html:ro"]
    result = engine._run_container(recipe)
    address = service_url("home", parameters["domain"]) if parameters["domain"] else f"http://<lab-server>:{parameters['ports'][0].split(':')[0]}"
    result.output.append(f"Home content snapshot: {destination}. Open {address}")
    return result
