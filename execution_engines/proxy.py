"""Optional hostname routing shared by single-container and Compose recipes.

Saving a domain is configuration only. Docker is touched exclusively when a
deployment calls one of the preparation helpers below.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from .domains import normalize_domain, service_url
from .result import ExecutionResult
from .settings import load_variables


_UPSTREAMS = {
    "home": (None, 80, "http"),
    "mattermost": (None, 8065, "http"),
    "guacamole": (None, 8080, "http"),
    "openproject": ("OPENPROJECT_CONTAINER_PORT", 80, "http"),
    "etherpad": ("ETHERPAD_CONTAINER_PORT", 9001, "http"),
    "nextcloud": ("NEXTCLOUD_CONTAINER_PORT", 80, "http"),
    "moodle": (None, 8080, "http"),
    "ctfd": ("CTFD_CONTAINER_PORT", 8000, "http"),
    "portainer": (None, 9000, "http"),
}


def _service_id(value):
    return re.sub(r"[\s_-]+", "", str(value)).casefold()


def proxy_settings(engine):
    """Read saved defaults, respecting the variables of the current action."""
    base_dir = getattr(engine, "base_dir", None)
    values = {}
    # Recipe unit tests and integrations sometimes provide partial engine mocks.
    if isinstance(base_dir, (str, bytes, os.PathLike)):
        path = Path(base_dir) / "variables" / "deployment-variables.yaml"
        if path.is_file():
            values = load_variables(path)
    context = getattr(engine, "_deployment_context", None)
    if isinstance(context, dict):
        values.update(context)
    domain = normalize_domain(values.get("LAB_DOMAIN", ""))
    network = str(values.get("PROXY_NETWORK", "toolbox-proxy")).strip()
    if domain:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", network) or network in {"bridge", "host", "none", "default"}:
            raise ValueError("PROXY_NETWORK must name a dedicated Docker network, for example toolbox-proxy")
        try:
            port = int(values.get("PROXY_HTTP_HOST_PORT", 80))
        except (TypeError, ValueError) as exc:
            raise ValueError("PROXY_HTTP_HOST_PORT must be 80 for the generated hostname links") from exc
        if port != 80:
            raise ValueError("PROXY_HTTP_HOST_PORT must be 80 for the generated hostname links")
    return {"enabled": bool(domain), "domain": domain, "network": network, "values": values}


def canonical_url(engine, service_id):
    """Return a service's HTTP lab URL, or None for direct-port mode."""
    settings = proxy_settings(engine)
    return (service_url(service_id, settings["domain"])
            if settings["enabled"] and _service_id(service_id) in _UPSTREAMS else None)


def route_for(service_id, domain, values=None):
    """Build nginx-proxy discovery metadata for one public frontend."""
    domain = normalize_domain(domain)
    service_id = _service_id(service_id)
    if not domain or service_id not in _UPSTREAMS:
        return {}
    key, default_port, protocol = _UPSTREAMS[service_id]
    raw_port = (values or {}).get(key, default_port) if key else default_port
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid upstream port for {service_id}: {raw_port!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"Invalid upstream port for {service_id}: {raw_port!r}")
    hostname = urlsplit(service_url(service_id, domain)).hostname
    return {"VIRTUAL_HOST": hostname + "," + domain if service_id == "home" else hostname,
            "VIRTUAL_PORT": str(port), "VIRTUAL_PROTO": protocol}


def ensure_proxy_network(engine, network):
    """Create a missing shared bridge; failures never proceed to deployment."""
    output = []
    try:
        names = engine._docker_read(["network", "ls", "--format", "{{.Name}}"] ).splitlines()
        code = 0
        if network not in names:
            created = engine._run_steps([["docker", "network", "create", "--driver", "bridge", network]])
            output.extend(created.output)
            code = created.returncode
            if code == 130:
                return ExecutionResult(output, 130)
        # Verify after create even on failure: another deployment can win the race.
        info = json.loads(engine._docker_read(["network", "inspect", network]))
        if (not isinstance(info, list) or not info or info[0].get("Name") != network
                or info[0].get("Driver") != "bridge" or info[0].get("Internal")):
            return ExecutionResult(output + [f"Docker network {network!r} must be a non-internal bridge network."], 1)
        if code:
            output.append(f"Shared network {network!r} is available after a concurrent creation attempt.")
        return ExecutionResult(output)
    except (RuntimeError, ValueError, OSError) as exc:
        return ExecutionResult(output + [f"Cannot prepare shared proxy network {network!r}: {exc}"], 1)


def _application_environment(service_id, route, environment):
    """Keep application redirects and cookies consistent with the HTTP lab URL."""
    hostname = route["VIRTUAL_HOST"]
    url = "http://" + hostname
    if service_id == "openproject":
        environment.update({"OPENPROJECT_HOST__NAME": hostname, "OPENPROJECT_HTTPS": "false"})
    elif service_id == "etherpad":
        environment["TRUST_PROXY"] = "true"
    elif service_id == "ctfd":
        environment["REVERSE_PROXY"] = "true"
    elif service_id == "nextcloud":
        # Fixed overwrite values avoid trusting every container on a shared CIDR.
        trusted = str(environment.get("NEXTCLOUD_TRUSTED_DOMAINS", "")).split()
        environment.update({"NEXTCLOUD_TRUSTED_DOMAINS": " ".join(dict.fromkeys([*trusted, hostname])),
                            "OVERWRITEHOST": hostname, "OVERWRITEPROTOCOL": "http",
                            "OVERWRITECLIURL": url, "APACHE_DISABLE_REWRITE_IP": "1"})


def prepare_container(engine, parameters):
    """Return a copy with routing and network flags, plus preparation status."""
    recipe = deepcopy(parameters)
    service_id = _service_id(recipe.get("_toolbox_service", ""))
    if service_id not in _UPSTREAMS:
        return recipe, ExecutionResult()
    settings = proxy_settings(engine)
    if not settings["enabled"]:
        return recipe, ExecutionResult()
    route = route_for(service_id, settings["domain"], settings["values"])
    # Explicit port overrides in a single-container recipe take precedence.
    if service_id != "portainer" and recipe.get("ports"):
        target = str(recipe["ports"][0]).rsplit(":", 1)[-1].split("/", 1)[0]
        if target.isdigit() and 1 <= int(target) <= 65535:
            route["VIRTUAL_PORT"] = str(int(target))
    if any(str(value).split("=", 1)[0] in {"--net", "--network"} for value in recipe.get("extra_args", [])):
        raise ValueError("Hostname routing manages the frontend network; remove extra_args --network overrides")
    network = settings["network"]
    if recipe.get("networks") not in (None, [], [network]):
        raise ValueError("Hostname routing requires the shared proxy network on this frontend")
    environment = recipe.setdefault("environment", {})
    environment.update(route)
    _application_environment(service_id, route, environment)
    if service_id == "portainer":
        command = recipe.setdefault("command", [])
        if "--http-disabled" in command:
            raise ValueError("Portainer hostname routing needs its internal HTTP listener; remove --http-disabled")
        if "--http-enabled" not in command:
            command.append("--http-enabled")
    recipe["networks"] = [network]
    recipe["expose"] = list(dict.fromkeys([*recipe.get("expose", []), route["VIRTUAL_PORT"]]))
    result = ensure_proxy_network(engine, network)
    if not result.returncode:
        result.output.append(f"Hostname route: {service_url(service_id, settings['domain'])} (nginx-proxy must be running on host port 80).")
    return recipe, result


def attach_to_compose(engine, document, service_key, service_id):
    """Attach only a Compose frontend while retaining its private stack network."""
    settings = proxy_settings(engine)
    if not settings["enabled"]:
        return ExecutionResult()
    if _service_id(service_id) == "zulip":
        return ExecutionResult(["Zulip requires public HTTPS and keeps its configured direct HTTPS address; the hostname proxy serves HTTP lab routes."])
    route = route_for(service_id, settings["domain"], settings["values"])
    if not route:
        raise ValueError(f"No proxy route is registered for {service_id!r}")
    network = settings["network"]
    frontend = document["services"][service_key]
    frontend.setdefault("environment", {}).update(route)
    expose = frontend.setdefault("expose", [])
    if route["VIRTUAL_PORT"] not in [str(port) for port in expose]:
        expose.append(route["VIRTUAL_PORT"])
    # Without an explicit default here Compose disconnects the frontend from DBs.
    networks = frontend.setdefault("networks", ["default"])
    alias = "toolbox_proxy"
    definitions = document.setdefault("networks", {})
    expected = {"external": True, "name": network}
    if alias in definitions and definitions[alias] != expected:
        raise ValueError("Compose network toolbox_proxy is reserved for hostname routing")
    definitions.setdefault("default", {})
    definitions[alias] = expected
    if isinstance(networks, dict):
        networks.setdefault(alias, {})
    elif isinstance(networks, list):
        if alias not in networks:
            networks.append(alias)
    else:
        raise ValueError("Compose frontend networks must be a mapping or list")
    return ensure_proxy_network(engine, network)
