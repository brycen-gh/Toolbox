"""Nginx Proxy Manager deployment with persistent configuration and certificates."""

PARAMETERS = {
    "name": "${NGINX_CONTAINER_NAME}",
    "image": "${NGINX_IMAGE}",
    "recreate": "${NGINX_RECREATE}",
    "restart": "${NGINX_RESTART_POLICY}",
    "ports": ["${NGINX_HTTP_HOST_PORT}:80", "${NGINX_ADMIN_HOST_PORT}:81",
              "${NGINX_HTTPS_HOST_PORT}:443"],
    "volumes": ["${NGINX_DATA_VOLUME}/data:/data",
                "${NGINX_DATA_VOLUME}/letsencrypt:/etc/letsencrypt"],
    "extra_args": ["--add-host", "host.docker.internal:host-gateway"],
}


def deploy(engine, parameters):
    result = engine._run_container(parameters)
    if not result.returncode:
        result.output.extend([
            f"Nginx Proxy Manager administration: http://<lab-server>:{parameters['ports'][1].split(':')[0]}",
            "Complete first-run account setup, then add Proxy Hosts pointing to host.docker.internal and each service's published host port.",
            "Enable Websockets Support for chat and collaborative applications.",
            "Configure LAN DNS and each application's public URL/trusted proxy settings to match its proxy hostname.",
            "WSL NAT: forward the HTTP and HTTPS host ports from Windows; keep the administration port restricted to administrators.",
        ])
    return result
