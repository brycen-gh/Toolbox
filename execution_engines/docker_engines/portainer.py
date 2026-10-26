"""Portainer deployment recipe, including its Docker socket mount."""

PARAMETERS = {
    "name": "${PORTAINER_CONTAINER_NAME}",
    "image": "${PORTAINER_IMAGE}",
    "recreate": "${PORTAINER_RECREATE}",
    "restart": "${PORTAINER_RESTART_POLICY}",
    "command": ["--setup-token", "${PORTAINER_SETUP_TOKEN}"],
    "ports": [
        "${PORTAINER_EDGE_HOST_PORT}:${PORTAINER_EDGE_CONTAINER_PORT}",
        "${PORTAINER_HTTPS_HOST_PORT}:${PORTAINER_HTTPS_CONTAINER_PORT}",
    ],
    "volumes": [
        "${PORTAINER_DOCKER_SOCKET}:${PORTAINER_DOCKER_SOCKET_TARGET}",
        "${PORTAINER_DATA_VOLUME}:${PORTAINER_DATA_PATH}",
    ],
}


# Deploy portainer using the resolved service recipe and shared engine.
def deploy(engine, parameters):
    command = parameters.get("command", [])
    if "--setup-token" in command:
        index = command.index("--setup-token") + 1
        if index >= len(command) or not str(command[index]).strip():
            raise ValueError("Portainer setup token cannot be empty")
        engine._sensitive_values.add(str(command[index]))
    return engine._run_container(parameters)
