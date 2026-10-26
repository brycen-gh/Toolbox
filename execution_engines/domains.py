"""Validated, portable domain preferences and public service addresses."""

import ipaddress
from pathlib import Path
import re

from .settings import load_variables, save_variables


SERVICE_HOSTS = {
    "home": "home",
    "mattermost": "mattermost",
    "guacamole": "guacamole",
    "openproject": "openproject",
    "etherpad": "etherpad",
    "nextcloud": "nextcloud",
    "moodle": "moodle",
    "ctfd": "ctfd",
    "portainer": "portainer",
    "zulip": "zulip",
}

# Zulip requires a public HTTPS endpoint and retains its direct HTTPS address.
HTTP_PROXY_SERVICES = frozenset(SERVICE_HOSTS) - {"zulip"}


def normalize_domain(value):
    """Accept an optional DNS suffix, returning its canonical ASCII form."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Domain must be a name such as ggsec.org, or blank.")
    domain = value.strip()
    if not domain:
        return ""
    if domain.endswith("."):
        domain = domain[:-1]
    if any(character.isspace() for character in domain) or any(
        character in domain for character in ":/\\@*?#[]"
    ):
        raise ValueError("Enter only the domain, without a scheme, port, path, or wildcard.")
    try:
        domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValueError("Domain contains an invalid DNS label.") from error
    labels = domain.split(".")
    if len(domain) > 253 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise ValueError("Domain must contain DNS labels of up to 63 letters, digits, or hyphens.")
    if any(len(slug) + 1 + len(domain) > 253 for slug in SERVICE_HOSTS.values()):
        raise ValueError("Domain is too long to prefix the lab's service names.")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ValueError("Enter a domain name, not an IP address.")
    if labels[-1].isdigit():
        raise ValueError("A domain's final label cannot be entirely numeric.")
    return domain


def load_domain(base_dir):
    """Read only the optional public domain preference from deployment settings."""
    path = Path(base_dir) / "variables" / "deployment-variables.yaml"
    values = load_variables(path) if path.exists() else {}
    return normalize_domain(values.get("LAB_DOMAIN", ""))


def save_domain(base_dir, domain):
    """Update the domain while retaining all other variables and include owners."""
    domain = normalize_domain(domain)
    path = Path(base_dir) / "variables" / "deployment-variables.yaml"
    values = load_variables(path) if path.exists() else {}
    values["LAB_DOMAIN"] = domain
    save_variables(path, values)
    return domain


def service_url(service, domain, scheme="http"):
    """Build a public proxy URL for a registered service, preserving app paths."""
    domain = normalize_domain(domain)
    key = re.sub(r"[\s_-]+", "", str(service)).lower()
    if key not in SERVICE_HOSTS:
        raise ValueError(f"Unknown public service: {service}")
    if scheme not in {"http", "https"}:
        raise ValueError("Public service URLs require http or https.")
    if not domain:
        return ""
    path = "/guacamole/" if key == "guacamole" else "/"
    return f"{scheme}://{SERVICE_HOSTS[key]}.{domain}{path}"


def hosts_entries(ip, domain):
    """Return a copyable hosts-file block without changing any host settings."""
    domain = normalize_domain(domain)
    if not domain:
        return ""
    try:
        address = str(ipaddress.ip_address(str(ip).strip()))
    except ValueError as error:
        raise ValueError("Hosts entries require a valid server IPv4 or IPv6 address.") from error
    names = [domain, *(f"{slug}.{domain}" for service, slug in SERVICE_HOSTS.items()
                       if service in HTTP_PROXY_SERVICES)]
    return "\n".join(f"{address}\t{name}" for name in names)
