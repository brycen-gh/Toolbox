"""Single-container CTFd deployment recipe."""

PARAMETERS = {
    "name": "${CTFD_CONTAINER_NAME}",
    "image": "${CTFD_IMAGE}",
    "recreate": "${CTFD_RECREATE}",
    "restart": "${CTFD_RESTART_POLICY}",
    "ports": ["${CTFD_HOST_PORT}:${CTFD_CONTAINER_PORT}"],
    "volumes": ["${CTFD_DATA_VOLUME}:${CTFD_DATA_PATH}"],
    "environment": {"SECRET_KEY": "${CTFD_SECRET_KEY}"},
}


# Deploy ctfd using the resolved service recipe and shared engine.
def deploy(engine, parameters):
    return engine._run_container(parameters)
