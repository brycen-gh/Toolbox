"""Nextcloud deployment recipe."""

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
    return engine._run_container(parameters)
