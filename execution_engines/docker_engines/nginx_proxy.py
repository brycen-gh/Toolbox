"""Automatic HTTP hostname routes using the upstream nginx-proxy project."""
from copy import deepcopy
from urllib.parse import urlsplit
import re
import uuid

from ..domains import service_url
from ..proxy import ensure_proxy_network, proxy_settings
from ..result import ExecutionResult


PARAMETERS = {
    "name": "${PROXY_CONTAINER_NAME}",
    "image": "${PROXY_IMAGE}",
    "recreate": "${PROXY_RECREATE}",
    "restart": "${PROXY_RESTART_POLICY}",
    "ports": ["${PROXY_HTTP_HOST_PORT}:80"],
    "volumes": ["${PROXY_DOCKER_SOCKET}:/tmp/docker.sock:ro"],
    "directory": "${PROXY_DATA_VOLUME}",
    "environment": {"HTTPS_METHOD": "nohttps", "TRUST_DOWNSTREAM_PROXY": "false"},
}


def _port_conflict(engine, name):
    """Explain occupied port 80 without stopping another host service."""
    rows = engine._docker_read(["container", "ls", "--format", "{{.Names}}\t{{.Ports}}"])
    for row in rows.splitlines():
        owner, _, ports = row.partition("\t")
        if owner != name and re.search(r"(?:^|[,\s])[^,\s]+:80->", ports):
            return ExecutionResult([
                f"Host port 80 is already published by {owner!r}. Stop or reconfigure that service before installing nginx-proxy.",
                "Nginx Proxy Manager and automatic nginx-proxy cannot both publish host port 80.",
            ], 1)
    return ExecutionResult()


def build_vhost_snapshot(engine, parameters, domain):
    """Keep replacement configuration separate from a running proxy's mounts."""
    root = engine._local_data_directory(parameters["directory"])
    directory = root / ("vhosts-" + uuid.uuid4().hex)
    directory.mkdir(parents=True, exist_ok=False)
    guacamole = urlsplit(service_url("guacamole", domain)).hostname
    (directory / (guacamole + "_location")).write_text(
        "proxy_buffering off;\nproxy_read_timeout 3600s;\nproxy_send_timeout 3600s;\n",
        encoding="utf-8",
    )
    nextcloud = urlsplit(service_url("nextcloud", domain)).hostname
    (directory / nextcloud).write_text("client_max_body_size 1g;\n", encoding="utf-8")
    return directory


def deploy(engine, parameters):
    settings = proxy_settings(engine)
    if not settings["enabled"]:
        raise ValueError("Set the optional lab domain in Home options before installing nginx-proxy (for example ggsec.org).")
    if parameters.get("ports") != ["80:80"]:
        raise ValueError("nginx-proxy must publish 80:80 for the generated hostname links")
    names = engine._docker_read(["container", "ls", "-a", "--format", "{{.Names}}"] ).splitlines()
    if parameters["name"] in names and not engine._as_bool(parameters.get("recreate", False), "recreate"):
        return ExecutionResult([f"Container {parameters['name']!r} exists. Enable Recreate existing container to replace it."], 1)
    conflict = _port_conflict(engine, str(parameters["name"]))
    if conflict.returncode:
        return conflict
    network = ensure_proxy_network(engine, settings["network"])
    if network.returncode:
        return network
    destination = build_vhost_snapshot(engine, parameters, settings["domain"])
    recipe = deepcopy(parameters)
    recipe.pop("directory", None)
    recipe["networks"] = [settings["network"]]
    recipe.setdefault("volumes", []).append(f"{destination}:/etc/nginx/vhost.d:ro")
    result = engine._run_container(recipe)
    result.output = network.output + result.output
    if not result.returncode:
        result.output.extend([
            f"Automatic hostname routing is listening on host port 80 for {settings['domain']}.",
            "Install or recreate each application after setting the domain so its discovery environment and network are applied.",
            "Each client must resolve the listed service hostnames to this server's reachable IP using its hosts file or DNS.",
            "This lab proxy uses HTTP. Hosts-file entries do not supply TLS certificates; Zulip keeps its direct HTTPS address.",
            f"Proxy configuration snapshot: {destination}",
        ])
    return result
